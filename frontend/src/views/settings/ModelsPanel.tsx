import { useState } from "react";
import { Plus, Trash2, ListChecks, Search, X } from "lucide-react";
import type { PanelProps } from "./GeneralPanel";
import {
  modelDisplayName,
  type ChatModel, type ImageModel, type VideoModel, type EmbedModel,
} from "../../stores/settings";
import { discoverProviderModels } from "../../api/aiProviders";
import { filterModelNames } from "../../lib/modelSearch";

// 嵌入模型快捷预设
const EMBED_PRESETS = [
  { name: "Ollama 本地", baseUrl: "http://localhost:11434/v1", modelName: "qwen3-embedding:latest", apiKey: "ollama" },
  { name: "智谱 云端", baseUrl: "https://open.bigmodel.cn/api/paas/v4", modelName: "embedding-3", apiKey: "" },
];

// 一张「模型卡」：名称/Key/URL + 「读取模型列表」按钮（调 discover-models 拉列表供选）
function ModelCard({ model, onChange, onRemove, customSizeSupported, onCustomSizeSupport }: {
  model: { id?: string; displayName?: string; apiKey: string; baseUrl: string; modelName: string };
  onChange: (patch: Partial<ChatModel>) => void;
  onRemove: () => void;
  customSizeSupported?: boolean;
  onCustomSizeSupport?: (enabled: boolean) => void;
}) {
  const [models, setModels] = useState<string[]>([]);
  const [modelQuery, setModelQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const discover = async () => {
    if (!model.baseUrl) { setErr("请先填 API URL"); return; }
    setLoading(true); setErr("");
    try {
      const r = await discoverProviderModels(model.baseUrl, model.apiKey);
      if (r.ok) {
        setModels(r.models);
        setModelQuery("");
      }
      else setErr(r.error || "读取失败");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setLoading(false);
    }
  };
  const filteredModels = filterModelNames(models, modelQuery);

  return (
    <div className="image-model-card">
      <div className="row-head">
        <strong>{modelDisplayName(model)}</strong>
        <button className="icon-btn" style={{ background: "#d23b3b" }} onClick={onRemove}>
          <Trash2 size={14} />
        </button>
      </div>
      <div className="field">
        <label>显示名称</label>
        <input
          value={model.displayName || ""}
          onChange={(e) => onChange({ displayName: e.target.value })}
          placeholder={model.modelName ? `例如：${model.modelName} · 4K令牌` : "例如：GPT Image 2 · 4K令牌"}
        />
        <p className="field-hint">仅用于界面区分，不会作为模型参数发送。</p>
      </div>
      <div className="field">
        <label>API URL</label>
        <input value={model.baseUrl} onChange={(e) => onChange({ baseUrl: e.target.value })} placeholder="https://api.openai.com/v1" />
      </div>
      <div className="field">
        <label>API Key</label>
        <input type="password" value={model.apiKey} onChange={(e) => onChange({ apiKey: e.target.value })} />
      </div>
      <div className="field">
        <label>API 模型名称</label>
        <div style={{ display: "flex", gap: 6 }}>
          <input value={model.modelName} onChange={(e) => onChange({ modelName: e.target.value })} placeholder="gpt-4o" style={{ flex: 1 }} />
          <button className="btn" onClick={discover} disabled={loading} title="从该供应商读取可用模型列表">
            <ListChecks size={14} style={{ verticalAlign: "-2px", marginRight: 4 }} />
            {loading ? "读取中…" : "读取列表"}
          </button>
        </div>
        {err && <p className="field-hint" style={{ color: "#d23b3b" }}>{err}</p>}
        {models.length > 0 && (
          <div className="model-list-picker">
            <div className="model-list-tools">
              <div className="model-list-search">
                <Search size={14} aria-hidden="true" />
                <input
                  value={modelQuery}
                  onChange={(e) => setModelQuery(e.target.value)}
                  placeholder="搜索模型名称…"
                  aria-label="搜索模型名称"
                />
                {modelQuery && (
                  <button type="button" onClick={() => setModelQuery("")} title="清空搜索" aria-label="清空模型搜索">
                    <X size={14} />
                  </button>
                )}
              </div>
              <span>{filteredModels.length}/{models.length}</span>
            </div>
            <select
              value=""
              onChange={(e) => { if (e.target.value) onChange({ modelName: e.target.value }); }}
            >
              <option value="">
                {filteredModels.length > 0 ? "— 选择模型 —" : "— 没有匹配的模型 —"}
              </option>
              {filteredModels.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
        )}
      </div>
      {onCustomSizeSupport && (
        <label className="model-capability-toggle">
          <input
            type="checkbox"
            checked={customSizeSupported === true}
            onChange={(event) => onCustomSizeSupport(event.target.checked)}
          />
          <span>上游支持任意图片尺寸</span>
        </label>
      )}
    </div>
  );
}

export function ModelsPanel({ draft, setDraft }: PanelProps) {
  const setEmbed = (patch: Partial<EmbedModel>) =>
    setDraft((d) => ({ ...d, embedModel: { ...d.embedModel, ...patch } }));

  const addChatModel = () =>
    setDraft((d) => ({ ...d, chatModels: [...d.chatModels, { id: crypto.randomUUID(), apiKey: "", baseUrl: "", modelName: "新模型" }] }));
  const updateChatModel = (id: string, patch: Partial<ChatModel>) =>
    setDraft((d) => ({ ...d, chatModels: d.chatModels.map((m) => (m.id === id ? { ...m, ...patch } : m)) }));
  const removeChatModel = (id: string) =>
    setDraft((d) => ({ ...d, chatModels: d.chatModels.filter((m) => m.id !== id), activeChatModelId: d.activeChatModelId === id ? undefined : d.activeChatModelId }));

  const addImageModel = () =>
    setDraft((d) => ({ ...d, imageModels: [...d.imageModels, { id: crypto.randomUUID(), apiKey: "", baseUrl: "", modelName: "新模型" }] }));
  const updateImageModel = (id: string, patch: Partial<ImageModel>) =>
    setDraft((d) => ({ ...d, imageModels: d.imageModels.map((m) => (m.id === id ? { ...m, ...patch } : m)) }));
  const removeImageModel = (id: string) =>
    setDraft((d) => ({ ...d, imageModels: d.imageModels.filter((m) => m.id !== id), activeImageModelId: d.activeImageModelId === id ? undefined : d.activeImageModelId }));

  const addVideoModel = () =>
    setDraft((d) => ({ ...d, videoModels: [...(d.videoModels || []), { id: crypto.randomUUID(), apiKey: "", baseUrl: "", modelName: "新模型" }] }));
  const updateVideoModel = (id: string, patch: Partial<VideoModel>) =>
    setDraft((d) => ({ ...d, videoModels: (d.videoModels || []).map((m) => (m.id === id ? { ...m, ...patch } : m)) }));
  const removeVideoModel = (id: string) =>
    setDraft((d) => ({ ...d, videoModels: (d.videoModels || []).filter((m) => m.id !== id), activeVideoModelId: d.activeVideoModelId === id ? undefined : d.activeVideoModelId }));

  const embedProvider = (() => {
    const u = (draft.embedModel.baseUrl || "").toLowerCase();
    if (u.includes("11434") || u.includes("ollama")) return "本地 Ollama";
    if (u.includes("bigmodel.cn")) return "云端智谱";
    if (u.includes("openai.com")) return "云端 OpenAI";
    if (!u.trim()) return "未配置";
    return "自定义 / 中转";
  })();

  return (
    <>
      {/* 对话模型 */}
      <div className="settings-section">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h4 style={{ margin: 0 }}>对话模型</h4>
          <button className="btn" onClick={addChatModel}><Plus size={15} style={{ verticalAlign: "-2px", marginRight: 4 }} />添加</button>
        </div>
        <p className="field-hint" style={{ marginTop: 8 }}>智能体的大脑（也用于反推图片）。可配多个供应商，在对话框左下角图标处切换。</p>
        <div style={{ marginTop: 12 }}>
          {draft.chatModels.length === 0 && <p className="field-hint">还没有对话模型，点击「添加」。</p>}
          {draft.chatModels.map((m) => (
            <ModelCard key={m.id} model={m} onChange={(p) => updateChatModel(m.id!, p)} onRemove={() => removeChatModel(m.id!)} />
          ))}
        </div>
      </div>

      {/* 生图模型 */}
      <div className="settings-section">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h4 style={{ margin: 0 }}>生图模型</h4>
          <button className="btn" onClick={addImageModel}><Plus size={15} style={{ verticalAlign: "-2px", marginRight: 4 }} />添加</button>
        </div>
        <div style={{ marginTop: 12 }}>
          {draft.imageModels.length === 0 && <p className="field-hint">还没有生图模型，点击「添加」。</p>}
          {draft.imageModels.map((m) => (
            <ModelCard
              key={m.id}
              model={m}
              customSizeSupported={m.supportsCustomSize}
              onCustomSizeSupport={(enabled) => updateImageModel(m.id, { supportsCustomSize: enabled })}
              onChange={(p) => updateImageModel(m.id, p as Partial<ImageModel>)}
              onRemove={() => removeImageModel(m.id)}
            />
          ))}
        </div>
      </div>

      {/* 视频模型 */}
      <div className="settings-section">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h4 style={{ margin: 0 }}>视频模型</h4>
          <button className="btn" onClick={addVideoModel}><Plus size={15} style={{ verticalAlign: "-2px", marginRight: 4 }} />添加</button>
        </div>
        <p className="field-hint" style={{ marginTop: 8 }}>文生视频（OpenAI 兼容 video/generations，多为异步任务）。可配多个供应商，对话里说"生成视频"即调用。</p>
        <div style={{ marginTop: 12 }}>
          {(draft.videoModels || []).length === 0 && <p className="field-hint">还没有视频模型，点击「添加」。</p>}
          {(draft.videoModels || []).map((m) => (
            <ModelCard key={m.id} model={m} onChange={(p) => updateVideoModel(m.id, p as Partial<VideoModel>)} onRemove={() => removeVideoModel(m.id)} />
          ))}
        </div>
      </div>

      {/* 嵌入模型 */}
      <div className="settings-section">
        <h4>嵌入模型（知识库 RAG）</h4>
        <p className="field-hint" style={{ margin: "0 0 10px" }}>用于把仓库资料/生成历史向量化检索。需支持 embeddings 接口，如智谱 embedding-3、OpenAI text-embedding-3、Ollama 本地向量模型。</p>
        <div style={{ display: "flex", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
          {EMBED_PRESETS.map((p) => (
            <button key={p.name} className="btn" onClick={() => setEmbed({ baseUrl: p.baseUrl, modelName: p.modelName, apiKey: p.apiKey })}>{p.name}</button>
          ))}
        </div>
        <p style={{ fontSize: 12, margin: "0 0 10px" }}>当前使用：<strong>{embedProvider}</strong></p>
        <div className="field"><label>API URL</label><input value={draft.embedModel.baseUrl} onChange={(e) => setEmbed({ baseUrl: e.target.value })} placeholder="http://localhost:11434/v1" /></div>
        <div className="field"><label>API Key</label><input type="password" value={draft.embedModel.apiKey} onChange={(e) => setEmbed({ apiKey: e.target.value })} /></div>
        <div className="field"><label>模型名称</label><input value={draft.embedModel.modelName} onChange={(e) => setEmbed({ modelName: e.target.value })} placeholder="qwen3-embedding:latest" /></div>
      </div>
    </>
  );
}
