import { apiGet, apiPost } from "./client";

export interface ComfyStatus {
  running: boolean;
  managed: boolean;
}

export function comfyStatus(url: string) {
  return apiGet<ComfyStatus>(`/comfyui/status?url=${encodeURIComponent(url)}`);
}

export function startComfy(path: string, url: string) {
  return apiPost<{ running: boolean; managed: boolean; message: string }>("/comfyui/start", {
    path,
    url,
  });
}

// 关闭 ComfyUI（装插件/依赖前需先关）
export function stopComfy(url: string, path = "") {
  return apiPost<{ stopped: boolean; message: string }>("/comfyui/stop", { url, path });
}

// 重启 ComfyUI（装完插件生效）：先关再起，需 path 重新拉起
export function restartComfy(path: string, url: string) {
  return apiPost<{ running: boolean; managed: boolean; message: string }>("/comfyui/restart", {
    path,
    url,
  });
}

// 把 ComfyUI 路径/地址落盘到后端，供 start-dev 脚本读取
export function saveComfyConfig(path: string, url: string) {
  return apiPost<{ path: string; url: string }>("/comfyui/config", { path, url });
}

export interface SubmitResult {
  ok: boolean;
  prompt_id?: string;
  node_count?: number;
}

export function submitWorkflow(
  templateId: string,
  values: Record<string, unknown>,
  url: string,
  prompt = "",
) {
  return apiPost<SubmitResult>("/comfyui/submit", {
    template_id: templateId,
    values,
    prompt,
    url,
  });
}

const API_BASE = "http://127.0.0.1:8010/api";

export interface UploadResult {
  name: string;
  raw: Record<string, unknown>;
}

// 上传图片到 ComfyUI 的 input 目录，返回可供 LoadImage 引用的文件名
export async function uploadImage(file: File, url: string): Promise<UploadResult> {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("url", url);
  const resp = await fetch(`${API_BASE}/comfyui/upload`, { method: "POST", body: fd });
  if (!resp.ok) throw new Error(`API request failed: ${resp.status}`);
  return resp.json();
}

export interface ResultImage {
  filename: string;
  subfolder: string;
  type: string;
}

export interface GenResult {
  status: "pending" | "running" | "completed";
  images: ResultImage[];
  texts: string[];
}

export function getResult(promptId: string, url: string) {
  return apiGet<GenResult>(
    `/comfyui/result?prompt_id=${encodeURIComponent(promptId)}&url=${encodeURIComponent(url)}`,
  );
}

// 拼出经后端代理的取图地址
export function viewUrl(img: ResultImage, url: string): string {
  const qs = new URLSearchParams({
    filename: img.filename,
    type: img.type,
    subfolder: img.subfolder,
    url,
  });
  return `${API_BASE}/comfyui/view?${qs.toString()}`;
}

// 把原图留存到设置的 outputDir，返回本地文件路径
export function saveLocal(args: {
  img: ResultImage; repoId: string; outputDir: string; url: string;
}) {
  return apiPost<{ ok: boolean; path: string }>("/comfyui/save-local", {
    filename: args.img.filename,
    subfolder: args.img.subfolder,
    type: args.img.type,
    repo_id: args.repoId,
    output_dir: args.outputDir,
    url: args.url,
  });
}

// 本地留存原图的访问地址
export function localViewUrl(path: string): string {
  return `${API_BASE}/comfyui/local-view?path=${encodeURIComponent(path)}`;
}

// 通用模式留存：把任意图片地址（云端直链 / data URI）存到 outputDir
export function saveLocalSrc(args: { src: string; repoId: string; outputDir: string }) {
  return apiPost<{ ok: boolean; path: string }>("/comfyui/save-local", {
    src: args.src,
    repo_id: args.repoId,
    output_dir: args.outputDir,
  });
}

// 从锁定画布回传的完整工作流直接提交生成
export function submitGraph(workflow: unknown, url: string) {
  return apiPost<SubmitResult>("/comfyui/submit_graph", { workflow, url });
}

// 强行停止 ComfyUI 生图（人工打断工作流）：删排队项 + 中断执行。prompt_id 可空。
export function interruptComfy(url: string, promptId = "") {
  return apiPost<{ ok: boolean; deleted: boolean; interrupted: boolean }>(
    "/comfyui/interrupt",
    { url, prompt_id: promptId },
  );
}
