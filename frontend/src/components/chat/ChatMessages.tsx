import { memo, useState } from "react";
import { Bot, Brush, Check, ChevronDown, CornerDownRight, Download, ExternalLink, Image as ImageIcon, Images, MessageCircle, Pencil, Play, Plus, RotateCw, ScanText, Search, Send, Sparkles, Video, Workflow, Wrench, X } from "lucide-react";
import type { AgentRoute, ChatMessage, PromptApproval, RouteChoice } from "../../types/chat";
import type { AssistantAvatarState } from "../../lib/assistantAvatar";
import type { PortOp } from "../../api/ai";
import type { RichContent } from "../RichInput";
import { CopyButton } from "../CopyButton";
import { openLightbox } from "../Lightbox";

// 下载图片/视频：拉成 blob 触发浏览器保存对话框，文件名取地址里的真实名。
// 失败（跨域/CORS）则退化为新标签打开，让用户手动另存。
async function downloadMedia(url: string) {
  const name = mediaFilename(url);
  try {
    const resp = await fetch(url);
    const blob = await resp.blob();
    const href = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = href;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    // 下载已由浏览器接管；下一帧释放 objectURL，避免长定时器，也不抢在 click 之前释放。
    requestAnimationFrame(() => URL.revokeObjectURL(href));
  } catch {
    window.open(url, "_blank", "noreferrer");
  }
}

// 从取图地址推断文件名：优先 filename/path 查询参数，其次路径末段，兜底带时间戳
function mediaFilename(url: string): string {
  try {
    const u = new URL(url, window.location.origin);
    const q = u.searchParams.get("filename") || u.searchParams.get("path");
    if (q) return q.split(/[/\\]/).pop() || q;
    const last = u.pathname.split("/").pop();
    if (last && /\.\w+$/.test(last)) return last;
  } catch { /* ignore */ }
  return `download_${Date.now()}`;
}

// 动图判定：GIF/WebP 用 <img> 渲染（原生循环、可放大），其余（mp4/webm/mov…）用 <video>。
// ComfyUI 的动图/视频产物都进 msg.video，这里按扩展名/类型分流。
function isAnimatedImage(url: string): boolean {
  const clean = url.split("?")[0].split("#")[0].toLowerCase();
  if (/\.(gif|webp)$/.test(clean)) return true;
  // 本地/代理取图地址把真实文件名放在 filename/path 查询参数里
  return /[?&](filename|path)=[^&]*\.(gif|webp)/i.test(url);
}

// 内联图片 chip：缩略小图，悬停弹出大图预览浮窗
export function ImageChip({ url, onAddToChat }: { url: string; onAddToChat?: (url: string) => void }) {
  const open = () => openLightbox(url);
  return (
    <span className="img-chip">
      <img src={url} alt="用户附图" className="img-chip-thumb" role="button" tabIndex={0}
        onClick={open}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } }} />
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
// memo：长列表里流式/进度刷新时，未变的历史消息跳过重渲染（回调需稳定，见 ChatView 的 useCallback）
export function userMessagePlainText(msg: ChatMessage): string {
  if (!msg.parts?.length) return msg.text || "";
  return msg.parts
    .filter((part) => part.type === "text")
    .map((part) => part.text || "")
    .join("");
}

export function userMessageRichContent(msg: ChatMessage): RichContent {
  const text = userMessagePlainText(msg);
  const images = (msg.parts || [])
    .filter((part) => part.type === "image" && part.url)
    .map((part) => part.url!);
  if (msg.image && !images.includes(msg.image)) images.push(msg.image);
  const maskedPart = (msg.parts || []).find(
    (part) => part.type === "masked-image" && part.image && part.mask && part.url,
  );
  const maskedImage = maskedPart ? {
    image: maskedPart.image!,
    mask: maskedPart.mask!,
    preview: maskedPart.url!,
  } : undefined;
  return {
    text,
    images,
    parts: [
      ...images.map((url) => ({ type: "image" as const, url })),
      ...(maskedImage ? [{
        type: "masked-image" as const,
        url: maskedImage.preview,
        image: maskedImage.image,
        mask: maskedImage.mask,
      }] : []),
      ...(text ? [{ type: "text" as const, text }] : []),
    ],
    ...(maskedImage ? { maskedImage } : {}),
  };
}

