import { useEffect, useRef, useState } from "react";
import {
  Boxes,
  CornerDownRight,
  MessagesSquare,
  Archive,
  Palette,
  PanelRight,
  Send,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { type Repo } from "../stores/repos";
import { useSettings } from "../stores/settings";
import { KnowledgeModal } from "../components/KnowledgeModal";
import { RichInput, type RichInputHandle } from "../components/RichInput";
import { WorkflowCard } from "../components/WorkflowCard";
import { useChatSession } from "../lib/useChatSession";
import { ConfirmModal } from "../components/Modal";
import { StylePresetModal } from "../components/StylePresetModal";
import { UserMessage, AssistantMessage, InspirationCard, PortsPlanCard } from "../components/chat/ChatMessages";
import { ModelSwitcher, SizeSwitcher, ChatEmptyLanding } from "../components/chat/ChatControls";
import { comfyStatus, startComfy } from "../api/comfyui";
import { listTemplates, type Template } from "../api/workflows";
import { indexDocument } from "../api/ai";
import { calcSize } from "../lib/viewRouting";

export function ChatView({
  repo,
  settings,
  update,
  presets,
  setCover,
  onBack,
  initialImage,
  onImageConsumed,
}: {
  repo?: Repo;
  settings: ReturnType<typeof useSettings>["settings"];
  update: ReturnType<typeof useSettings>["update"];
  presets: Pick<ReturnType<typeof useSettings>, "addStylePreset" | "updateStylePreset" | "removeStylePreset">;
  setCover: (id: string, cover: string) => void;
  onBack?: () => void;
  initialImage?: string | null;              // 从资产库「发送至对话」带来的图，挂载后插入输入框
  onImageConsumed?: () => void;
}) {
  const streamRef = useRef<HTMLDivElement | null>(null);   // 对话滚动容器
  const atBottomRef = useRef(true);                        // 用户当前是否贴在底部（决定是否自动跟随）
  const richRef = useRef<RichInputHandle | null>(null);

  // 资产库带图进来：挂载后插入输入框一次
  useEffect(() => {
    if (initialImage) {
      richRef.current?.insertImage(initialImage);
      richRef.current?.focus();
      onImageConsumed?.();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialImage]);
  const [hasText, setHasText] = useState(false);  // 输入框是否有可发送内容（文本或图片，驱动发送按钮）
  // 对话线 id = 仓库 id（首页用 "home"）：后端按此落盘多轮记忆与 RAG 知识库
  const threadId = repo?.id || "home";

  // 记录用户是否贴在底部：滚动时更新（容差 80px）
  const onStreamScroll = () => {
    const el = streamRef.current;
    if (!el) return;
    atBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  };

  const [modelId, setModelId] = useState(
    settings.activeImageModelId || settings.imageModels[0]?.id || "",
  );
  // 当前选中的对话模型（智能体大脑 + 反推）
  const [chatModelId, setChatModelId] = useState(
    settings.activeChatModelId || settings.chatModels[0]?.id || "",
  );
  // 生图尺寸：比例 + 分辨率档
  const [aspect, setAspect] = useState<string>("1:1");
  const [resTier, setResTier] = useState<string>("1k");
  const [showStylePresets, setShowStylePresets] = useState(false);  // 风格存档管理弹窗
  const activeChat = settings.chatModels.find((m) => m.id === chatModelId) || settings.chatModels[0];
  const chat = { baseUrl: activeChat?.baseUrl || "", apiKey: activeChat?.apiKey || "", modelName: activeChat?.modelName || "" };
  // 当前选中的生图模型（底部下拉），传给 agent 的生图工具
  const gm = settings.imageModels.find((m) => m.id === modelId) || settings.imageModels[0];
  const genModel = { baseUrl: gm?.baseUrl || "", apiKey: gm?.apiKey || "", modelName: gm?.modelName || "" };
  // ComfyUI 节点面板
  const [showComfy, setShowComfy] = useState(false);
  const [comfyRunning, setComfyRunning] = useState(false);
  const [comfyMsg, setComfyMsg] = useState("");
  // 工作流模板与 /w 选择浮层
  const [templates, setTemplates] = useState<Template[]>([]);
  const [showPicker, setShowPicker] = useState(false);
  // 知识库：手动参考资料入库弹窗
  const [showKnowledge, setShowKnowledge] = useState(false);
  const [indexingDoc, setIndexingDoc] = useState(false);

  // 聊天会话引擎：messages/生成生命周期/持久化/编排全部集中在 useChatSession（见 lib/useChatSession）。
  const {
    messages, streamingId, wfRunning, queued,
    send, runCommand, pushBot,
    pickTemplate, markCardDone, markCardReopen,
    applyWorkflowOps, ignoreWorkflowOps,
    stopGenerating, guideQueued, cancelQueued,
    confirmReq, compact, compacting,
  } = useChatSession({
    repo, settings, setCover, chat, genModel,
    size: calcSize(aspect, resTier), templates, setShowPicker, atBottomRef,
  });

  const submitDocument = (title: string, text: string) => {
    setIndexingDoc(true);
    indexDocument(threadId, text, title, settings.embedModel)
      .then((r) => {
        setShowKnowledge(false);
        pushBot(`已入库 ${r.chunks} 条参考资料，后续对话会自动检索引用。`);
      })
      .catch((e) => pushBot(`参考资料入库失败：${(e as Error).message}`))
      .finally(() => setIndexingDoc(false));
  };

  useEffect(() => {
    listTemplates().then((r) => setTemplates(r.items)).catch(() => {});
  }, []);

  // 消息变化时智能跟随：仅当用户原本就在底部才自动滚到底
  useEffect(() => {
    const el = streamRef.current;
    if (el && atBottomRef.current) el.scrollTop = el.scrollHeight;
  }, [messages]);

  // 面板打开时轮询 ComfyUI 状态
  useEffect(() => {
    if (!showComfy) return;
    let alive = true;
    const check = async () => {
      try {
        const s = await comfyStatus(settings.comfyuiUrl);
        if (alive) setComfyRunning(s.running);
      } catch {
        if (alive) setComfyRunning(false);
      }
    };
    check();
    const t = setInterval(check, 3000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [showComfy, settings.comfyuiUrl]);

  const onStartComfy = async () => {
    if (!settings.comfyuiPath) {
      setComfyMsg("请先在「设置 → 路径」填写 ComfyUI 目录。");
      return;
    }
    setComfyMsg("正在启动 ComfyUI（首次较慢）…");
    try {
      const r = await startComfy(settings.comfyuiPath, settings.comfyuiUrl);
      setComfyMsg(r.message);
    } catch (e) {
      setComfyMsg(`启动失败：${(e as Error).message}`);
    }
  };

  return (
    <div className="chat-view">
      <div className="chat-view-head">
        {onBack && <button className="back-btn" onClick={onBack}>← 返回</button>}
        <h1>{repo?.name ?? "想生成什么？"}</h1>
        <button
          className="btn"
          style={{ marginLeft: "auto" }}
          onClick={compact}
          disabled={compacting || !!streamingId || wfRunning}
          title="把当前对话历史总结成一段摘要并清空对话（图片/提示词/知识库保留），缓解上下文过长"
        >
          <Archive size={15} style={{ verticalAlign: "-2px", marginRight: 4 }} />
          {compacting ? "压缩中…" : "压缩上下文"}
        </button>
        <button
          className="btn"
          onClick={() => setShowKnowledge(true)}
          title="录入角色设定、画风说明等，AI 对话自动检索"
        >
          <Boxes size={15} style={{ verticalAlign: "-2px", marginRight: 4 }} />
          知识库
        </button>
        <button
          className={`btn ${showComfy ? "primary" : ""}`}
          onClick={() => setShowComfy((s) => !s)}
        >
          <PanelRight size={15} style={{ verticalAlign: "-2px", marginRight: 4 }} />
          ComfyUI 节点面板
        </button>
      </div>

      <div className="chat-layout">
        <div className="chat-col">
          <div className="chat-stream" ref={streamRef} onScroll={onStreamScroll}>
            {messages.length === 0 && <ChatEmptyLanding />}
            {messages.map((m) =>
              m.role === "user" ? (
                <UserMessage key={m.id} msg={m} onAddToChat={(url) => richRef.current?.insertImage(url)} />
              ) : m.workflow ? (
                <WorkflowCard
                  key={m.id}
                  msg={m}
                  comfyUrl={settings.comfyuiUrl}
                  chatModel={chat}
                  onDone={(graph) => markCardDone(m.id, graph)}
                  onReopen={() => markCardReopen(m.id)}
                  onNotify={pushBot}
                  onOrchestrate={() => {
                    // 「AI 编排」：往输入框填入 /a 模板名 ，用户补充需求后发送即走编排
                    richRef.current?.insertText(`/a ${m.workflow!.templateName} `);
                  }}
                />
              ) : m.portsPlan ? (
                <PortsPlanCard
                  key={m.id}
                  plan={m.portsPlan}
                  onApply={() => applyWorkflowOps(m.id)}
                  onIgnore={() => ignoreWorkflowOps(m.id)}
                />
              ) : m.inspiration ? (
                <InspirationCard
                  key={m.id}
                  data={m.inspiration}
                  onInsert={(text) => richRef.current?.insertText(text)}
                />
              ) : (
                <AssistantMessage
                  key={m.id}
                  msg={m}
                  streaming={m.id === streamingId}
                  onRunCommand={runCommand}
                  onSendImage={(url) => {
                    richRef.current?.insertImage(url);
                    richRef.current?.focus();
                  }}
                  onRefineImage={(url) => {
                    // 识图微调：填一句自然语言 + 这张图，交给智能体自行反推并改图
                    richRef.current?.insertText("参考这张图，反推它的提示词后按我的要求改图：");
                    richRef.current?.insertImage(url);
                    richRef.current?.focus();
                  }}
                />
              ),
            )}
          </div>

          <div className="chat-input-wrap">
            {showPicker && (
              <div className="tpl-picker">
                <div className="tpl-picker-head">
                  <span>选择工作流模板</span>
                  <button
                    className="icon-btn"
                    style={{ background: "transparent", color: "var(--text)" }}
                    onClick={() => setShowPicker(false)}
                  >
                    <X size={15} />
                  </button>
                </div>
                {templates.length === 0 ? (
                  <p style={{ color: "var(--text-muted)", fontSize: 13, padding: "8px 12px" }}>
                    还没有模板，去「工作流模板」里创建并保存。
                  </p>
                ) : (
                  templates.map((t) => (
                    <button key={t.id} className="tpl-item" onClick={() => pickTemplate(t)}>
                      <strong>{t.name}</strong>
                      <span style={{ color: "var(--text-muted)", fontSize: 12 }}>
                        {t.exposed.length} 个字段
                      </span>
                    </button>
                  ))
                )}
              </div>
            )}
          <div className="chat-input-bar">
        {queued.length > 0 && (
          <div className="queue-strip">
            {queued.map((q) => (
              <div className="queue-row" key={q.id}>
                <CornerDownRight size={14} className="queue-row-icon" />
                <span className="queue-row-text" title={q.text || "（图片）"}>
                  {q.text || "（图片）"}
                </span>
                <button
                  className="queue-row-btn"
                  title="打断当前生成，让 AI 结合已生成内容继续处理这条（生图/工作流会先确认后果）"
                  onClick={() => guideQueued(q.id)}
                >
                  <CornerDownRight size={13} /> 引导
                </button>
                <button className="queue-row-del" title="删除这条排队消息" onClick={() => cancelQueued(q.id)}>
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
          </div>
        )}
        <RichInput
          ref={richRef}
          onSubmit={send}
          onCanSubmitChange={setHasText}
          templateNames={templates.map((t) => t.name)}
          placeholder="说出你想要的：描述画面直接生图、贴图让它反推或改图、提问绘画；/w 可选专业工作流。Enter 发送，图片用上方 + 添加或直接粘贴"
        />
        <div className="chat-actions">
          <ModelSwitcher
            icon={<MessagesSquare size={18} />}
            label="对话模型"
            items={settings.chatModels.map((m) => ({ id: m.id!, name: m.modelName || "未命名模型" }))}
            activeId={chatModelId}
            emptyHint="未配置对话模型（去设置添加）"
            onPick={(id) => { setChatModelId(id); update({ activeChatModelId: id }); }}
          />
          <ModelSwitcher
            icon={<Sparkles size={18} />}
            label="生图模型"
            items={settings.imageModels.map((m) => ({ id: m.id, name: m.modelName || "未命名模型" }))}
            activeId={modelId}
            emptyHint="未配置生图模型（去设置添加）"
            onPick={(id) => { setModelId(id); update({ activeImageModelId: id }); }}
          />
          <SizeSwitcher
            aspect={aspect}
            resTier={resTier}
            onPick={(a, t) => { setAspect(a); setResTier(t); }}
          />
          <ModelSwitcher
            icon={<Palette size={18} />}
            label="提示词风格"
            items={[
              { id: "none", name: "不启用（原样直出）" },
              ...(settings.stylePresets || []).map((p) => ({ id: `preset:${p.id}`, name: `★ ${p.name || "未命名存档"}` })),
              { id: "__manage__", name: "＋ 管理风格存档…" },
            ]}
            activeId={settings.imageStyle && settings.imageStyle.startsWith("preset:") ? settings.imageStyle : "none"}
            emptyHint="提示词风格"
            onPick={(id) => {
              if (id === "__manage__") { setShowStylePresets(true); return; }
              update({ imageStyle: id === "none" ? "" : id });
            }}
          />
          {(streamingId || wfRunning) ? (
            <>
              {/* 生成中仍可发送：Enter 或点此 = 打断并合并（生图/工作流流程会先确认） */}
              <button
                className="btn primary"
                title="打断当前生成并发送，AI 会带上下文续写；若在生图/工作流会先确认"
                onClick={() => richRef.current?.submit()}
                disabled={!hasText}
              >
                <Send size={16} style={{ marginRight: 6, verticalAlign: "-2px" }} />
                发送
              </button>
              <button className="btn danger" title="仅停止当前生成，不发送" onClick={stopGenerating}>
                <X size={16} style={{ marginRight: 6, verticalAlign: "-2px" }} />
                停止
              </button>
            </>
          ) : (
            <button className="btn primary" onClick={() => richRef.current?.submit()} disabled={!hasText}>
              <Send size={16} style={{ marginRight: 6, verticalAlign: "-2px" }} />
              发送
            </button>
          )}
        </div>
      </div>
          </div>
        </div>

        {showComfy && (
          <div className="comfy-panel">
            <div className="comfy-panel-head">
              <strong>ComfyUI 节点面板</strong>
              <button
                className="icon-btn"
                style={{ background: "transparent", color: "var(--text)" }}
                onClick={() => setShowComfy(false)}
              >
                <X size={16} />
              </button>
            </div>
            {comfyRunning ? (
              <iframe className="comfy-frame" src={settings.comfyuiUrl} title="ComfyUI" />
            ) : (
              <div className="comfy-empty">
                <p style={{ color: "var(--text-muted)" }}>
                  ComfyUI 未运行。复杂节点（如 D 站画廊）需在原生界面里选图操作。
                </p>
                <button className="btn primary" onClick={onStartComfy}>
                  启动 ComfyUI
                </button>
                {comfyMsg && <p style={{ color: "var(--text-muted)", fontSize: 13 }}>{comfyMsg}</p>}
              </div>
            )}
          </div>
        )}
      </div>

      {showKnowledge && (
        <KnowledgeModal
          repoName={repo?.name ?? "首页"}
          repoId={threadId}
          busy={indexingDoc}
          embed={settings.embedModel}
          onSubmit={submitDocument}
          onClose={() => setShowKnowledge(false)}
        />
      )}
      {confirmReq && (
        <ConfirmModal
          title="确认操作"
          message={confirmReq.message}
          confirmText="停止"
          danger
          onConfirm={() => confirmReq.resolve(true)}
          onCancel={() => confirmReq.resolve(false)}
        />
      )}
      {showStylePresets && (
        <StylePresetModal
          presets={settings.stylePresets || []}
          onAdd={presets.addStylePreset}
          onUpdate={presets.updateStylePreset}
          onRemove={presets.removeStylePreset}
          onClose={() => setShowStylePresets(false)}
        />
      )}
    </div>
  );
}

