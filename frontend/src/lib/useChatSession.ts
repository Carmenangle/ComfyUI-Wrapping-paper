// 聊天会话引擎：从 ChatView 抽出的「持久化 + 生成编排」深簇。
// 拥有 messages / 生成生命周期 reducer / 各类 ref 与加载·落盘 effect，
// 对外只暴露渲染所需的状态与动作句柄；UI 局部态（模型选择/面板开关/尺寸）留在 ChatView。
// 接口即测试面：整台生成引擎集中一处，不必渲染千行组件即可推演其行为。
import { type MutableRefObject, useEffect, useReducer, useRef, useState } from "react";
import type { ChatMessage, MsgPart } from "../types/chat";
import type { Repo } from "../stores/repos";
import type { useSettings } from "../stores/settings";
import { activeStyleTemplate } from "../stores/settings";
import type { RichContent } from "../components/RichInput";
import type { Template } from "../api/workflows";
import {
  comfyStatus, startComfy, submitGraph, getResult, viewUrl,
  saveLocal, saveLocalSrc, localViewUrl, interruptComfy, type GenResult,
} from "../api/comfyui";
import {
  imageAgentStream, fetchHistory, indexGeneration, appendMessage, multiAgent,
  saveSnapshot, fetchSnapshot, fetchAgentRunning, cancelAgent,
  fetchInspiration, extractKeywords, compactHistory,
} from "../api/ai";
import {
  reduce as reduceGen, initialGenState,
  streamingBotId, needsConfirm, runningPromptId, queuedItem,
} from "./generationLifecycle";
import { useWorkflowOrchestration } from "./workflowOrchestration";
import { needsImageInput, hasImageProvided, pickBestText, slimSnapshot as slimSnapshotPure } from "./chatGeneration";

type Model = { baseUrl: string; apiKey: string; modelName: string };

export interface ChatSessionDeps {
  repo?: Repo;
  settings: ReturnType<typeof useSettings>["settings"];
  setCover: (id: string, cover: string) => void;
  chat: Model;                                   // 当前对话模型（智能体大脑+反推）
  genModel: Model;                               // 当前生图模型
  size: string;                                  // 生图尺寸 "宽x高"
  templates: Template[];
  setShowPicker: (v: boolean) => void;           // 与 /w 选择浮层共享
  atBottomRef: MutableRefObject<boolean>;        // 与滚动跟随 UI 共享
  multiMode?: boolean;                           // 多 Agent 模式：自由文本走 Supervisor 编排端点（复用同一生命周期）
}

// PLACEHOLDER_BODY

