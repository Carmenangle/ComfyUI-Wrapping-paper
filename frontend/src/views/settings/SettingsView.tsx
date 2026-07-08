import { useState } from "react";
import { Palette, FolderCog, BrainCircuit, Sparkles, Blocks, Puzzle, KeyRound, Bot } from "lucide-react";
import type { Settings } from "../../stores/settings";
import { saveComfyConfig } from "../../api/comfyui";
import { GeneralPanel } from "./GeneralPanel";
import { PathsPanel } from "./PathsPanel";
import { ModelsPanel } from "./ModelsPanel";
import { StylePanel } from "./StylePanel";
import { McpPanel } from "./McpPanel";
import { SkillsPanel } from "./SkillsPanel";
import { TokensPanel } from "./TokensPanel";
import { AgentPanel } from "./AgentPanel";

interface Props {
  settings: Settings;
  update: (patch: Partial<Settings>) => void;
}

// 左侧导航项：分组 + 图标。id 对应右侧渲染的面板。
type NavId = "general" | "agent" | "paths" | "models" | "style" | "mcp" | "skills" | "tokens";
const NAV: { group: string; items: { id: NavId; label: string; icon: typeof Palette }[] }[] = [
  { group: "常规", items: [
    { id: "general", label: "外观", icon: Palette },
    { id: "agent", label: "智能体", icon: Bot },
    { id: "paths", label: "路径与代理", icon: FolderCog },
  ] },
  { group: "模型与服务", items: [
    { id: "models", label: "模型", icon: BrainCircuit },
    { id: "style", label: "生图风格", icon: Sparkles },
  ] },
  { group: "扩展", items: [
    { id: "mcp", label: "MCP 服务器", icon: Blocks },
    { id: "skills", label: "技能扩展", icon: Puzzle },
  ] },
  { group: "凭证", items: [
    { id: "tokens", label: "下载令牌", icon: KeyRound },
  ] },
];

export function SettingsView({ settings, update }: Props) {
  // 草稿：编辑都改这里，保存才写回，取消则丢弃（与原 Modal 一致）
  const [draft, setDraft] = useState<Settings>(settings);
  const [active, setActive] = useState<NavId>("general");
  const [saved, setSaved] = useState(false);

  const onSave = () => {
    update(draft);
    // 同步 ComfyUI 路径/地址到后端，供 start-dev 脚本读取
    saveComfyConfig(draft.comfyuiPath, draft.comfyuiUrl).catch(() => {});
    setSaved(true);
    setTimeout(() => setSaved(false), 1800);
  };

  const dirty = JSON.stringify(draft) !== JSON.stringify(settings);

  return (
    <div className="settings-page">
      <aside className="settings-nav">
        {NAV.map((g) => (
          <div className="settings-nav-group" key={g.group}>
            <div className="settings-nav-title">{g.group}</div>
            {g.items.map((it) => (
              <button
                key={it.id}
                className={active === it.id ? "settings-nav-item active" : "settings-nav-item"}
                onClick={() => setActive(it.id)}
              >
                <it.icon size={16} /> {it.label}
              </button>
            ))}
          </div>
        ))}
      </aside>

      <div className="settings-content">
        <div className="settings-content-body">
          {active === "general" && <GeneralPanel draft={draft} setDraft={setDraft} />}
          {active === "agent" && <AgentPanel />}
          {active === "paths" && <PathsPanel draft={draft} setDraft={setDraft} />}
          {active === "models" && <ModelsPanel draft={draft} setDraft={setDraft} />}
          {active === "style" && <StylePanel draft={draft} setDraft={setDraft} />}
          {active === "mcp" && <McpPanel />}
          {active === "skills" && <SkillsPanel />}
          {active === "tokens" && <TokensPanel draft={draft} setDraft={setDraft} />}
        </div>
        <div className="settings-footer">
          {dirty && <span className="settings-dirty">有未保存的更改</span>}
          {saved && <span className="settings-saved">已保存</span>}
          <button className="btn" disabled={!dirty} onClick={onSave}>保存</button>
        </div>
      </div>
    </div>
  );
}
