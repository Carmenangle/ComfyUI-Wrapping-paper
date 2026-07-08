import { useEffect, useState } from "react";
import { Plus, Trash2, Save, AlertTriangle } from "lucide-react";
import { listAgents, saveAgents, defaultPrompt, DEFAULT_TOOLS, type Agent, type AgentTools } from "../../api/agents";
import { listMcpServers, type McpServer } from "../../api/mcp";
import { listSkills, type Skill } from "../../api/skills";

const TOOL_LABELS: { key: keyof AgentTools; label: string }[] = [
  { key: "generate_image", label: "文生图" },
  { key: "image_to_image", label: "图生图" },
  { key: "analyze_image", label: "反推提示词" },
  { key: "search_inspiration", label: "联网找灵感" },
];

// 多 Agent 预设管理：列表 + 编辑（人设/记忆/请求参数/工具开关）。
// 独立于 settings 草稿（存后端 data/agents.json），点保存整体写回。
export function AgentPanel() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [defPrompt, setDefPrompt] = useState("");
  const [mcpList, setMcpList] = useState<McpServer[]>([]);   // 可选的 MCP 服务器
  const [skillList, setSkillList] = useState<Skill[]>([]);   // 可选的技能

  useEffect(() => {
    Promise.all([listAgents(), defaultPrompt()])
      .then(([a, d]) => { setAgents(a); setDefPrompt(d.prompt); })
      .catch(() => {})
      .finally(() => setLoading(false));
    listMcpServers().then((m) => setMcpList(m.filter((x) => x.enabled))).catch(() => {});
    listSkills().then((s) => setSkillList(s.filter((x) => x.enabled))).catch(() => {});
  }, []);

  // 新建 Agent 默认带内置生图规则（开箱即能生图，与原行为一致），用户改了才不同
  const add = () =>
    setAgents((s) => [...s, {
      id: crypto.randomUUID(),
      name: "新智能体",
      systemPrompt: defPrompt,
      memory: "", temperature: null, topP: null, maxTokens: null,
      tools: { ...DEFAULT_TOOLS }, mcpServerIds: [], skillIds: [],
      isDefault: false, enabled: true,
    }]);
  const upd = (id: string, patch: Partial<Agent>) =>
    setAgents((s) => s.map((x) => (x.id === id ? { ...x, ...patch } : x)));
  const updTool = (id: string, key: keyof AgentTools, val: boolean) =>
    setAgents((s) => s.map((x) => (x.id === id ? { ...x, tools: { ...x.tools, [key]: val } } : x)));
  // 勾选/取消某 Agent 的 MCP 服务器或技能（在其 id 列表里增删）
  const toggleId = (id: string, field: "mcpServerIds" | "skillIds", val: string) =>
    setAgents((s) => s.map((x) => {
      if (x.id !== id) return x;
      const list = x[field] || [];
      return { ...x, [field]: list.includes(val) ? list.filter((v) => v !== val) : [...list, val] };
    }));
  const del = (id: string) => setAgents((s) => s.filter((x) => x.id !== id));

  const save = async () => {
    setSaving(true);
    try {
      const r = await saveAgents(agents);
      setAgents(r);
      setSaved(true);
      setTimeout(() => setSaved(false), 1800);
    } finally {
      setSaving(false);
    }
  };

  // APPEND_AGENT_RENDER
  if (loading) return <div className="settings-section"><p className="field-hint">加载中…</p></div>;

  return (
    <div className="settings-section">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h4 style={{ margin: 0 }}>智能体（Agent）</h4>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn" onClick={add}><Plus size={15} style={{ verticalAlign: "-2px", marginRight: 4 }} />新建</button>
          <button className="btn primary" onClick={save} disabled={saving}>
            <Save size={14} style={{ verticalAlign: "-2px", marginRight: 4 }} />{saving ? "保存中…" : "保存"}
          </button>
        </div>
      </div>
      <p className="field-hint" style={{ marginTop: 8 }}>
        创建多个智能体预设，对话时在左下角切换。新建的智能体默认带内置生图规则（开箱即能生图），你可自由修改提示词打造不同用途的智能体。改动需点「保存」。
        {saved && <span className="settings-saved" style={{ marginLeft: 8 }}>已保存</span>}
      </p>
      <div style={{ marginTop: 12 }}>
        {agents.length === 0 && <p className="field-hint">还没有自定义智能体（当前对话用内置默认行为）。点「新建」创建一个（默认带生图规则，可改）。</p>}
        {agents.map((a) => (
          <div className="image-model-card" key={a.id}>
            <div className="row-head">
              <label style={{ display: "flex", alignItems: "center", gap: 6, flex: 1 }}>
                <input type="checkbox" checked={a.enabled} onChange={(e) => upd(a.id, { enabled: e.target.checked })} />
                <input value={a.name} onChange={(e) => upd(a.id, { name: e.target.value })} placeholder="智能体名称" style={{ fontWeight: 600, flex: 1 }} />
              </label>
              <button className="icon-btn" style={{ background: "#d23b3b" }} onClick={() => del(a.id)}><Trash2 size={14} /></button>
            </div>
            <div className="field">
              <label>系统提示词（人设/行为）</label>
              <textarea
                value={a.systemPrompt}
                onChange={(e) => upd(a.id, { systemPrompt: e.target.value })}
                placeholder="定义这个智能体的角色、语气、行为规则…"
                rows={6}
                style={{ width: "100%", resize: "vertical" }}
              />
              <p className="field-hint" style={{ marginTop: 4 }}>
                <AlertTriangle size={12} style={{ verticalAlign: "-2px", marginRight: 3 }} />
                提示词含生图工具调用规则，大幅改动可能影响生图。想做纯问答等用途可自由重写。
              </p>
            </div>
            <div className="field">
              <label>长期记忆（可选）</label>
              <textarea value={a.memory} onChange={(e) => upd(a.id, { memory: e.target.value })} placeholder="关于用户的偏好/背景，会一直提供给这个智能体" rows={2} style={{ width: "100%", resize: "vertical" }} />
            </div>
            <div className="field">
              <label>本地工具</label>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
                {TOOL_LABELS.map((t) => (
                  <label key={t.key} style={{ display: "flex", alignItems: "center", gap: 4, fontWeight: 400 }}>
                    <input type="checkbox" checked={a.tools[t.key]} onChange={(e) => updTool(a.id, t.key, e.target.checked)} />
                    {t.label}
                  </label>
                ))}
              </div>
            </div>
            <div className="field">
              <label>MCP 服务器（勾选此智能体可调用的）</label>
              {mcpList.length === 0 ? (
                <p className="field-hint">还没有 MCP 服务器。去「扩展 → MCP 服务器」添加。</p>
              ) : (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
                  {mcpList.map((m) => (
                    <label key={m.id} style={{ display: "flex", alignItems: "center", gap: 4, fontWeight: 400 }}>
                      <input type="checkbox" checked={(a.mcpServerIds || []).includes(m.id)} onChange={() => toggleId(a.id, "mcpServerIds", m.id)} />
                      {m.name}
                    </label>
                  ))}
                </div>
              )}
            </div>
            <div className="field">
              <label>技能扩展（勾选此智能体启用的）</label>
              {skillList.length === 0 ? (
                <p className="field-hint">还没有技能。去「扩展 → 技能扩展」添加。</p>
              ) : (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
                  {skillList.map((s) => (
                    <label key={s.id} style={{ display: "flex", alignItems: "center", gap: 4, fontWeight: 400 }}>
                      <input type="checkbox" checked={(a.skillIds || []).includes(s.id)} onChange={() => toggleId(a.id, "skillIds", s.id)} />
                      {s.name}
                    </label>
                  ))}
                </div>
              )}
            </div>
            <div className="field">
              <label>请求参数（可选，留空用默认）</label>
              <div style={{ display: "flex", gap: 10 }}>
                <input type="number" step="0.1" min="0" max="2" value={a.temperature ?? ""} onChange={(e) => upd(a.id, { temperature: e.target.value === "" ? null : Number(e.target.value) })} placeholder="温度 (0~2)" />
                <input type="number" step="1" min="1" value={a.maxTokens ?? ""} onChange={(e) => upd(a.id, { maxTokens: e.target.value === "" ? null : Number(e.target.value) })} placeholder="最大 tokens" />
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
