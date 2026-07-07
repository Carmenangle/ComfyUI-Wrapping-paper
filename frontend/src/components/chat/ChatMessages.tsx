import { useState } from "react";
import { Bot, ChevronDown, CornerDownRight, ExternalLink, Play, Plus, RefreshCw, Send, Sparkles, Workflow } from "lucide-react";
import type { ChatMessage } from "../../types/chat";
import type { PortOp } from "../../api/ai";
import { CopyButton } from "../CopyButton";
import { openLightbox } from "../Lightbox";

// 内联图片 chip：缩略小图，悬停弹出大图预览浮窗
export function ImageChip({ url, onAddToChat }: { url: string; onAddToChat?: (url: string) => void }) {
  return (
    <span className="img-chip">
      <img src={url} alt="图片" className="img-chip-thumb" onClick={() => openLightbox(url)} />
      {/* 悬停大图预览：pointer-events:none + 定位在上方，避免遮挡小图触发 hover 抖动闪烁 */}
      <span className="img-chip-pop">
        <img src={url} alt="预览" />
      </span>
      {onAddToChat && (
        <button
          className="img-chip-add"
          title="把这张图添加到输入框"
          onClick={(e) => { e.stopPropagation(); onAddToChat(url); }}
        >
          <Plus size={12} />
        </button>
      )}
    </span>
  );
}

// 用户消息：支持图文混排（parts 按顺序渲染，图片为内联 chip+悬停预览），否则纯文本
export function UserMessage({ msg, onAddToChat }: { msg: ChatMessage; onAddToChat?: (url: string) => void }) {
  return (
    <div className="msg-user">
      <div className="bubble-user">
        {msg.parts && msg.parts.length > 0 ? (
          msg.parts.map((p, i) =>
            p.type === "image" && p.url ? (
              <ImageChip key={i} url={p.url} onAddToChat={onAddToChat} />
            ) : (
              <span key={i}>{p.text}</span>
            ),
          )
        ) : (
          msg.text
        )}
      </div>
    </div>
  );
}

