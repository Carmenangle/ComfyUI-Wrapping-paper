import type { PortOp } from "../api/ai";

// 图文混排片段：文本/图片穿插渲染
export interface MsgPart {
  type: "text" | "image";
  text?: string;  // type=text
  url?: string;   // type=image（dataURI 或 http URL）
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  parts?: MsgPart[];   // 图文混排：有则优先按顺序渲染，文本/图片穿插
  thinking?: string;
  image?: string;
  // 工作流节点卡：选中模板后把所选节点逐个提取，各自嵌入锁定的真实 ComfyUI 画布，纵向排列
  workflow?: {
    templateId: string;
    templateName: string;
    capturedGraph: unknown | null; // 「选择完毕」时合并参数后的完整工作流
    done: boolean;
  };
  // 工作流输入口编排计划：AI 规划「各输入口放什么」，用户确认后写入画布
  portsPlan?: {
    cardId: string;            // 目标工作流卡的消息 id
    summary: string;
    ops: PortOp[];
    images: string[];          // 本轮随文图片（dataURI/URL），set_image 按 image_index 取用
    status: "pending" | "applied" | "ignored";
  };
  // 灵感卡：联网搜服装/发型/画风等 → 提炼的提示词（代码块样式，右下角可插入对话）
  inspiration?: {
    query: string;
    prompt: string;
    tags: string[];
    sources: { title: string; url: string }[];
  };
}