function UserMessageBase({
  msg,
  onAddToChat,
  onEdit,
}: {
  msg: ChatMessage;
  onAddToChat?: (url: string) => void;
  onEdit?: (content: RichContent) => void;
}) {
  const plainText = userMessagePlainText(msg);
  return (
    <div className="msg-user">
      <div className="bubble-user">
        <div className="user-message-text">
          {msg.parts && msg.parts.length > 0 ? (
            msg.parts.map((p, i) =>
              (p.type === "image" || p.type === "masked-image") && p.url ? (
                <ImageChip
                  key={`img-${p.url}`}
                  url={p.url}
                  onAddToChat={p.type === "image" ? onAddToChat : undefined}
                />
              ) : (
                <span key={`text-${i}-${(p.text || "").slice(0, 20)}`}>{p.text}</span>
              ),
            )
          ) : (
            msg.text
          )}
        </div>
        <div className="user-message-actions">
          <CopyButton text={plainText} className="user-copy-btn" label="复制纯文本" />
          {onEdit && (
            <button
              type="button"
              className="user-edit-btn"
              title="复制图文内容到输入框编辑"
              aria-label="编辑此消息"
              onClick={() => onEdit(userMessageRichContent(msg))}
            >
              <Pencil size={13} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export function PromptApprovalCard({
  approval,
  onAction,
}: {
  approval: PromptApproval;
  onAction?: (approval: PromptApproval, action: "submit" | "change" | "cancel", editedPrompt?: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [editedPrompt, setEditedPrompt] = useState(approval.prompt);
  const [busy, setBusy] = useState(false);
  const pending = approval.status === "pending";
  const actionable = pending || approval.status === "failed";
  const deliveryUnknown = approval.stage === "delivery_unknown";
  const requestFailed = approval.stage === "request_failed";
  const statusLabel = approval.status === "submitted" ? "已提交"
    : approval.status === "cancelled" ? "已取消"
      : deliveryUnknown ? "上游交付状态未知"
        : requestFailed ? "请求未发送到上游"
        : approval.status === "failed" ? "生成失败，等待后续处理" : "等待确认";
  const act = async (action: "submit" | "change" | "cancel", prompt?: string) => {
    if (!onAction || busy) return;
    setBusy(true);
    try {
      await onAction(approval, action, prompt);
      if (action === "change") setEditing(false);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="prompt-approval-card">
      <div className="prompt-approval-head">
        <span>{approval.kind === "video" ? "待审核视频提示词" : "待审核生图提示词"}</span>
        <span className={`prompt-approval-status ${approval.status}`}>{statusLabel}</span>
      </div>
      {editing ? (
        <textarea
          className="prompt-approval-editor"
          value={editedPrompt}
          onChange={(event) => setEditedPrompt(event.target.value)}
          autoFocus
        />
      ) : (
        <pre className="prompt-approval-code">{approval.prompt}</pre>
      )}
      {actionable && onAction && (
        <div className="prompt-approval-actions">
          {editing ? (
            <>
              <button className="btn primary" disabled={busy || !editedPrompt.trim()} onClick={() => act("change", editedPrompt)}>
                <Check size={14} /> 保存更改
              </button>
              <button className="btn" disabled={busy} onClick={() => { setEditedPrompt(approval.prompt); setEditing(false); }}>
                <X size={14} /> 返回
              </button>
            </>
          ) : (
            <>
              <button className="btn primary" disabled={busy} onClick={() => act("submit")}>
                <Check size={14} /> {deliveryUnknown || requestFailed ? "确认重新提交" : "确认提交"}
              </button>
              <button className="btn" disabled={busy} onClick={() => { setEditedPrompt(approval.prompt); setEditing(true); }}>
                <Pencil size={14} /> 更改
              </button>
              <button className="btn danger" disabled={busy} onClick={() => act("cancel")}>
                <X size={14} /> 取消
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

const routeChoiceIcon = (route: AgentRoute) => {
  if (route === "answer") return <MessageCircle size={15} />;
  if (route === "generate" || route === "img2img") return <Images size={15} />;
  if (route === "analyze") return <ScanText size={15} />;
  if (route === "video") return <Video size={15} />;
  if (route === "inspire") return <Search size={15} />;
  return <Wrench size={15} />;
};

export function RouteChoiceCard({
  choice,
  onSelect,
}: {
  choice: RouteChoice;
  onSelect?: (choice: RouteChoice, route: AgentRoute) => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const select = async (route: AgentRoute) => {
    if (!onSelect || busy || choice.status !== "pending") return;
    setBusy(true);
    try {
      await onSelect(choice, route);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="route-choice-card">
      <div className="route-choice-head">
        <span>选择本次功能</span>
        {choice.status === "selected" && <span>已选择</span>}
      </div>
      <div className="route-choice-actions">
        {choice.options.map((option) => (
          <button
            key={option.route}
            className={`btn ${choice.selectedRoute === option.route ? "primary is-selected" : ""}`}
            disabled={!onSelect || busy || choice.status === "selected"}
            title={option.label}
            onClick={() => select(option.route)}
          >
            {routeChoiceIcon(option.route)} {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function AssistantMessageBase({ msg, streaming, avatarState = "default", onSendImage, onMaskImage, onRunCommand, onSetCover, onPromptApproval, onRouteChoice, onRegenerate, regenerating = false }: { msg: ChatMessage; streaming?: boolean; avatarState?: AssistantAvatarState; onSendImage: (url: string) => void; onMaskImage?: (url: string) => void; onRunCommand?: (cmd: string) => void; onSetCover?: (url: string) => void; onPromptApproval?: (approval: PromptApproval, action: "submit" | "change" | "cancel", editedPrompt?: string) => Promise<void>; onRouteChoice?: (choice: RouteChoice, route: AgentRoute) => Promise<void>; onRegenerate?: (messageId: string) => void; regenerating?: boolean }) {
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
      <div className={`bot-avatar bot-avatar-${avatarState}`}>
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
          <div className="img-card" key={url}>
            <img src={url} alt={`生成结果 ${i + 1}`} loading="lazy" onClick={() => openLightbox(url)} style={{ cursor: "zoom-in" }} />
            <div className="img-tools">
              <a className="img-tool" href={url} target="_blank" rel="noreferrer">
                <ExternalLink size={14} /> 查看原图
              </a>
              <button className="img-tool" onClick={() => downloadMedia(url)}><Download size={14} /> 下载</button>
              <button
                className="img-tool"
                disabled={!msg.regeneration || !onRegenerate || regenerating}
                title={msg.regeneration ? "使用这张结果绑定的原始参数重新生成" : "旧结果未保存完整生成参数"}
                onClick={() => onRegenerate?.(msg.id)}
              >
                <RotateCw size={14} /> {regenerating ? "重新生成中…" : "重新生图"}
              </button>
              <button className="img-tool" onClick={() => onMaskImage?.(url)}><Brush size={14} /> 蒙化修改</button>
              <button className="img-tool" onClick={() => onSendImage(url)}>
                <Send size={14} /> 发送至对话
              </button>
              {onSetCover && (
                <button className="img-tool" onClick={() => onSetCover(url)}><ImageIcon size={14} /> 设为封面</button>
              )}
            </div>
          </div>
        ))}
        {msg.video && (
          <div className="img-card">
            {isAnimatedImage(msg.video) ? (
              // GIF/WebP 动图：用 <img> 渲染（原生循环播放、可放大），而非 <video>
              <img src={msg.video} alt="生成动图结果" loading="lazy"
                onClick={() => openLightbox(msg.video!)} style={{ maxWidth: "100%", borderRadius: 8, cursor: "zoom-in" }} />
            ) : (
              <video src={msg.video} controls loop playsInline style={{ maxWidth: "100%", borderRadius: 8 }} />
            )}
            <div className="img-tools">
              <a className="img-tool" href={msg.video} target="_blank" rel="noreferrer">
                <ExternalLink size={14} /> 查看原文件
              </a>
              <button className="img-tool" onClick={() => downloadMedia(msg.video!)}><Download size={14} /> 下载</button>
              <button className="img-tool" onClick={() => onSendImage(msg.video!)}>
                <Send size={14} /> 发送至对话
              </button>
            </div>
          </div>
        )}
        {cleanText && <div className="bot-text">{cleanText}</div>}
        {msg.promptApproval && (
          <PromptApprovalCard approval={msg.promptApproval} onAction={onPromptApproval} />
        )}
        {msg.routeChoice && (
          <RouteChoiceCard choice={msg.routeChoice} onSelect={onRouteChoice} />
        )}
        {streaming && (
          <div className="bot-streaming" title="正在生成，请稍候…">
            <span className="bot-spinner" />
            <span className="bot-streaming-text">生成中…</span>
          </div>
        )}
        {cmds.length > 0 && onRunCommand && (
          <div className="cmd-suggest">
            {cmds.map((c) => (
              <button key={c} className="cmd-chip" onClick={() => onRunCommand(c)} title={`执行 ${c}`}>
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

// memo 导出：props 未变（同一 msg 引用、稳定回调）则跳过重渲染。
export const UserMessage = memo(UserMessageBase);
export const AssistantMessage = memo(AssistantMessageBase);

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
              {data.sources.map((s) => (
                <a key={s.url} href={s.url} target="_blank" rel="noreferrer" title={s.url}>
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
  onEditOp,
}: {
  plan: NonNullable<ChatMessage["portsPlan"]>;
  onApply: () => void;
  onIgnore: () => void;
  onEditOp?: (opIndex: number, value: string) => void;
}) {
  // 文本类 op（set_widget、文本 replace_output）的 value 可在执行前内联编辑
  const isEditableText = (op: PortOp) =>
    op.action === "set_widget" || (op.action === "replace_output" && op.kind !== "image");
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
            {plan.ops.map((op, i) => {
              const editable = plan.status === "pending" && onEditOp && isEditableText(op);
              return (
                <li key={`${op.node_id}-${op.action}-${op.input || op.output || i}`} style={{ marginBottom: 4 }}>
                  <code>#{op.node_id} · {op.action === "replace_output" ? op.output : op.input}</code>
                  {editable ? (
                    <>
                      {" → 写入（可编辑）："}
                      <textarea
                        className="ports-op-edit"
                        value={String(op.value ?? "")}
                        onChange={(e) => onEditOp!(i, e.target.value)}
                        rows={(() => {
                          // 长提示词多为无换行长句：按显式换行数 + 字符折行估算（约 48 字/行），
                          // 数字/短值仍是 1~2 行，长文本自动撑高，最多 12 行避免过长。
                          const s = String(op.value ?? "");
                          const byNewline = s.split("\n").length;
                          const byLength = Math.ceil(s.length / 48);
                          return Math.min(12, Math.max(1, byNewline, byLength));
                        })()}
                        style={{ width: "100%", marginTop: 4, fontSize: 12, fontFamily: "inherit",
                          padding: "6px 8px", borderRadius: 6, border: "1px solid var(--border)",
                          background: "var(--bg)", color: "var(--text)", resize: "vertical",
                          lineHeight: 1.5, boxSizing: "border-box" }}
                      />
                    </>
                  ) : (
                    <> → {actionLabel(op)}</>
                  )}
                  {op.reason && (
                    <span style={{ color: "var(--text-muted)" }}>　{op.reason}</span>
                  )}
                </li>
              );
            })}
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