export function AssistantMessage({ msg, streaming, onSendImage, onRefineImage, onRunCommand }: { msg: ChatMessage; streaming?: boolean; onSendImage: (url: string) => void; onRefineImage?: (url: string) => void; onRunCommand?: (cmd: string) => void }) {
  const [showThinking, setShowThinking] = useState(false);
  // 正文来源：有 parts 用其文本块拼接（历史恢复走 parts），否则用 msg.text
  const rawText = msg.parts && msg.parts.length > 0
    ? msg.parts.filter((p) => p.type === "text").map((p) => p.text || "").join("")
    : (msg.text || "");
  // 从正文解析 AI 给出的可执行指令标记 [[cmd:/w 文生图]]，渲染成按钮；正文里移除标记
  const cmds: string[] = [];
  const cleanText = rawText.replace(/\[\[cmd:([^\]]+)\]\]/g, (_, c) => {
    const v = String(c).trim();
    if (v) cmds.push(v);
    return "";
  }).trim();
  // 收集本条消息的所有图片：msg.image + parts 里的图片块，去重（实时出图与历史恢复统一渲染）
  const imgs: string[] = [];
  if (msg.image) imgs.push(msg.image);
  for (const p of msg.parts || []) {
    if (p.type === "image" && p.url && !imgs.includes(p.url)) imgs.push(p.url);
  }
  return (
    <div className="msg-bot">
      <div className="bot-avatar">
        <Bot size={18} />
      </div>
      <div className="bot-content">
        {msg.thinking && (
          <div className="thinking">
            <button className="thinking-head" onClick={() => setShowThinking((s) => !s)}>
              <span>思考过程</span>
              <ChevronDown
                size={16}
                style={{ transform: showThinking ? "none" : "rotate(-90deg)", transition: "transform .15s" }}
              />
            </button>
            {showThinking && <div className="thinking-body">{msg.thinking}</div>}
          </div>
        )}
        {imgs.map((url, i) => (
          <div className="img-card" key={i}>
            <img src={url} alt="生成结果" loading="lazy" onClick={() => openLightbox(url)} style={{ cursor: "zoom-in" }} />
            <div className="img-tools">
              <a className="img-tool" href={url} target="_blank" rel="noreferrer">
                <ExternalLink size={14} /> 查看原图
              </a>
              <button className="img-tool" onClick={() => onRefineImage?.(url)}><RefreshCw size={14} /> 识图微调</button>
              <button className="img-tool" onClick={() => onSendImage(url)}>
                <Send size={14} /> 发送至对话
              </button>
            </div>
          </div>
        ))}
        {cleanText && <div className="bot-text">{cleanText}</div>}
        {streaming && (
          <div className="bot-streaming" title="正在生成，请稍候…">
            <span className="bot-spinner" />
            <span className="bot-streaming-text">生成中…</span>
          </div>
        )}
        {cmds.length > 0 && onRunCommand && (
          <div className="cmd-suggest">
            {cmds.map((c, i) => (
              <button key={i} className="cmd-chip" onClick={() => onRunCommand(c)} title={`执行 ${c}`}>
                <Play size={12} style={{ verticalAlign: "-1px", marginRight: 4 }} />
                执行 {c}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// 灵感卡：联网搜到并提炼的提示词。代码块风格（深色等宽），右下角「插入对话」把提示词填进输入框。
export function InspirationCard({
  data,
  onInsert,
}: {
  data: { query: string; prompt: string; tags: string[]; sources: { title: string; url: string }[] };
  onInsert: (text: string) => void;
}) {
  return (
    <div className="msg-bot">
      <div className="bot-avatar"><Bot size={18} /></div>
      <div className="bot-content">
        <div className="insp-card">
          <div className="insp-head">
            <Sparkles size={14} />
            <span>灵感 · {data.query}</span>
          </div>
          <pre className="insp-prompt">{data.prompt}</pre>
          {data.sources.length > 0 && (
            <div className="insp-sources">
              {data.sources.map((s, i) => (
                <a key={i} href={s.url} target="_blank" rel="noreferrer" title={s.url}>
                  <ExternalLink size={11} /> {s.title || s.url}
                </a>
              ))}
            </div>
          )}
          <div className="insp-actions">
            <CopyButton text={data.prompt} className="insp-insert" />
            <button
              className="insp-insert"
              title="把这段提示词插入到输入框"
              onClick={() => onInsert(data.prompt)}
            >
              <CornerDownRight size={13} /> 插入对话
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// 输入口编排计划卡：展示 AI 规划的「各输入口放什么」，用户确认后写入画布
export function PortsPlanCard({
  plan,
  onApply,
  onIgnore,
}: {
  plan: NonNullable<ChatMessage["portsPlan"]>;
  onApply: () => void;
  onIgnore: () => void;
}) {
  const actionLabel = (op: PortOp) => {
    if (op.action === "set_image") return `放入图${op.image_index || "?"}（新建/接入图像节点）`;
    if (op.action === "replace_output") {
      return op.kind === "image"
        ? `输出口替换为图${op.image_index || "?"}（重接下游）`
        : `输出口替换为文本：${String(op.value ?? "")}`;
    }
    return `写入：${String(op.value ?? "")}`;
  };
  return (
    <div className="msg-bot">
      <div className="bot-avatar">
        <Workflow size={18} />
      </div>
      <div className="bot-content" style={{ width: "100%" }}>
        <div style={{ marginBottom: 8 }}>
          <strong>工作流输入口编排</strong>
          {plan.status === "applied" && (
            <span style={{ color: "#3a9e5b", fontSize: 12, marginLeft: 8 }}>已应用</span>
          )}
          {plan.status === "ignored" && (
            <span style={{ color: "var(--text-muted)", fontSize: 12, marginLeft: 8 }}>已忽略</span>
          )}
        </div>
        {plan.summary && (
          <p style={{ fontSize: 13, margin: "0 0 8px" }}>{plan.summary}</p>
        )}
        {plan.ops.length === 0 ? (
          <p style={{ color: "#c98a1a", fontSize: 13 }}>
            AI 未给出可自动执行的操作（可能需要手动在画布里处理，见上面说明）。
          </p>
        ) : (
          <ul style={{ margin: "0 0 10px", paddingLeft: 18, fontSize: 13 }}>
            {plan.ops.map((op, i) => (
              <li key={i} style={{ marginBottom: 4 }}>
                <code>#{op.node_id} · {op.action === "replace_output" ? op.output : op.input}</code> → {actionLabel(op)}
                {op.reason && (
                  <span style={{ color: "var(--text-muted)" }}>　{op.reason}</span>
                )}
              </li>
            ))}
          </ul>
        )}
        {plan.status === "pending" && plan.ops.length > 0 && (
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn primary" onClick={onApply}>
              应用到画布
            </button>
            <button className="btn" onClick={onIgnore}>
              忽略
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
