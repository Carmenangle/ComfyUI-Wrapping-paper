import { useState } from "react";
import { Plus, Trash2, X } from "lucide-react";
import type { Settings, Theme, ChatModel, EmbedModel, ImageModel } from "../stores/settings";
import { saveComfyConfig } from "../api/comfyui";

interface Props {
  settings: Settings;
  update: (patch: Partial<Settings>) => void;
  onClose: () => void;
}

const THEMES: { value: Theme; label: string }[] = [
  { value: "light", label: "白天" },
  { value: "dark", label: "夜间" },
  { value: "system", label: "跟随系统" },
];

export function SettingsModal({ settings, update, onClose }: Props) {
  // 草稿：编辑都改这里，保存才写回，取消则丢弃
  const [draft, setDraft] = useState<Settings>(settings);

  const setEmbed = (patch: Partial<EmbedModel>) =>
    setDraft((d) => ({ ...d, embedModel: { ...d.embedModel, ...patch } }));

  const addChatModel = () =>
    setDraft((d) => ({
      ...d,
      chatModels: [
        ...d.chatModels,
        { id: crypto.randomUUID(), apiKey: "", baseUrl: "", modelName: "新模型" },
      ],
    }));

  const updateChatModel = (id: string, patch: Partial<ChatModel>) =>
    setDraft((d) => ({
      ...d,
      chatModels: d.chatModels.map((m) => (m.id === id ? { ...m, ...patch } : m)),
    }));

  const removeChatModel = (id: string) =>
    setDraft((d) => ({
      ...d,
      chatModels: d.chatModels.filter((m) => m.id !== id),
      activeChatModelId: d.activeChatModelId === id ? undefined : d.activeChatModelId,
    }));

  // 嵌入模型快捷预设：一键填好 baseUrl/模型名（key 留空由用户填）
  const EMBED_PRESETS = [
    { name: "Ollama 本地", baseUrl: "http://localhost:11434/v1", modelName: "qwen3-embedding:latest", apiKey: "ollama" },
    { name: "智谱 云端", baseUrl: "https://open.bigmodel.cn/api/paas/v4", modelName: "embedding-3", apiKey: "" },
  ];

  // 按 baseUrl 自动判断当前在用哪家（只读提示，不改逻辑）
  const embedProvider = (() => {
    const u = (draft.embedModel.baseUrl || "").toLowerCase();
    if (u.includes("11434") || u.includes("ollama")) return "本地 Ollama";
    if (u.includes("bigmodel.cn")) return "云端智谱";
    if (u.includes("openai.com")) return "云端 OpenAI";
    if (!u.trim()) return "未配置";
    return "自定义 / 中转";
  })();

  const addImageModel = () =>
    setDraft((d) => ({
      ...d,
      imageModels: [
        ...d.imageModels,
        { id: crypto.randomUUID(), apiKey: "", baseUrl: "", modelName: "新模型" },
      ],
    }));

  const updateImageModel = (id: string, patch: Partial<ImageModel>) =>
    setDraft((d) => ({
      ...d,
      imageModels: d.imageModels.map((m) => (m.id === id ? { ...m, ...patch } : m)),
    }));

  const removeImageModel = (id: string) =>
    setDraft((d) => ({
      ...d,
      imageModels: d.imageModels.filter((m) => m.id !== id),
      activeImageModelId: d.activeImageModelId === id ? undefined : d.activeImageModelId,
    }));

  const onSave = () => {
    update(draft);
    // 同步 ComfyUI 路径/地址到后端，供 start-dev 脚本读取（开源后无需改脚本）
    saveComfyConfig(draft.comfyuiPath, draft.comfyuiUrl).catch(() => {});
    onClose();
  };

  return (
    <div className="modal-mask">
      <div className="modal settings-modal" onClick={(e) => e.stopPropagation()}>
        <div className="settings-head">
          <h3 style={{ margin: 0 }}>设置</h3>
          <button className="icon-btn" style={{ background: "transparent", color: "var(--text)" }} onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        <div className="settings-body">
          {/* 主题 */}
          <div className="settings-section">
            <h4>主题</h4>
            <div className="theme-options">
              {THEMES.map((t) => (
                <button
                  key={t.value}
                  className={draft.theme === t.value ? "active" : ""}
                  onClick={() => setDraft((d) => ({ ...d, theme: t.value }))}
                >
                  {t.label}
                </button>
              ))}
            </div>
          </div>

          {/* 路径 */}
          <div className="settings-section">
            <h4>路径</h4>
            <div className="field">
              <label>工作流默认读取路径</label>
              <input
                value={draft.workflowDir}
                onChange={(e) => setDraft((d) => ({ ...d, workflowDir: e.target.value }))}
                placeholder="D:\\ComfyUI\\workflows"
              />
            </div>
            <div className="field">
              <label>输出图片默认存放路径</label>
              <input
                value={draft.outputDir}
                onChange={(e) => setDraft((d) => ({ ...d, outputDir: e.target.value }))}
                placeholder="D:\\ComfyUI\\output"
              />
            </div>
            <div className="field">
              <label>ComfyUI 目录（含 main.py）</label>
              <input
                value={draft.comfyuiPath}
                onChange={(e) => setDraft((d) => ({ ...d, comfyuiPath: e.target.value }))}
                placeholder="D:\\tool\\ComfyUI\\ComfyUI_aaaki\\ComfyUI"
              />
            </div>
            <div className="field">
              <label>ComfyUI 访问地址</label>
              <input
                value={draft.comfyuiUrl}
                onChange={(e) => setDraft((d) => ({ ...d, comfyuiUrl: e.target.value }))}
                placeholder="http://127.0.0.1:8188"
              />
            </div>
            <div className="field">
              <label>
                <input
                  type="checkbox"
                  checked={draft.proxyEnabled}
                  onChange={(e) => setDraft((d) => ({ ...d, proxyEnabled: e.target.checked }))}
                  style={{ marginRight: 6, verticalAlign: "-1px" }}
                />
                启用联网搜索代理
              </label>
              <input
                value={draft.proxyUrl}
                disabled={!draft.proxyEnabled}
                onChange={(e) => setDraft((d) => ({ ...d, proxyUrl: e.target.value }))}
                placeholder="http://127.0.0.1:7897"
                style={draft.proxyEnabled ? undefined : { opacity: 0.5 }}
              />
              <p style={{ color: "var(--text-muted)", fontSize: 12, margin: "4px 0 0" }}>
                联网找灵感（/find、AI 搜索）走此代理访问外网。关闭则直连（国内多半连不上）。
              </p>
            </div>
            <div className="field">
              <label>模型目录（models）</label>
              <input
                value={draft.modelsDir}
                onChange={(e) => setDraft((d) => ({ ...d, modelsDir: e.target.value }))}
                placeholder="D:\\tool\\ComfyUI\\...\\ComfyUI\\models"
              />
              <p style={{ color: "var(--text-muted)", fontSize: 12, margin: "4px 0 0" }}>
                下载的模型按类型存进此目录的子文件夹（checkpoints/loras/vae 等），ComfyUI 原生识别。
              </p>
            </div>
          </div>

          {/* 对话模型（可多个供应商，对话框可切换） */}
          <div className="settings-section">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <h4 style={{ margin: 0 }}>对话模型</h4>
              <button className="btn" onClick={addChatModel}>
                <Plus size={15} style={{ verticalAlign: "-2px", marginRight: 4 }} />
                添加
              </button>
            </div>
            <p style={{ color: "var(--text-muted)", fontSize: 12, margin: "8px 0 0" }}>
              智能体的大脑（也用于反推图片）。可配多个供应商，在对话框左下角图标处切换。
            </p>
            <div style={{ marginTop: 12 }}>
              {draft.chatModels.length === 0 && (
                <p style={{ color: "var(--text-muted)", fontSize: 13 }}>还没有对话模型，点击「添加」。</p>
              )}
              {draft.chatModels.map((m) => (
                <div className="image-model-card" key={m.id}>
                  <div className="row-head">
                    <strong>{m.modelName || "未命名模型"}</strong>
                    <button className="icon-btn" style={{ background: "#d23b3b" }} onClick={() => removeChatModel(m.id!)}>
                      <Trash2 size={14} />
                    </button>
                  </div>
                  <div className="field">
                    <label>模型名称</label>
                    <input value={m.modelName} onChange={(e) => updateChatModel(m.id!, { modelName: e.target.value })} placeholder="gpt-4o" />
                  </div>
                  <div className="field">
                    <label>API Key</label>
                    <input type="password" value={m.apiKey} onChange={(e) => updateChatModel(m.id!, { apiKey: e.target.value })} />
                  </div>
                  <div className="field">
                    <label>API URL</label>
                    <input value={m.baseUrl} onChange={(e) => updateChatModel(m.id!, { baseUrl: e.target.value })} placeholder="https://api.openai.com/v1" />
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* 嵌入模型（知识库 RAG 用） */}
          <div className="settings-section">
            <h4>嵌入模型（知识库 RAG）</h4>
            <p style={{ color: "var(--text-muted)", fontSize: 12, margin: "0 0 10px" }}>
              用于把仓库资料/生成历史向量化检索。需支持 embeddings 接口，如智谱 embedding-3、OpenAI text-embedding-3、Ollama 本地向量模型。
            </p>
            {/* 快捷预设：一键填好对应路径与模型名 */}
            <div style={{ display: "flex", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
              {EMBED_PRESETS.map((p) => (
                <button
                  key={p.name}
                  className="btn"
                  onClick={() => setEmbed({ baseUrl: p.baseUrl, modelName: p.modelName, apiKey: p.apiKey })}
                >
                  {p.name}
                </button>
              ))}
            </div>
            {/* 当前提供方：按 baseUrl 自动判断，只读 */}
            <p style={{ fontSize: 12, margin: "0 0 10px" }}>
              当前使用：<strong>{embedProvider}</strong>
            </p>
            <div className="field">
              <label>API Key</label>
              <input type="password" value={draft.embedModel.apiKey} onChange={(e) => setEmbed({ apiKey: e.target.value })} />
            </div>
            <div className="field">
              <label>API URL</label>
              <input value={draft.embedModel.baseUrl} onChange={(e) => setEmbed({ baseUrl: e.target.value })} placeholder="http://localhost:11434/v1" />
            </div>
            <div className="field">
              <label>模型名称</label>
              <input value={draft.embedModel.modelName} onChange={(e) => setEmbed({ modelName: e.target.value })} placeholder="qwen3-embedding:latest" />
            </div>
          </div>

          {/* 生图模型（可多个） */}
          <div className="settings-section">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <h4 style={{ margin: 0 }}>生图模型</h4>
              <button className="btn" onClick={addImageModel}>
                <Plus size={15} style={{ verticalAlign: "-2px", marginRight: 4 }} />
                添加
              </button>
            </div>
            <div style={{ marginTop: 12 }}>
              {draft.imageModels.length === 0 && (
                <p style={{ color: "var(--text-muted)", fontSize: 13 }}>还没有生图模型，点击「添加」。</p>
              )}
              {draft.imageModels.map((m) => (
                <div className="image-model-card" key={m.id}>
                  <div className="row-head">
                    <strong>{m.modelName || "未命名模型"}</strong>
                    <button className="icon-btn" style={{ background: "#d23b3b" }} onClick={() => removeImageModel(m.id)}>
                      <Trash2 size={14} />
                    </button>
                  </div>
                  <div className="field">
                    <label>模型名称</label>
                    <input value={m.modelName} onChange={(e) => updateImageModel(m.id, { modelName: e.target.value })} />
                  </div>
                  <div className="field">
                    <label>API Key</label>
                    <input type="password" value={m.apiKey} onChange={(e) => updateImageModel(m.id, { apiKey: e.target.value })} />
                  </div>
                  <div className="field">
                    <label>API URL</label>
                    <input value={m.baseUrl} onChange={(e) => updateImageModel(m.id, { baseUrl: e.target.value })} />
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* 模型下载鉴权 token（下载页用） */}
          <div className="settings-section">
            <h4>模型下载鉴权</h4>
            <p style={{ color: "var(--text-muted)", fontSize: 12, margin: "0 0 10px" }}>
              下载需登录的模型时填写；公开模型可留空。下载功能在左侧「模型下载」页。
            </p>
            <div className="field">
              <label>HuggingFace Token</label>
              <input type="password" value={draft.hfToken} onChange={(e) => setDraft((d) => ({ ...d, hfToken: e.target.value }))} placeholder="hf_..." />
            </div>
            <div className="field">
              <label>Civitai API Key</label>
              <input type="password" value={draft.civitaiToken} onChange={(e) => setDraft((d) => ({ ...d, civitaiToken: e.target.value }))} />
            </div>
          </div>
        </div>

        <div className="settings-foot">
          <button className="btn" onClick={onClose}>取消</button>
          <button className="btn primary" onClick={onSave}>保存</button>
        </div>
      </div>
    </div>
  );
}
