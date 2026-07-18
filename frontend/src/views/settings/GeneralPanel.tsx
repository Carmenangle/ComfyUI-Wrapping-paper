import { useRef, useState } from "react";
import { ImagePlus, Monitor } from "lucide-react";
import type { Settings, Theme } from "../../stores/settings";
import { localViewUrl } from "../../api/comfyui";
import { uploadChatBg } from "../../api/userState";

// 各面板共享：接收 draft 与 setDraft，直接改草稿态（保存由 SettingsView 顶层统一处理）
export interface PanelProps {
  draft: Settings;
  setDraft: React.Dispatch<React.SetStateAction<Settings>>;
}

const THEMES: { value: Exclude<Theme, "system">; label: string; description: string; colors: string[] }[] = [
  { value: "bright", label: "明亮", description: "日光瓷白与矢车菊蓝", colors: ["#f8f7fa", "#647dcb"] },
  { value: "night", label: "夜间", description: "深灰与柔白", colors: ["#1a1a1a", "#e5e5e5"] },
  { value: "eye-care", label: "护眼", description: "暖米黄与橄榄金", colors: ["#f4efe0", "#a98a3c"] },
  { value: "green", label: "绿色", description: "浅绿与深绿", colors: ["#e9f5e9", "#395932"] },
  { value: "gray", label: "灰色", description: "冷浅灰与蓝灰", colors: ["#f3f4f6", "#394050"] },
  { value: "high-contrast", label: "高对比", description: "纯黑与纯白", colors: ["#000000", "#ffffff"] },
];

export function GeneralPanel({ draft, setDraft }: PanelProps) {
  const bg = draft.chatBgPath || "";
  const opacity = draft.chatBgOpacity ?? 0.15;
  const fit = draft.chatBgFit ?? "cover";
  const scale = draft.chatBgScale ?? 1;
  const posX = draft.chatBgPosX ?? 50;
  const posY = draft.chatBgPosY ?? 50;
  const set = (patch: Partial<Settings>) => setDraft((d) => ({ ...d, ...patch }));
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);

  const onPickFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    e.target.value = "";  // 允许重复选同一文件
    if (!f) return;
    setUploading(true);
    try {
      const r = await uploadChatBg(f);
      if (r.ok) set({ chatBgPath: r.path });
    } catch { /* 忽略，用户可手填路径 */ }
    finally { setUploading(false); }
  };

  // 预览与实际渲染共用的背景样式（所见即所得）
  const bgStyle: React.CSSProperties = {
    backgroundImage: bg ? `url(${localViewUrl(bg)})` : undefined,
    backgroundSize: fit === "cover" ? `${scale * 100}%` : "contain",
    backgroundPosition: `${posX}% ${posY}%`,
    backgroundRepeat: "no-repeat",
    opacity,
  };

  return (
    <>
      <div className="settings-section">
        <h4>主题</h4>
        <div className="theme-picker">
          {THEMES.map((t) => (
            <button
              key={t.value}
              className={draft.theme === t.value ? "theme-choice active" : "theme-choice"}
              onClick={() => setDraft((d) => ({ ...d, theme: t.value }))}
              aria-pressed={draft.theme === t.value}
            >
              <span className="theme-swatches" aria-hidden="true">
                {t.colors.map((color) => <span key={color} style={{ background: color }} />)}
              </span>
              <span className="theme-choice-copy">
                <strong>{t.label}</strong>
                <small>{t.description}</small>
              </span>
            </button>
          ))}
        </div>
        <button
          className={draft.theme === "system" ? "theme-system active" : "theme-system"}
          onClick={() => setDraft((d) => ({ ...d, theme: "system" }))}
          aria-pressed={draft.theme === "system"}
        >
          <Monitor size={16} />
          <span><strong>跟随系统</strong><small>系统亮色使用明亮，暗色使用夜间</small></span>
        </button>
      </div>

      <div className="settings-section">
        <h4>对话背景</h4>
        <p className="field-hint" style={{ margin: "0 0 12px" }}>
          给小仓库对话窗设置背景图（填本地图片完整路径）。可调填充方式、缩放、位置、透明度，实时预览。
        </p>
        <div className="field">
          <label>背景图路径</label>
          <div className="background-path-row">
            <input
              value={bg}
              onChange={(e) => set({ chatBgPath: e.target.value })}
              placeholder="D:\\images\\bg.png（填路径或点右侧导入）"
              style={{ flex: 1 }}
            />
            <button className="btn" onClick={() => fileRef.current?.click()} disabled={uploading} style={{ whiteSpace: "nowrap" }}>
              <ImagePlus size={15} style={{ verticalAlign: "-2px", marginRight: 4 }} />{uploading ? "导入中…" : "导入照片"}
            </button>
            <input ref={fileRef} type="file" accept="image/*" style={{ display: "none" }} onChange={onPickFile} />
          </div>
        </div>
        {bg && (
          <>
            <div className="field">
              <label>填充方式</label>
              <div className="theme-options">
                <button className={fit === "cover" ? "active" : ""} onClick={() => set({ chatBgFit: "cover" })}>铺满裁剪</button>
                <button className={fit === "contain" ? "active" : ""} onClick={() => set({ chatBgFit: "contain" })}>完整显示</button>
              </div>
            </div>
            {fit === "cover" && (
              <div className="field">
                <label>缩放：{Math.round(scale * 100)}%</label>
                <input type="range" min={0.5} max={2} step={0.05} value={scale} onChange={(e) => set({ chatBgScale: Number(e.target.value) })} />
              </div>
            )}
            <div className="field">
              <label>水平位置：{posX}%</label>
              <input type="range" min={0} max={100} step={1} value={posX} onChange={(e) => set({ chatBgPosX: Number(e.target.value) })} />
            </div>
            <div className="field">
              <label>垂直位置：{posY}%</label>
              <input type="range" min={0} max={100} step={1} value={posY} onChange={(e) => set({ chatBgPosY: Number(e.target.value) })} />
            </div>
            <div className="field">
              <label>透明度：{Math.round(opacity * 100)}%</label>
              <input type="range" min={0} max={1} step={0.05} value={opacity} onChange={(e) => set({ chatBgOpacity: Number(e.target.value) })} />
            </div>
            <div className="field">
              <label>预览</label>
              <div style={{ position: "relative", height: 200, borderRadius: 10, overflow: "hidden", border: "1px solid var(--border)", background: "var(--bg)" }}>
                <div style={{ position: "absolute", inset: 0, ...bgStyle }} />
                <div style={{ position: "relative", padding: 12, fontSize: 13, color: "var(--text-muted)" }}>对话文字示意…</div>
              </div>
            </div>
            <button className="btn" onClick={() => set({ chatBgPath: "" })}>清除背景</button>
          </>
        )}
      </div>
    </>
  );
}
