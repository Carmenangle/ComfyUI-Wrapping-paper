// laf_lock 子帧（锁定的 ComfyUI 画布）postMessage 协议原语，单点。
// 四处（WorkflowCard/NodePickerModal/WorkflowTemplates/workflowOrchestration）此前各自
// 重造 URL 拼接、post 信封、来源守卫。握手时序各页不同故不强合并，仅收口这三个原语。

// 锁定画布的 iframe 地址：ComfyUI 带 ?laf_lock=1 进入受控模式。
export function lockUrl(comfyUrl: string): string {
  return `${comfyUrl.replace(/\/$/, "")}/?laf_lock=1`;
}

// 完整功能画布地址：ComfyUI 带 ?laf_full=1，保留全部原生交互 + 父页面双向同步协议。
// 用于 AI 搭工作流页右侧（load 写入整图 / request_api_prompt 读回画布）。
export function fullUrl(comfyUrl: string): string {
  return `${comfyUrl.replace(/\/$/, "")}/?laf_full=1`;
}

// 向子帧发送一条 laf_lock 消息（统一 target 信封）。
export function postToFrame(win: Window | null | undefined, type: string, payload?: unknown): void {
  win?.postMessage({ target: "laf_lock", type, payload }, "*");
}

// 是否是来自 laf_lock 子帧的消息；给 type 则同时校验类型。
export function isLafMessage(data: any, type?: string): boolean {
  if (!data || data.source !== "laf_lock") return false;
  return type === undefined || data.type === type;
}