export function useChatSession(deps: ChatSessionDeps) {
  const { repo, settings, setCover, chat, genModel, size, templates, setShowPicker, atBottomRef } = deps;

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  // 破坏性操作确认弹窗：由 UI 渲染 ConfirmModal，用户选择后 resolve 这个 promise
  const [confirmReq, setConfirmReq] = useState<{ message: string; resolve: (ok: boolean) => void } | null>(null);
  const askConfirm = (message: string) =>
    new Promise<boolean>((resolve) => {
      setConfirmReq({
        message,
        resolve: (ok) => { setConfirmReq(null); resolve(ok); },
      });
    });
  // 生成生命周期单一真相源（reducer）：取代原 streamingId/wfRunning/imgStartedRef/pendingPromptRef + queueRef 影子镜像。
  const [gen, dispatch] = useReducer(reduceGen, initialGenState);
  // 只读派生别名
  const streamingId = streamingBotId(gen);             // 正在流式的 bot 气泡 id（渲染转圈用）
  const wfRunning = gen.status.kind === "workflow";    // /s 工作流进行中
  const queued = gen.queue;                            // 排队列表（渲染队列条用）
  const abortRef = useRef<(() => void) | null>(null);      // 中断当前流式生成
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);  // 切回后等后台落盘的轮询
  const bgRunningRef = useRef(false);  // 后台任务进行中：此时后端拥有快照写权，前端不抢写以免覆盖
  // 对话线 id = 仓库 id（首页用 "home"）：后端按此落盘多轮记忆与 RAG 知识库
  const threadId = repo?.id || "home";
  const chatKey = `laf_chat_${threadId}`;
  const loadedRef = useRef(false);  // 标记本仓库消息已加载，避免初始空数组覆盖已存记录
  const snapTimer = useRef<ReturnType<typeof setTimeout> | null>(null);  // 后端快照防抖

  const pushBot = (text: string) =>
    setMessages((m) => [...m, { id: crypto.randomUUID(), role: "assistant", text }]);
  // 通用：追加一条任意消息（多 Agent 模式用，可带 user 角色 / 图片）
  const pushMsg = (msg: Partial<ChatMessage>) =>
    setMessages((m) => [...m, { id: crypto.randomUUID(), role: "assistant", text: "", ...msg } as ChatMessage]);

  // 压缩上下文：AI 把历史+生成记录总结成一条摘要，清空对话线，只留摘要。知识库/资产不动。
  // 生成进行中不允许压缩（避免与流式落盘打架）。返回是否成功。
  const [compacting, setCompacting] = useState(false);
  const compact = async (): Promise<boolean> => {
    if (streamingId || wfRunning || compacting) return false;
    const ok = await askConfirm(
      "压缩会把本仓库的对话历史总结成一段摘要，并清空当前对话（只保留摘要）。\n" +
      "已生成的图片、提示词、知识库都会保留，不受影响。确定压缩吗？",
    );
    if (!ok) return false;
    setCompacting(true);
    try {
      const r = await compactHistory(threadId, chat, settings.embedModel);
      if (r.ok && r.message) {
        setMessages([{ id: r.message.id, role: "assistant", text: r.message.text } as ChatMessage]);
        return true;
      }
      pushBot("压缩失败：没有可压缩的内容或摘要为空。");
      return false;
    } catch (e) {
      pushBot("压缩失败：" + (e as Error).message);
      return false;
    } finally {
      setCompacting(false);
    }
  };

  // 进入仓库/切换时加载消息，三级兜底：本地 localStorage → 后端消息流快照 → langgraph 对话历史。
  useEffect(() => {
    let alive = true;
    loadedRef.current = false;
    let shownLocal = false;
    const local = localStorage.getItem(chatKey);
    if (local) {
      try {
        const arr = JSON.parse(local) as ChatMessage[];
        if (arr.length > 0) {
          setMessages(arr);
          shownLocal = true;
        }
      } catch { /* 本地损坏则走后端兜底 */ }
    }
    // 切回/刷新时若后台仍有生成任务在跑，轮询快照等其落盘后自动回显。
    // 必须无论快照是否已有内容都执行——正常对话后快照必然非空，若放在
    // 加载兜底的 early-return 之后就永远跑不到，等于后台化失效。
    const maybeStartBgPoll = async () => {
      try {
        if (!alive || pollRef.current) return;
        const st = await fetchAgentRunning(threadId);
        if (!alive || !st.running) return;
        bgRunningRef.current = true;  // 后台在跑：暂停前端快照写，避免覆盖后端落盘
        const poll = setInterval(async () => {
          if (!alive) { clearInterval(poll); return; }
          try {
            const [snap, run] = await Promise.all([
              fetchSnapshot(threadId),
              fetchAgentRunning(threadId),
            ]);
            if (!alive) { clearInterval(poll); return; }
            if (snap.items && snap.items.length > 0) {
              setMessages(snap.items as ChatMessage[]);
            }
            if (!run.running) { bgRunningRef.current = false; clearInterval(poll); }  // 后台跑完
          } catch { /* 后端波动，下次再试 */ }
        }, 1500);
        pollRef.current = poll;
      } catch { /* 状态接口失败，忽略 */ }
    };
    (async () => {
      try {
        const snap = await fetchSnapshot(threadId);
        if (!alive) return;
        if (snap.items && snap.items.length > 0) {
          setMessages(snap.items as ChatMessage[]);
          loadedRef.current = true;
          await maybeStartBgPoll();
          return;
        }
      } catch { /* 快照接口失败，继续兜底 */ }
      if (shownLocal) { loadedRef.current = true; await maybeStartBgPoll(); return; }  // 本地已渲染、后端无快照
      try {
        const r = await fetchHistory(threadId);
        if (!alive) return;
        setMessages(
          (r.items || []).map((m) => {
            const imgs = m.images || [];
            const parts: MsgPart[] = [];
            if (m.content) parts.push({ type: "text", text: m.content });
            for (const u of imgs) parts.push({ type: "image", url: u });
            return {
              id: crypto.randomUUID(),
              role: m.role === "assistant" ? "assistant" : "user",
              text: m.content,
              parts: parts.length > 0 ? parts : undefined,
            };
          }),
        );
      } catch { /* 后端未起/无历史，保持空 */ }
      finally { if (alive) loadedRef.current = true; }
      await maybeStartBgPoll();
    })();
    return () => {
      alive = false;
      abortRef.current?.();
      abortRef.current = null;
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
      bgRunningRef.current = false;
      dispatch({ t: "reset" });  // 清空生成状态 + 待发队列，避免串到新仓库
    };
  }, [threadId]);
  // APPEND_HERE

  // 存快照前给图片瘦身：把用户上传的 data:URI 大图落盘转 local-view 小地址。
  const persistDataUri = async (src: string): Promise<string> => {
    if (typeof src === "string" && src.startsWith("data:") && settings.outputDir && repo?.id) {
      try {
        const s = await saveLocalSrc({ src, repoId: repo.id, outputDir: settings.outputDir });
        return localViewUrl(s.path);
      } catch { /* 保留原图 */ }
    }
    return src;
  };
  const slimSnapshot = (msgs: ChatMessage[]) => slimSnapshotPure(msgs, persistDataUri);

  // 消息变化时持久化：本地即时写（快取）+ 后端快照防抖写（可靠真源）。
  useEffect(() => {
    if (!loadedRef.current) return;  // 加载完成前不写，防止空数组覆盖
    const slim = messages.map((m) =>
      m.workflow ? { ...m, workflow: { ...m.workflow, capturedGraph: null } } : m,
    );
    try {
      localStorage.setItem(chatKey, JSON.stringify(slim));
    } catch { /* 超额等忽略 */ }
    if (snapTimer.current) clearTimeout(snapTimer.current);
    const tid = threadId;
    snapTimer.current = setTimeout(async () => {
      if (bgRunningRef.current) return;  // 后台任务在写快照，前端不抢写以免覆盖后端落盘
      const full = await slimSnapshot(messages);
      saveSnapshot(tid, full).catch(() => {});  // 后端未起则忽略，本地仍在
      if (tid === threadId && JSON.stringify(full) !== JSON.stringify(messages)) {
        setMessages(full);
      }
    }, 600);
  }, [messages, chatKey, threadId]);

  // 选中模板 → 在对话流插入工作流节点卡（卡内嵌锁定画布）
  const pickTemplate = (t: Template) => {
    const card: ChatMessage = {
      id: crypto.randomUUID(),
      role: "assistant",
      text: "",
      workflow: {
        templateId: t.id,
        templateName: t.name,
        capturedGraph: null,
        done: false,
      },
    };
    setMessages((m) => [...m, card]);
    setShowPicker(false);
  };

  // 「选择完毕」：存下从 iframe 抓取的工作流并标记完成
  const markCardDone = (msgId: string, graph: unknown) =>
    setMessages((ms) =>
      ms.map((m) =>
        m.id === msgId && m.workflow
          ? { ...m, workflow: { ...m.workflow, capturedGraph: graph, done: true } }
          : m,
      ),
    );

  // 「更改」：把已确认的卡重置为未完成
  const markCardReopen = (msgId: string) =>
    setMessages((ms) =>
      ms.map((m) =>
        m.id === msgId && m.workflow
          ? { ...m, workflow: { ...m.workflow, done: false } }
          : m,
      ),
    );

  // 按名称选模板（/w 名称）
  const pickByName = (name: string) => {
    const t = templates.find((x) => x.name === name) || templates.find((x) => x.name.includes(name));
    if (t) pickTemplate(t);
    else pushBot(`没找到名为「${name}」的模板。输入 /w 查看可选模板。`);
  };
  // APPEND2_HERE

  // ===== 进行中生图任务持久化（切仓库/刷新后可恢复）=====
  const pendingKey = `laf_pending_gen_${threadId}`;
  const getPending = (): { prompt_id: string; createdAt: number }[] => {
    try { return JSON.parse(localStorage.getItem(pendingKey) || "[]"); } catch { return []; }
  };
  const addPending = (promptId: string) => {
    const list = getPending().filter((p) => p.prompt_id !== promptId);
    list.push({ prompt_id: promptId, createdAt: Date.now() });
    try { localStorage.setItem(pendingKey, JSON.stringify(list)); } catch { /* ignore */ }
  };
  const removePending = (promptId: string) => {
    try {
      localStorage.setItem(pendingKey, JSON.stringify(getPending().filter((p) => p.prompt_id !== promptId)));
    } catch { /* ignore */ }
  };

  // 已 finalize 的 promptId，防同一次生成被 pollResult 与切回 resume 重复落盘=重复出图
  const finalizedRef = useRef<Set<string>>(new Set());

  // 把一次已完成的生成结果落成消息 + 留存 + 入库 + 切词 + 落盘。返回是否产出了内容。
  const finalizeGeneration = async (r: GenResult, promptId?: string): Promise<boolean> => {
    // 去重双闸：
    // ① 持久化 pending——已被 removePending（这轮收尾过）的 promptId 不在 pending 里，直接跳过。
    //    这是跨「进出仓库/重挂」的可靠去重（内存 finalizedRef 重挂即失效，是三张重复的根）。
    // ② 内存 finalizedRef——防同一实例内 pollResult 与 resume 并发重入（removePending 前的窗口）。
    if (promptId && !getPending().some((p) => p.prompt_id === promptId)) return false;
    if (promptId && finalizedRef.current.has(promptId)) return false;
    const best = pickBestText(r.texts);
    if ((r.images?.length || 0) === 0 && !best) return false;
    if (promptId) finalizedRef.current.add(promptId);
    const imgs = await Promise.all(
      (r.images || []).map(async (img) => {
        if (settings.outputDir && repo?.id) {
          try {
            const s = await saveLocal({ img, repoId: repo.id, outputDir: settings.outputDir, url: settings.comfyuiUrl });
            return localViewUrl(s.path);
          } catch { /* 留存失败回退在线 */ }
        }
        return viewUrl(img, settings.comfyuiUrl);
      }),
    );
    const blocks: ChatMessage[] = [];
    if (imgs.length > 0) {
      blocks.push({ id: crypto.randomUUID(), role: "assistant", text: best, image: imgs[0] });
      for (const url of imgs.slice(1)) {
        blocks.push({ id: crypto.randomUUID(), role: "assistant", text: "", image: url });
      }
    } else {
      blocks.push({ id: crypto.randomUUID(), role: "assistant", text: best });
    }
    // 追加图后立即落盘 snapshot（不等 600ms 防抖）：退出仓库会整体卸载 ChatView，
    // 防抖来不及跑就丢图 → 返回时 fetchSnapshot 读到旧快照(无图)，卡在"运转中"。
    // 用函数式回调捕获追加后的完整数组，同步写快照，保证退出返回图仍在。
    const tid = threadId;
    setMessages((m) => {
      const next = [...m, ...blocks];
      slimSnapshot(next).then((full) => saveSnapshot(tid, full).catch(() => {})).catch(() => {});
      return next;
    });
    if (imgs.length > 0 && repo?.id) setCover(repo.id, imgs[0]);
    let autoTags = "";
    if (best.trim()) {
      try { autoTags = (await extractKeywords(best, chat)).tags.join(","); } catch { /* 兜底后端切 */ }
    }
    // 入库(Chroma 写入)完成后再派发刷新事件——否则资产库抢在写入前拉取，读不到新图。
    const indexJobs: Promise<unknown>[] = [];
    if (imgs.length > 0) {
      // 每张都带上提示词+标签(同批同提示词)：原来只给第 0 张，一旦第 0 张入库失败整批提示词全丢。
      // 每张各自带，Chroma 按 image_url 的确定性 doc_id 各存一条，无单点丢失。
      imgs.forEach((url) => {
        indexJobs.push(
          indexGeneration(threadId, { prompt: best, tags: autoTags, image_url: url }, settings.embedModel)
            .catch((e) => console.error("[资产库入库失败]", threadId, url, e)),
        );
      });
    } else {
      indexJobs.push(
        indexGeneration(threadId, { prompt: best, tags: autoTags, image_url: "" }, settings.embedModel)
          .catch((e) => console.error("[资产库入库失败]", threadId, e)),
      );
    }
    // 全部入库落定后才通知资产库刷新（不阻塞对话显示，异步等待）
    Promise.all(indexJobs).then(() => {
      window.dispatchEvent(new CustomEvent("laf-generation-saved", { detail: threadId }));
    });
    appendMessage(threadId, "assistant", best, imgs).catch(() => {});
    return true;
  };

  // 轮询某次生成的结果，拿到图片后插入对话流
  const pollResult = (promptId: string) => {
    addPending(promptId);  // 记进行中，切仓库/刷新后可恢复
    dispatch({ t: "workflowStart", promptId });  // 状态 C：工作流出图中
    let tries = 0;
    const tick = async () => {
      tries += 1;
      try {
        const r = await getResult(promptId, settings.comfyuiUrl);
        if (r.status === "completed") {
          const got = await finalizeGeneration(r, promptId);
          // 仅当确实无任何产出时提示；去重跳过(got=false 但 r 有内容)不误报
          if (!got && (r.images?.length || 0) === 0 && !pickBestText(r.texts)) {
            pushBot("生成完成，但没有输出（工作流未含 SaveImage 或文字输出节点）。");
          }
          removePending(promptId);
          dispatch({ t: "workflowDone", promptId });  // reducer 内置所有权守卫，只清自己这轮
          return;
        }
      } catch {
        // 历史还没出，继续等
      }
      // 前 150 次每 2 秒（快轮询 5 分钟），之后转慢守望每 15 秒，直到 ~20 分钟硬上限。
      // 全程不 removePending：即使用户不切仓库干等，超长任务(实测 71 节点 4.4 分钟，
      // 甚至更久)出图后也能被这条守望自动 finalize，不再丢图。
      if (tries === 150) {
        // 快轮询阶段结束仍没完成：解除"运转中"占用不阻塞操作，但继续后台慢守望。
        dispatch({ t: "workflowDone", promptId });
        pushBot("生成较复杂、仍在后台进行，出图后会自动载入（也可在 ComfyUI 面板看进度）。");
      }
      if (tries < 210) {
        setTimeout(tick, tries < 150 ? 2000 : 15000);
      }
      // 达 210 次(约 20 分钟)仍未出：停止本轮守望，但保留 pending，
      // 下次进仓库/刷新由 resume 兜底重查。
    };
    setTimeout(tick, 1500);
  };

  // 模板是否定义了图像输入口 / 图值是否已填 → 见 lib/chatGeneration（纯逻辑，已抽出可测）
  // APPEND3_HERE

  // /s 启动：取最近一张已确认的工作流卡，用抓取到的画布工作流提交生成
  const runWorkflow = async () => {
    const card = [...messages].reverse().find((m) => m.workflow?.done);
    if (!card || !card.workflow) {
      pushBot("没有已确认的工作流。先用 /w 选模板，在画布里调好后点「选择完毕」，再 /s 启动。");
      return;
    }
    const wf = card.workflow;
    if (!wf.capturedGraph) {
      pushBot("没抓到画布内容，请重新点「选择完毕」。");
      return;
    }
    const tpl = templates.find((t) => t.id === wf.templateId);
    if (tpl && needsImageInput(tpl) && !hasImageProvided(wf.capturedGraph, tpl)) {
      pushBot("这是图生图工作流，需要输入图。请点「更改」在画布的图像节点里提供输入图，再 /s 启动。");
      return;
    }
    let comfyUp = false;
    try {
      const st = await comfyStatus(settings.comfyuiUrl);
      comfyUp = !!st.running;
    } catch { comfyUp = false; }
    if (!comfyUp) {
      if (settings.comfyuiPath) {
        pushBot("ComfyUI 未启动，正在尝试自动拉起，请稍候 20~40 秒后重试 /s …");
        startComfy(settings.comfyuiPath, settings.comfyuiUrl).catch(() => {});
      } else {
        pushBot("ComfyUI 未启动（8188 无响应）。请先启动 ComfyUI，或在「设置」填写 ComfyUI 目录后由工具自动启动。");
      }
      return;
    }
    try {
      const r = await submitGraph(wf.capturedGraph, settings.comfyuiUrl);
      pushBot(`已提交到 ComfyUI 生成（prompt_id: ${r.prompt_id}，${r.node_count} 个节点），正在运转工作流…`);
      if (r.prompt_id) pollResult(r.prompt_id);
    } catch (e) {
      pushBot(`启动失败：${(e as Error).message}`);
    }
  };

  // 进入仓库/切回时，恢复"进行中的生图任务"。
  const resumedRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    let alive = true;
    const resume = async () => {
      for (let i = 0; i < 40 && !loadedRef.current; i++) await new Promise((r) => setTimeout(r, 100));
      if (!alive) return;
      const list = getPending();
      for (const p of list) {
        if (resumedRef.current.has(p.prompt_id)) continue;  // 本会话已处理过，不重复
        resumedRef.current.add(p.prompt_id);
        if (Date.now() - p.createdAt > 30 * 60 * 1000) { removePending(p.prompt_id); continue; }
        try {
          const r = await getResult(p.prompt_id, settings.comfyuiUrl);
          if (!alive) return;
          if (r.status === "completed") {
            await finalizeGeneration(r, p.prompt_id);
            removePending(p.prompt_id);
            dispatch({ t: "workflowDone", promptId: p.prompt_id });  // 补清工作流态，否则切回后卡在"运转中"
          } else {
            pollResult(p.prompt_id);  // 仍在跑，重新挂轮询
          }
        } catch {
          pollResult(p.prompt_id);    // 查询失败按仍在跑处理，继续轮询
        }
      }
    };
    resume();
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threadId]);
  // APPEND4_HERE

  // 发送入口：生成进行中默认进队列，否则直接执行
  const send = (content: RichContent) => {
    const text = content.text.trim();
    if (!text && content.images.length === 0) return;
    atBottomRef.current = true;  // 用户主动发送时强制跟随到底
    if (streamingId || wfRunning) { enqueue(content); return; }
    dispatchSend(content);
  };

  // /w 选模板、/s 出图的公共前缀路由。命中并处理则返回 true。
  const routeWorkflowCmd = (text: string): boolean => {
    if (text === "/w") { setShowPicker(true); return true; }
    if (text.startsWith("/w ")) {
      setMessages((m) => [...m, { id: crypto.randomUUID(), role: "user", text }]);
      pickByName(text.slice(3).trim());
      return true;
    }
    if (text === "/s") {
      setMessages((m) => [...m, { id: crypto.randomUUID(), role: "user", text }]);
      runWorkflow();
      return true;
    }
    return false;
  };

  // 真正执行一条发送（已确保当前无进行中生成）
  const dispatchSend = (content: RichContent) => {
    const text = content.text.trim();
    if (!text && content.images.length === 0) return;
    if (routeWorkflowCmd(text)) return;
    // /压缩 或 /compact：压缩当前对话上下文（AI 触发也可在对话里说"压缩上下文"再点确认）
    if (text === "/压缩" || text === "/compact") { compact(); return; }
    // /find 主题：联网找灵感 → 提炼成提示词灵感卡
    if (text === "/find" || text.startsWith("/find ")) {
      const q = text.slice(5).trim();
      if (!q) { setMessages((m) => [...m, { id: crypto.randomUUID(), role: "user", text }]); pushBot("请在 /find 后写要找的灵感主题，如 /find 哥特萝莉裙"); return; }
      runFindInspiration(q, content);
      return;
    }
    // /a 模板名 [需求]：显式请求编排 → 强制编排，跳过意图判定。
    if (text === "/a" || text.startsWith("/a ")) {
      const rest = text.slice(2).trim();  // "模板名 需求"
      const found = findWorkflowCardByName(rest);
      if (!found) {
        setMessages((m) => [...m, { id: crypto.randomUUID(), role: "user", text }]);
        pushBot(rest
          ? `没找到匹配「${rest}」的工作流卡。请先用 /w 选择该工作流，或点卡片上的「AI 编排」。`
          : "请在 /a 后写工作流模板名（或点工作流卡上的「AI 编排」按钮），再补充你的编排需求。");
        return;
      }
      const { card, matchedName } = found;
      const scene = rest.slice(matchedName.length).trim();  // 去掉模板名，剩余为自然语言需求
      planWorkflowOps(card, scene, { ...content, text: scene }, true);  // force 编排
      return;
    }
    // 智能路由：有可编排工作流卡时先让 AI 判断是否编排意图，否则转对话
    const orchCard = findWorkflowCardByName("");
    if (orchCard) {
      planWorkflowOps(orchCard.card, text, content, false);  // force=false：带意图判定
      return;
    }
    // 其余一律交给图像智能体（多 Agent 模式走 Supervisor 编排，复用同一生命周期）
    runFreeText(text, content, deps.multiMode === true);
  };

  // 把消息加入队列
  const enqueue = (content: RichContent) => {
    dispatch({ t: "enqueue", item: { id: crypto.randomUUID(), text: content.text.trim(), content } });
  };

  // 当前轮生成结束后，自动取队首执行下一条
  const flushQueue = () => {
    const next = gen.queue[0];
    if (!next) return;
    dispatch({ t: "dequeue" });
    dispatchSend(next.content);
  };

  // 取消队列里的某条
  const cancelQueued = (id: string) => {
    dispatch({ t: "removeQueued", id });
  };

  // 生成结束（idle）后自动出队执行下一条
  useEffect(() => {
    if (gen.status.kind === "idle" && gen.queue.length > 0) {
      const t = setTimeout(flushQueue, 0);  // 让本轮状态落定再发，避免同步竞态
      return () => clearTimeout(t);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gen.status.kind, gen.queue.length]);

  // AI 建议按钮点击：执行单条指令（/w 选模板、/s 出图）。其余走智能体。
  const runCommand = (cmd: string) => {
    const text = cmd.trim();
    if (!text) return;
    if (routeWorkflowCmd(text)) return;
    runFreeText(text);
  };
  // APPEND5_HERE

  // 自由文本 → 图像智能体（多轮上下文）：对话模型自主调反推/生图工具。
  // multi=true 走 Supervisor 多 Agent 端点（LangGraph 编排），复用同一套生命周期（消息/图片/状态/落盘），
  // 仅后端端点不同 + 多 onTrace 协作过程。这是"前端生命周期与后端 agent 解耦"的体现。
  const runFreeText = (t: string, content?: RichContent, multi = false) => {
    const images = content?.images || [];
    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      text: t,
      parts: content?.parts,
    };
    const botId = crypto.randomUUID();
    setMessages((m) => [
      ...m,
      userMsg,
      { id: botId, role: "assistant", text: "" },
    ]);
    dispatch({ t: "agentStart", botId });  // 进入 agent 态（未出图）
    const append = (delta: string) =>
      setMessages((ms) =>
        ms.map((m) => (m.id === botId ? { ...m, text: m.text + delta } : m)),
      );
    const onImage = (shown: string, id?: string) => {
      dispatch({ t: "agentImage" });  // 已触发生图 → 进入状态 B（打断需二次确认）
      setMessages((m) => [...m, { id: id || crypto.randomUUID(), role: "assistant", text: "", image: shown }]);
      if (repo?.id) setCover(repo.id, shown);
      window.dispatchEvent(new CustomEvent("laf-generation-saved", { detail: threadId }));
    };
    const onInspiration = (card: { id?: string; query: string; prompt: string; tags: string[]; sources: { title: string; url: string }[] }) => {
      setMessages((m) => [...m, {
        id: card.id || crypto.randomUUID(), role: "assistant", text: "",
        inspiration: { query: card.query, prompt: card.prompt, tags: card.tags || [], sources: card.sources || [] },
      }]);
    };
    const onDone = (err?: string) => {
      dispatch({ t: "agentDone" });
      abortRef.current = null;
      if (err) {
        setMessages((ms) =>
          ms.map((m) => (m.id === botId ? { ...m, text: m.text || `对话失败：${err}` } : m)),
        );
      }
    };
    if (multi) {
      // 多 Agent：trace（主管分派→专家执行）作为过程行 append 进 bot 文本，其余回调复用
      abortRef.current = multiAgent(
        threadId, t, images, chat, genModel, size,
        {
          onTrace: (line) => append(`${line}\n`),
          onDelta: append,
          onImage, onInspiration, onDone,
        },
        { outputDir: settings.outputDir, repoId: repo?.id || threadId, embed: settings.embedModel, proxyUrl: settings.proxyEnabled ? settings.proxyUrl : "" },
      );
      return;
    }
    abortRef.current = imageAgentStream(
      threadId, t, images, chat, genModel, size, append, onImage,
      onDone,
      { outputDir: settings.outputDir, repoId: repo?.id || threadId, embed: settings.embedModel, messageId: botId, proxyUrl: settings.proxyEnabled ? settings.proxyUrl : "", style: "", styleTemplate: activeStyleTemplate(settings), agentId: settings.activeAgentId || "" },
      onInspiration,
    );
  };

  // 工作流输入口编排（见 lib/workflowOrchestration）：依赖 runFreeText，故声明其后。
  const { findWorkflowCardByName, planWorkflowOps, applyWorkflowOps, ignoreWorkflowOps } =
    useWorkflowOrchestration({
      messages, setMessages, templates, chat,
      comfyuiUrl: settings.comfyuiUrl, imageStyle: "", styleTemplate: activeStyleTemplate(settings), pushBot, runFreeText,
    });

  // /find：联网找灵感 → 灵感卡（显式指令路径，不走 agent）
  const runFindInspiration = async (query: string, content?: RichContent) => {
    setMessages((m) => [...m, {
      id: crypto.randomUUID(), role: "user",
      text: content?.text?.trim() || `/find ${query}`, parts: content?.parts,
    }]);
    const loadId = crypto.randomUUID();
    setMessages((m) => [...m, { id: loadId, role: "assistant", text: `正在联网搜索「${query}」的灵感…` }]);
    try {
      const card = await fetchInspiration(query, chat, settings.proxyEnabled ? settings.proxyUrl : "");
      setMessages((ms) => ms.map((m) => m.id === loadId
        ? { id: m.id, role: "assistant", text: "",
            inspiration: { query: card.query, prompt: card.prompt, tags: card.tags || [], sources: card.sources || [] } }
        : m));
    } catch (e) {
      setMessages((ms) => ms.map((m) => m.id === loadId
        ? { ...m, text: `找灵感失败：${(e as Error).message}` } : m));
    }
  };

  // 真正停止后台生成
  const hardCancel = async (promptId: string | null): Promise<void> => {
    try { await cancelAgent(threadId); } catch { /* 后端未起忽略 */ }
    if (promptId) {
      try { await interruptComfy(settings.comfyuiUrl, promptId); } catch { /* 忽略 */ }
    }
    abortRef.current?.();
    abortRef.current = null;
  };

  // 中断当前生成（「停止」按钮）
  const stopGenerating = async () => {
    if (needsConfirm(gen)) {
      const ok = await askConfirm(
        "正在生成图片 / 运转工作流。强行停止会中止本次生成（工作流任务也会停止，已发起的云端调用可能作废）。确定停止吗？",
      );
      if (!ok) return;
    }
    const sid = streamingId;
    const pid = runningPromptId(gen);
    dispatch({ t: "stop" });  // 一次性转 idle
    await hardCancel(pid);
    if (sid) {
      setMessages((ms) =>
        ms.map((m) => (m.id === sid && !m.text && !m.image ? { ...m, text: "（已停止生成）" } : m)),
      );
    }
  };

  // 队列条「引导」：把该排队消息以「打断+合并」方式立即执行。
  const guideQueued = async (id: string) => {
    const item = queuedItem(gen, id);
    if (!item) return;
    if (needsConfirm(gen)) {
      const ok = await askConfirm(
        "当前正在云端生图 / 运转工作流。\n\n" +
        "打断会中止本次生成：已发起的云端调用可能作废且不退费，工作流任务也会停止。\n\n" +
        "确定要打断并让 AI 结合已生成内容继续处理这条消息吗？",
      );
      if (!ok) return;  // 用户取消 → 保留在队列
    }
    const sid = streamingId;
    const pid = runningPromptId(gen);
    dispatch({ t: "removeQueued", id });  // 出队该条
    dispatch({ t: "stop" });              // 停当前生成（保留半成品）
    await hardCancel(pid);
    if (sid) {
      setMessages((ms) =>
        ms.map((m) => (m.id === sid ? { ...m, text: (m.text || "") + "（已打断）" } : m)),
      );
    }
    dispatchSend(item.content);  // 同 thread 新一轮：AI 带上下文续写 = 合并
  };

  return {
    messages, streamingId, wfRunning, queued,
    send, runCommand, pushBot, pushMsg,
    pickTemplate, markCardDone, markCardReopen,
    applyWorkflowOps, ignoreWorkflowOps,
    stopGenerating, guideQueued, cancelQueued,
    confirmReq, compact, compacting,
  };
}
