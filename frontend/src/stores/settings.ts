import { useEffect, useState } from "react";
import { getUserState } from "../api/userState";
import { pushSettings } from "../lib/userStateSync";

export type Theme = "light" | "dark" | "system";

export interface ChatModel {
  id?: string;        // 多模型列表里的唯一 id（单模型旧数据可无）
  apiKey: string;
  baseUrl: string;
  modelName: string;
}

// 嵌入模型（知识库 RAG 用）：OpenAI 兼容形式，可填智谱/OpenAI/Ollama 等
export interface EmbedModel {
  apiKey: string;
  baseUrl: string;
  modelName: string;
}

export interface ImageModel {
  id: string;
  apiKey: string;
  baseUrl: string;
  modelName: string;
}

// 用户自定义的提示词风格存档：content 是整段风格模板（画风/结构/负面词，自由粘贴），
// AI 参照其组织形态来写提示词。切换器选中时 imageStyle = "preset:<id>"。
export interface StylePreset {
  id: string;
  name: string;
  content: string;
}

export interface Settings {
  theme: Theme;
  chatModels: ChatModel[];          // 对话模型（可多个供应商）
  activeChatModelId?: string;       // 当前选中的对话模型 id
  embedModel: EmbedModel;  // 知识库 RAG 嵌入模型
  imageModels: ImageModel[];
  activeImageModelId?: string;
  imageStyle?: string;  // 生图提示词风格：""(自动)/sd/gpt/banana，或 "preset:<id>" 指向自定义存档
  stylePresets?: StylePreset[];  // 用户自定义风格存档
  workflowDir: string; // 工作流默认读取路径（后端扫描该目录及子目录的 .json）
  outputDir: string; // 输出图片默认存放路径
  comfyuiPath: string; // ComfyUI 本体目录（含 main.py），用于后端启动
  comfyuiUrl: string; // ComfyUI 访问地址，iframe 嵌入与 API 调用
  modelsDir: string; // ComfyUI models 目录（模型下载落盘，留空则用 comfyuiPath/models）
  hfToken: string; // HuggingFace token（下载鉴权模型用）
  civitaiToken: string; // Civitai API key（下载鉴权模型用）
  proxyUrl: string; // 联网搜索代理地址（灵感搜索走此代理访问外网）
  proxyEnabled: boolean; // 是否启用代理（关则直连外网）
}

const KEY = "laf_settings";

const DEFAULT: Settings = {
  theme: "system",
  chatModels: [],
  embedModel: { apiKey: "ollama", baseUrl: "http://localhost:11434/v1", modelName: "qwen3-embedding:latest" },
  imageModels: [],
  imageStyle: "",
  stylePresets: [],
  workflowDir: "",
  outputDir: "",
  comfyuiPath: "",
  comfyuiUrl: "http://127.0.0.1:8188",
  modelsDir: "",
  hfToken: "",
  civitaiToken: "",
  proxyUrl: "http://127.0.0.1:7897",
  proxyEnabled: true,
};

// 旧数据迁移：单 chatModel 字段 → chatModels 列表（向后兼容）
function migrate(s: Record<string, unknown>): Settings {
  const merged = { ...DEFAULT, ...s } as Settings & { chatModel?: ChatModel };
  if ((!merged.chatModels || merged.chatModels.length === 0) && merged.chatModel) {
    const old = merged.chatModel;
    if (old.baseUrl || old.modelName || old.apiKey) {
      const id = crypto.randomUUID();
      merged.chatModels = [{ ...old, id }];
      merged.activeChatModelId = id;
    }
  }
  // 给缺 id 的对话模型补 id
  merged.chatModels = (merged.chatModels || []).map((m) =>
    m.id ? m : { ...m, id: crypto.randomUUID() },
  );
  delete merged.chatModel;
  return merged;
}

function load(): Settings {
  try {
    return migrate(JSON.parse(localStorage.getItem(KEY) || "{}"));
  } catch {
    return DEFAULT;
  }
}

// 取当前选中的对话模型（无选中则取第一个，再无则空配置）
export function activeChatModel(s: Settings): ChatModel {
  return (
    s.chatModels.find((m) => m.id === s.activeChatModelId) ||
    s.chatModels[0] ||
    { apiKey: "", baseUrl: "", modelName: "" }
  );
}

export function applyTheme(theme: Theme) {  const dark =
    theme === "dark" ||
    (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
}

export function useSettings() {
  const [settings, setSettings] = useState<Settings>(load);
  const [hydrated, setHydrated] = useState(false); // 后端为准：回填完成前不回写后端

  // 启动时拉后端存档，有则以后端为准覆盖本地（跨浏览器/换机恢复）
  useEffect(() => {
    let alive = true;
    getUserState()
      .then((s) => {
        if (alive && s.settings) {
          const migrated = migrate(s.settings as unknown as Record<string, unknown>);
          setSettings(migrated);
          localStorage.setItem(KEY, JSON.stringify(migrated));
        }
      })
      .catch(() => { /* 后端离线：沿用 localStorage */ })
      .finally(() => { if (alive) setHydrated(true); });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    localStorage.setItem(KEY, JSON.stringify(settings));
    applyTheme(settings.theme);
    if (hydrated) pushSettings(settings); // 回填完成后，本地变更（及升级时的本地存量）镜像到后端
  }, [settings, hydrated]);

  // 跟随系统时，监听系统主题变化
  useEffect(() => {
    if (settings.theme !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = () => applyTheme("system");
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [settings.theme]);

  const update = (patch: Partial<Settings>) => setSettings((p) => ({ ...p, ...patch }));

  const addImageModel = () =>
    setSettings((p) => ({
      ...p,
      imageModels: [
        ...p.imageModels,
        { id: crypto.randomUUID(), apiKey: "", baseUrl: "", modelName: "新模型" },
      ],
    }));

  const updateImageModel = (id: string, patch: Partial<ImageModel>) =>
    setSettings((p) => ({
      ...p,
      imageModels: p.imageModels.map((m) => (m.id === id ? { ...m, ...patch } : m)),
    }));

  const removeImageModel = (id: string) =>
    setSettings((p) => ({
      ...p,
      imageModels: p.imageModels.filter((m) => m.id !== id),
      activeImageModelId: p.activeImageModelId === id ? undefined : p.activeImageModelId,
    }));

  const addStylePreset = (name: string, content: string): string => {
    const id = crypto.randomUUID();
    setSettings((p) => ({ ...p, stylePresets: [...(p.stylePresets || []), { id, name, content }] }));
    return id;
  };

  const updateStylePreset = (id: string, patch: Partial<StylePreset>) =>
    setSettings((p) => ({
      ...p,
      stylePresets: (p.stylePresets || []).map((s) => (s.id === id ? { ...s, ...patch } : s)),
    }));

  const removeStylePreset = (id: string) =>
    setSettings((p) => ({
      ...p,
      stylePresets: (p.stylePresets || []).filter((s) => s.id !== id),
      imageStyle: p.imageStyle === `preset:${id}` ? "" : p.imageStyle,  // 删掉正选中的存档 → 回退自动
    }));

  return {
    settings, update, addImageModel, updateImageModel, removeImageModel,
    addStylePreset, updateStylePreset, removeStylePreset,
  };
}

// 从 imageStyle 取选中存档的 content（内置风格返回空串）。供生图链路透传给后端。
export function activeStyleTemplate(s: Settings): string {
  const v = s.imageStyle || "";
  if (!v.startsWith("preset:")) return "";
  const id = v.slice("preset:".length);
  return (s.stylePresets || []).find((p) => p.id === id)?.content || "";
}
