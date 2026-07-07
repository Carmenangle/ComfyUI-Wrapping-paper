import { useState } from "react";
import { Ratio } from "lucide-react";
import { calcSize, ASPECTS, RES_TIERS } from "../../lib/viewRouting";

// 对话框模型切换器：一个图标按钮，hover 显示当前模型名，点击弹小菜单切换。
// items 为 {id,name} 列表；空列表时禁用并提示去设置配置。
export function ModelSwitcher({
  icon,
  label,
  items,
  activeId,
  emptyHint,
  onPick,
}: {
  icon: React.ReactNode;
  label: string;
  items: { id: string; name: string }[];
  activeId: string;
  emptyHint: string;
  onPick: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const current = items.find((i) => i.id === activeId) || items[0];
  const title = current ? `${label}：${current.name}` : emptyHint;
  return (
    <div className="model-switch" style={{ position: "relative" }}>
      <button
        type="button"
        className="icon-btn model-switch-btn"
        title={title}
        onClick={() => items.length && setOpen((v) => !v)}
        disabled={items.length === 0}
      >
        {icon}
      </button>
      {open && items.length > 0 && (
        <>
          <div className="model-switch-mask" onClick={() => setOpen(false)} />
          <div className="model-switch-menu">
            <div className="model-switch-head">{label}</div>
            {items.map((i) => (
              <button
                key={i.id}
                type="button"
                className={`model-switch-item ${i.id === (current?.id || "") ? "active" : ""}`}
                onClick={() => { onPick(i.id); setOpen(false); }}
              >
                {i.name}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

// 生图尺寸选择器：比例 + 分辨率档，样式对齐 ModelSwitcher。
export function SizeSwitcher({
  aspect, resTier, onPick,
}: {
  aspect: string;
  resTier: string;
  onPick: (aspect: string, resTier: string) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="model-switch" style={{ position: "relative" }}>
      <button
        type="button"
        className="icon-btn model-switch-btn"
        title={`生图尺寸：${aspect} · ${resTier}（${calcSize(aspect, resTier)}）`}
        onClick={() => setOpen((v) => !v)}
      >
        <Ratio size={18} />
      </button>
      {open && (
        <>
          <div className="model-switch-mask" onClick={() => setOpen(false)} />
          <div className="model-switch-menu">
            <div className="model-switch-head">画面比例</div>
            {ASPECTS.map((a) => (
              <button
                key={a}
                type="button"
                className={`model-switch-item ${a === aspect ? "active" : ""}`}
                onClick={() => onPick(a, resTier)}
              >
                {a}
              </button>
            ))}
            <div className="model-switch-head" style={{ marginTop: 6 }}>分辨率</div>
            {Object.keys(RES_TIERS).map((t) => (
              <button
                key={t}
                type="button"
                className={`model-switch-item ${t === resTier ? "active" : ""}`}
                onClick={() => onPick(aspect, t)}
              >
                {t}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

// 首页空态落地：二次元网格风。超大描边标题压顶 + 网点铺底 + 提示。
export function ChatEmptyLanding() {
  return (
    <div className="chat-landing dot-grid">
      <div className="hero-title chat-landing-hero">STUDIO</div>
      <p className="chat-landing-hint">
        描述你想要的画面，或直接和 AI 对话。输入 <code>/w</code> 选择工作流模板。
      </p>
    </div>
  );
}
