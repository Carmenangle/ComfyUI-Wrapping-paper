import { getTemplateRaw, type Template } from "../api/workflows";
import { workflowPorts, type PortOp } from "../api/ai";
import { uploadImage } from "../api/comfyui";
import type { RichContent } from "../components/RichInput";
import type { ChatMessage } from "../types/chat";
import { fmtOpResults } from "./opResults";
import { isLafMessage } from "./lafLock";

type Chat = { baseUrl: string; apiKey: string; modelName: string };

export interface OrchestrationDeps {
  messages: ChatMessage[];
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
  templates: Template[];
  chat: Chat;
  comfyuiUrl: string;
  imageStyle?: string;  // 用户选的提示词风格 ""/sd/gpt/banana，透传给 workflowPorts
  styleTemplate?: string;  // 选中的自定义风格存档内容（非空时优先）
  pushBot: (text: string) => void;
  runFreeText: (t: string, content?: RichContent) => void;
}

// 工作流输入口编排：读节点结构 → AI 出计划 → 写画布/capturedGraph。
// 从 ChatView 抽出，通过 deps 拿到消息列表、模板、对话模型与回退对话能力。
// 对外只暴露 findWorkflowCardByName / planWorkflowOps / applyWorkflowOps / ignoreWorkflowOps。
export function useWorkflowOrchestration(deps: OrchestrationDeps) {
  const { messages, setMessages, templates, chat, comfyuiUrl, imageStyle, styleTemplate, pushBot, runFreeText } = deps;

  // 按 /a 后的文本找工作流卡：文本以某卡的模板名开头即匹配（其后为编排需求）。
  // 返回卡与命中的模板名，供剥离出需求部分。文本为空则取最近一张有编排能力的卡（matchedName=""）。
  const findWorkflowCardByName = (rest: string): { card: ChatMessage; matchedName: string } | null => {
    const orchable = (m: ChatMessage) => {
      if (!m.workflow) return false;
      const tpl = templates.find((t) => t.id === m.workflow!.templateId);
      if (!tpl) return false;
      return (tpl.input_node_ids?.length || 0) > 0 || (tpl.output_node_ids?.length || 0) > 0
        || !!tpl.prompt_node_id || !!tpl.image_node_id;
    };
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i];
      if (!orchable(m)) continue;
      const tn = m.workflow!.templateName || "";
      if (!rest) return { card: m, matchedName: "" };            // 空 → 最近可编排卡
      if (tn && rest.startsWith(tn)) return { card: m, matchedName: tn };  // 以模板名开头
    }
    return null;
  };

  // 向某工作流卡的某节点 iframe 发消息并等指定类型回复
  const askNodeFrame = <T,>(cardId: string, nodeId: string, send: object, expectType: string, ms = 4000) =>
    new Promise<T | null>((resolve) => {
      const frame = document.getElementById(`laf-node-${cardId}-${nodeId}`) as HTMLIFrameElement | null;
      if (!frame?.contentWindow) return resolve(null);
      let done = false;
      const onMsg = (ev: MessageEvent) => {
        const d = ev.data;
        if (!isLafMessage(d, expectType)) return;
        if (ev.source !== frame.contentWindow) return;
        done = true;
        window.removeEventListener("message", onMsg);
        resolve(d.payload as T);
      };
      window.addEventListener("message", onMsg);
      frame.contentWindow.postMessage({ target: "laf_lock", ...send }, "*");
      setTimeout(() => { if (!done) { window.removeEventListener("message", onMsg); resolve(null); } }, ms);
    });

  // dataURI/URL → File，供上传到 ComfyUI input
  const srcToFile = async (src: string, name: string): Promise<File> => {
    const resp = await fetch(src);
    const blob = await resp.blob();
    const ext = (blob.type.split("/")[1] || "png").split("+")[0];
    return new File([blob], `${name}.${ext}`, { type: blob.type || "image/png" });
  };

  // 规划工作流输入口填充：收集该卡节点结构 → AI 出计划 → push 计划消息（待确认）。
  // force=false 时先让 AI 判断意图，非编排（普通问答/修饰词/翻译）自动回退到 AI 对话。
  const planWorkflowOps = async (card: ChatMessage, text: string, content: RichContent, force: boolean) => {
    const images = content.images || [];
    let raw;
    try { raw = await getTemplateRaw(card.workflow!.templateId); }
    catch { return runFreeText(text, content); }  // 读不到模板 → 退回对话，别卡住
    const nodeIds: string[] = raw.exposed_ids || [];
    if (nodeIds.length === 0) {
      // 没配替换节点：不参与编排（防乱改），直接走对话
      return runFreeText(text, content);
    }
    // 读节点结构（已确认卡从 capturedGraph，未确认卡从画布 iframe）
    let schemas: unknown[] = [];
    if (card.workflow!.done && card.workflow!.capturedGraph) {
      schemas = schemaFromCapturedGraph(card.workflow!.capturedGraph, nodeIds);
    } else {
      for (const id of nodeIds) {
        const r = await askNodeFrame<{ nodes: unknown[] }>(
          card.id, id, { type: "request_node_schema", payload: { nodeIds: [id] } }, "node_schema",
        );
        if (r?.nodes) schemas.push(...r.nodes);
      }
    }
    if (schemas.length === 0) {
      // 读不到结构：force 时提示重试；否则退回对话（不打扰）
      if (force) {
        setMessages((m) => [...m, { id: crypto.randomUUID(), role: "user", text }]);
        pushBot("没能读到节点结构（画布可能还在载入）。请稍等画布载入完成后再点「AI 编排」。");
        return;
      }
      return runFreeText(text, content);
    }
    const modelName = guessModelName(raw.workflow);
    let plan;
    try {
      plan = await workflowPorts(text, images.length, schemas, modelName, chat, force, imageStyle || "", styleTemplate || "");
    } catch (e) {
      if (force) {
        setMessages((m) => [...m, { id: crypto.randomUUID(), role: "user", text }]);
        pushBot(`规划失败：${(e as Error).message}`);
        return;
      }
      return runFreeText(text, content);  // 判定阶段出错 → 退回对话
    }
    // AI 判定这句不是编排意图 → 转普通对话（新手无需记指令）
    if (plan.is_orchestration === false && !force) {
      return runFreeText(text, content);
    }
    // 是编排：push 用户消息 + 计划卡（待确认）
    setMessages((m) => [
      ...m,
      { id: crypto.randomUUID(), role: "user", text, parts: content.parts },
      {
        id: crypto.randomUUID(),
        role: "assistant",
        text: "",
        portsPlan: {
          cardId: card.id,
          summary: plan.summary || "",
          ops: plan.ops || [],
          images,
          status: "pending",
        },
      },
    ]);
  };

  // 从 capturedGraph(API格式 {id:{class_type,inputs}}) 提取选中节点的输入结构，供 AI 改参
  const schemaFromCapturedGraph = (graph: any, nodeIds: string[]): unknown[] => {
    const out: unknown[] = [];
    for (const id of nodeIds) {
      const node = graph?.[id];
      if (!node) continue;
      const inputs: any[] = [];
      const widgets: any[] = [];
      for (const [name, v] of Object.entries(node.inputs || {})) {
        if (Array.isArray(v)) {
          // [srcId, slot] = 连线输入
          inputs.push({ name, type: "", connected: true, source_type: "" });
        } else {
          // 标量 = widget 当前值
          widgets.push({ name, type: typeof v, value: v });
        }
      }
      out.push({ id: String(id), type: node.class_type || "", title: "", inputs, widgets });
    }
    return out;
  };

  // 从工作流 JSON 里猜 checkpoint/模型名（用于提示词风格）
  const guessModelName = (wf: any): string => {
    const nodes = wf?.nodes;
    if (!Array.isArray(nodes)) return "";
    for (const n of nodes) {
      const t = String(n.type || "");
      if (/Checkpoint|UNETLoader|Loader/i.test(t) && Array.isArray(n.widgets_values)) {
        const s = n.widgets_values.find((v: unknown) => typeof v === "string" && /\.(safetensors|ckpt|gguf|sft)$/i.test(v));
        if (s) return s;
      }
    }
    return "";
  };

  // 应用一条编排计划：未确认卡→写画布后自动「选择完毕」；已确认卡→直接改 capturedGraph
  const applyWorkflowOps = async (planMsgId: string) => {
    const planMsg = messages.find((m) => m.id === planMsgId);
    const plan = planMsg?.portsPlan;
    if (!plan) return;
    const card = messages.find((m) => m.id === plan.cardId);
    if (!card?.workflow) { pushBot("目标工作流卡不存在。"); return; }

    if (card.workflow.done) {
      await applyOpsToCaptured(planMsgId, plan, card);
    } else {
      await applyOpsToCanvas(planMsgId, plan, card);
    }
  };

  // 未确认卡：上传图 → 构造 ops → 触发本卡「选择完毕」（在全图隐藏 iframe 里 apply_ops 后抓参，
  // 这样 AI 新建的 LoadImage/连线能被原生 graphToPrompt 正确纳入），抓完自动卸载画布省显存。
  const applyOpsToCanvas = async (
    planMsgId: string,
    plan: NonNullable<ChatMessage["portsPlan"]>,
    card: ChatMessage,
  ) => {
    // 先上传需要用图的 op（set_image，或 kind=image 的 replace_output），换成 ComfyUI 文件名
    const uploaded: Record<number, string> = {};
    const needsImage = (op: PortOp) =>
      op.action === "set_image" || (op.action === "replace_output" && op.kind === "image");
    for (const op of plan.ops) {
      if (needsImage(op) && op.image_index && !uploaded[op.image_index]) {
        const src = plan.images[op.image_index - 1];
        if (!src) continue;
        try {
          const file = await srcToFile(src, `laf_${Date.now()}_${op.image_index}`);
          const up = await uploadImage(file, comfyuiUrl);
          uploaded[op.image_index] = up.name;
        } catch (e) {
          pushBot(`图${op.image_index} 上传失败：${(e as Error).message}`);
        }
      }
    }
    // 构造扁平 ops（已带 value / image_name），交给本卡在全图 iframe 执行
    const ops = plan.ops.map((op) => {
      const o: any = { node_id: String(op.node_id), input: op.input, action: op.action };
      if (op.action === "set_widget") o.value = op.value;
      if (op.action === "set_image") o.image_name = uploaded[op.image_index || 0] || "";
      if (op.action === "replace_output") {
        o.output = op.output;
        o.kind = op.kind;
        if (op.kind === "image") o.image_name = uploaded[op.image_index || 0] || "";
        else o.value = op.value;
      }
      return o;
    });
    markPlanApplied(planMsgId);
    pushBot("正在写入画布并自动「选择完毕」（抓取参数、关闭画布省显存）…");
    // 触发本卡 handleDone(ops)：全图 iframe 载入 → apply_ops → graphToPrompt → 卸载画布
    window.dispatchEvent(new CustomEvent("laf-finish-card", { detail: { cardId: card.id, ops } }));
  };

  // 已确认卡：画布已关，直接改 capturedGraph(API格式)。仅支持改 widget 标量；
  // set_image 在已确认态无法新建节点连线 → 退化为改其上游 LoadImage 的 image，失败则提示重开画布。
  const applyOpsToCaptured = async (
    planMsgId: string,
    plan: NonNullable<ChatMessage["portsPlan"]>,
    card: ChatMessage,
  ) => {
    const graph: any = JSON.parse(JSON.stringify(card.workflow!.capturedGraph));
    const results: any[] = [];
    const uploaded: Record<number, string> = {};
    for (const op of plan.ops) {
      const r: any = { node_id: String(op.node_id), input: op.input, ok: false, msg: "" };
      const node = graph[String(op.node_id)];
      if (!node) { r.msg = "节点不存在于已确认工作流"; results.push(r); continue; }
      if (op.action === "set_widget") {
        node.inputs[op.input] = op.value;
        r.ok = true;
      } else if (op.action === "set_image") {
        // 上传图
        let name = uploaded[op.image_index || 0];
        if (!name && op.image_index) {
          const src = plan.images[op.image_index - 1];
          if (src) {
            try {
              const file = await srcToFile(src, `laf_${Date.now()}_${op.image_index}`);
              name = (await uploadImage(file, comfyuiUrl)).name;
              uploaded[op.image_index] = name;
            } catch (e) { r.msg = `图上传失败：${(e as Error).message}`; results.push(r); continue; }
          }
        }
        const cur = node.inputs[op.input];
        if (Array.isArray(cur) && graph[cur[0]]?.class_type === "LoadImage") {
          // 该口连着 LoadImage → 改它的 image 文件名
          graph[cur[0]].inputs.image = name;
          r.ok = true;
        } else {
          r.msg = "该口未连 LoadImage，已确认态无法新建节点，请点「更改」重开画布处理";
        }
      } else if (op.action === "replace_output") {
        // 输出口替换需新建源节点并重接下游连线，已确认态(画布已关)做不了 → 提示重开画布
        r.input = op.output || op.input;
        r.msg = "输出口替换需在画布执行，请点「更改」重开画布后再让我处理";
      } else {
        r.msg = "未知动作";
      }
      results.push(r);
    }
    // 写回 capturedGraph
    setMessages((ms) =>
      ms.map((m) =>
        m.id === card.id && m.workflow
          ? { ...m, workflow: { ...m.workflow, capturedGraph: graph } }
          : m,
      ),
    );
    markPlanApplied(planMsgId);
    const okN = results.filter((r) => r.ok).length;
    pushBot(`已更新参数 ${okN}/${results.length} 项（已确认工作流）：\n${fmtOpResults(results)}\n直接输入 /s 提交，改动会和未修改节点一起出图。`);
  };

  const markPlanApplied = (planMsgId: string) =>
    setMessages((ms) =>
      ms.map((m) =>
        m.id === planMsgId && m.portsPlan
          ? { ...m, portsPlan: { ...m.portsPlan, status: "applied" } }
          : m,
      ),
    );

  const ignoreWorkflowOps = (planMsgId: string) =>
    setMessages((ms) =>
      ms.map((m) =>
        m.id === planMsgId && m.portsPlan
          ? { ...m, portsPlan: { ...m.portsPlan, status: "ignored" } }
          : m,
      ),
    );

  return { findWorkflowCardByName, planWorkflowOps, applyWorkflowOps, ignoreWorkflowOps };
}
