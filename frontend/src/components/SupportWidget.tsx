import { useEffect, useRef, useState } from "react";
import { Headset, Send, X } from "lucide-react";
import { supportStream } from "../api/ai";

type Model = { baseUrl: string; apiKey: string; modelName: string };

interface Msg {
  role: "user" | "bot";
  text: string;
}

const FAB_TOP_KEY = "laf_support_fab_top";
const FAB_HIDDEN_KEY = "laf_support_hidden";

export function SupportWidget({ chat, embed, repoId }: { chat: Model; embed: Model; repoId: string }) {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  // FAB 纵向位置（px，距顶），以及是否被长按隐藏
  const [fabTop, setFabTop] = useState<number>(() => {
    const v = Number(localStorage.getItem(FAB_TOP_KEY));
    return Number.isFinite(v) && v > 0 ? v : window.innerHeight - 80;
  });
  const [hidden, setHidden] = useState<boolean>(() => localStorage.getItem(FAB_HIDDEN_KEY) === "1");
  const dragRef = useRef<{ moved: boolean; startY: number; startTop: number } | null>(null);
  const longPressRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([
    { role: "bot", text: "你好，我是工具助手。直接说需求就能生图/改图；也可以问我 /w /s /a /find 等指令、工作流怎么用、知识库和资产库怎么配，我会查知识库回答。" },
  ]);
  const abortRef = useRef<(() => void) | null>(null);

  useEffect(() => { localStorage.setItem(FAB_TOP_KEY, String(fabTop)); }, [fabTop]);
  useEffect(() => { localStorage.setItem(FAB_HIDDEN_KEY, hidden ? "1" : "0"); }, [hidden]);

  const send = () => {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setBusy(true);
    // 先放用户消息 + 空 bot 消息，流式往 bot 追加
    setMsgs((prev) => [...prev, { role: "user", text }, { role: "bot", text: "" }]);
    const append = (delta: string) =>
      setMsgs((prev) => {
        const next = [...prev];
        next[next.length - 1] = { role: "bot", text: next[next.length - 1].text + delta };
        return next;
      });
    abortRef.current = supportStream(text, repoId, chat, embed, append, (err) => {
      setBusy(false);
      if (err) {
        setMsgs((prev) => {
          const next = [...prev];
          const last = next[next.length - 1];
          if (last && last.role === "bot" && !last.text) next[next.length - 1] = { role: "bot", text: `回答失败：${err}` };
          return next;
        });
      }
    });
  };

  // FAB 拖动 + 长按隐藏
  const onFabPointerDown = (e: React.PointerEvent) => {
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    dragRef.current = { moved: false, startY: e.clientY, startTop: fabTop };
    // 长按 600ms 隐藏
    longPressRef.current = setTimeout(() => {
      if (dragRef.current && !dragRef.current.moved) {
        setHidden(true);
        dragRef.current = null;
      }
    }, 600);
  };
  const onFabPointerMove = (e: React.PointerEvent) => {
    const d = dragRef.current;
    if (!d) return;
    const dy = e.clientY - d.startY;
    if (Math.abs(dy) > 4) {
      d.moved = true;
      if (longPressRef.current) { clearTimeout(longPressRef.current); longPressRef.current = null; }
    }
    const top = Math.min(window.innerHeight - 64, Math.max(8, d.startTop + dy));
    setFabTop(top);
  };
  const onFabPointerUp = () => {
    if (longPressRef.current) { clearTimeout(longPressRef.current); longPressRef.current = null; }
    const d = dragRef.current;
    dragRef.current = null;
    if (d && !d.moved) setOpen(true);  // 未拖动 = 点击 → 打开
  };

  // 被长按隐藏：右侧只留一个 <<< 拉手，点击唤回
  if (hidden) {
    return (
      <button className="support-handle" title="显示 AI 客服" onClick={() => setHidden(false)}>
        &lt;&lt;&lt;
      </button>
    );
  }

  if (!open) {
    return (
      <button
        className="support-fab"
        title="AI 客服（拖动可移动，长按隐藏）"
        style={{ top: fabTop, bottom: "auto" }}
        onPointerDown={onFabPointerDown}
        onPointerMove={onFabPointerMove}
        onPointerUp={onFabPointerUp}
      >
        <Headset className="support-fab-headset" size={24} />
        <span className="support-fab-emblem" aria-hidden="true" />
      </button>
    );
  }

  return (
    <div className="support-panel">
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span>AI 客服</span>
        <button className="icon-btn" style={{ background: "transparent", color: "#333" }} onClick={() => setOpen(false)}>
          <X size={18} />
        </button>
      </header>
      <div className="support-body">
        {msgs.map((m, i) => (
          <div key={i} className={`support-msg ${m.role}`}>
            {m.text || (busy && i === msgs.length - 1 ? "思考中…" : "")}
          </div>
        ))}
      </div>
      <div className="support-input">
        <input
          value={input}
          placeholder="输入问题…"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
        />
        <button className="btn primary" onClick={send} disabled={busy}>
          <Send size={16} />
        </button>
      </div>
    </div>
  );
}
