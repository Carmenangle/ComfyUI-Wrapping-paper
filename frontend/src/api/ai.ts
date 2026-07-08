import { apiGet, apiPost } from "./client";
import { openSSE } from "./sse";

// 嵌入模型配置（设置 → 嵌入模型），单一属主。
type Embed = { baseUrl: string; apiKey: string; modelName: string };
// 对话模型三元组配置。
type Chat = { baseUrl: string; apiKey: string; modelName: string };

// wire 格式序列化器（收口三元组，各调用方不再逐字段手拆）：
// - chatBody：对话端点用 base_url/api_key/model
// - ragEmbed：RAG POST 端点用 base_url/api_key/embed_model
// - sseEmbed：SSE 端点用 embed_base_url/embed_api_key/embed_model（默认模型 embedding-3）
function chatBody(chat: Chat) {
  return {
    base_url: chat.baseUrl,
    api_key: chat.apiKey,
    model: chat.modelName,
  };
}
function ragEmbed(embed?: Embed) {
  return {
    base_url: embed?.baseUrl || "",
    api_key: embed?.apiKey || "",
    embed_model: embed?.modelName || "",
  };
}
function sseEmbed(embed?: Embed) {
  return {
    embed_base_url: embed?.baseUrl || "",
    embed_api_key: embed?.apiKey || "",
    embed_model: embed?.modelName || "embedding-3",
  };
}


export interface GenPromptResult {
  prompt: string;
}

// 根据场景描述生成出图提示词（用设置里的对话模型）
export function genPrompt(
  scene: string,
  chat: { baseUrl: string; apiKey: string; modelName: string },
) {
  return apiPost<GenPromptResult>("/ai/prompt", {
    scene,
    ...chatBody(chat),
  });
}

// 反推：看图生成提示词（/r）。需视觉模型，复用对话模型配置。
export function describeImage(
  images: string[],
  chat: { baseUrl: string; apiKey: string; modelName: string },
  hint = "",
) {
  return apiPost<GenPromptResult>("/ai/describe-image", {
    images,
    hint,
    ...chatBody(chat),
  });
}

// 翻译（可选润色），用于模型介绍的多语言翻译
export function translateText(
  text: string,
  targetLang: string,
  chat: { baseUrl: string; apiKey: string; modelName: string },
  polish = false,
) {
  return apiPost<{ text: string }>("/ai/translate", {
    text,
    target_lang: targetLang,
    polish,
    ...chatBody(chat),
  });
}

export interface DescribeResult {
  description: string;
}

// 根据工作流节点结构 AI 生成一句能力描述（模板描述弹窗）
export function describeWorkflow(
  name: string,
  nodes: { id: string; type: string; title: string }[],
  chat: { baseUrl: string; apiKey: string; modelName: string },
) {
  return apiPost<DescribeResult>("/ai/describe-workflow", {
    name,
    nodes,
    ...chatBody(chat),
  });
}

// 基于已输入的能力描述文本润色，使其更便于 AI 理解
export function polishDescription(
  text: string,
  chat: { baseUrl: string; apiKey: string; modelName: string },
) {
  return apiPost<DescribeResult>("/ai/polish-description", {
    text,
    ...chatBody(chat),
  });
}

// 工作流输入口编排：AI 根据需求 + 选中节点的输入口结构，规划如何填充各输入口。
// 返回操作计划（不执行，前端确认后再 apply）。
export interface PortOp {
  node_id: string;
  input: string;
  output?: string;             // replace_output：输出口名
  action: "set_widget" | "set_image" | "replace_output";
  value?: string | number | boolean;
  image_index?: number;        // set_image / 图像 replace_output：用第几张用户图（从 1 开始）
  kind?: "image" | "text";     // replace_output：替换源类型
  reason?: string;
}
export interface PortsPlan {
  summary: string;
  ops: PortOp[];
  is_orchestration?: boolean;   // false=AI 判定这句不是编排意图，前端应转普通对话
}

export function workflowPorts(
  scene: string,
  imageCount: number,
  nodeSchema: unknown[],
  modelName: string,
  chat: { baseUrl: string; apiKey: string; modelName: string },
  force = false,
  style = "",
  styleTemplate = "",
) {
  return apiPost<PortsPlan>("/ai/workflow-ports", {
    scene,
    image_count: imageCount,
    node_schema: nodeSchema,
    model_name: modelName,
    ...chatBody(chat),
    force,
    style,
    style_template: styleTemplate,
  });
}

export interface ChatTurn {
  role: "user" | "assistant" | "system";
  content: string;
  images?: string[];   // 该条消息附带的图片（dataURI 或 URL）
}

// 灵感卡：联网搜服装/发型/画风等 → 提炼成提示词
export interface Inspiration {
  query: string;
  prompt: string;
  tags: string[];
  sources: { title: string; url: string }[];
}

// 联网找灵感：DuckDuckGo 搜索 + 对话模型提炼英文提示词。/find 指令用。
export function fetchInspiration(
  query: string,
  chat: { baseUrl: string; apiKey: string; modelName: string },
  proxyUrl = "",
) {
  return apiPost<Inspiration>("/ai/inspiration", {
    query,
    ...chatBody(chat),
    proxy_url: proxyUrl,
  });
}

// 多轮对话流式调用：历史由后端按 threadId(=仓库id) 落盘载入，前端只传本轮输入。
// images 为本轮随文附带的图片（dataURI/URL），非空时后端组多模态消息送 VLM。
// 逐块回调增量文本，结束/出错回调收尾。返回中止函数。
export function chatStream(
  threadId: string,
  message: string,
  chat: { baseUrl: string; apiKey: string; modelName: string },
  onDelta: (text: string) => void,
  onDone: (err?: string) => void,
  images: string[] = [],
  embed?: { baseUrl: string; apiKey: string; modelName: string },
): () => void {
  return openSSE("/ai/chat", {
    thread_id: threadId,
    message,
    images,
    ...chatBody(chat),
    ...sseEmbed(embed),
  }, (obj) => { if (obj.delta) onDelta(String(obj.delta)); }, onDone);
}

// 图像智能体流式调用：对话模型自主调反推/生图工具。
// onDelta 文本增量；onImage 生成的图片地址（可多张）；onDone 收尾。返回中止函数。
export function imageAgentStream(
  threadId: string,
  message: string,
  images: string[],
  chat: { baseUrl: string; apiKey: string; modelName: string },
  gen: { baseUrl: string; apiKey: string; modelName: string },
  size: string,
  onDelta: (text: string) => void,
  onImage: (url: string, id?: string) => void,
  onDone: (err?: string) => void,
  persist?: { outputDir: string; repoId: string; embed: { baseUrl: string; apiKey: string; modelName: string }; messageId?: string; proxyUrl?: string; style?: string; styleTemplate?: string; agentId?: string },
  onInspiration?: (card: Inspiration & { id?: string }) => void,
): () => void {
  return openSSE("/ai/image-agent", {
    thread_id: threadId,
    message,
    images,
    ...chatBody(chat),
    gen_base_url: gen.baseUrl,
    gen_api_key: gen.apiKey,
    gen_model: gen.modelName,
    size,
    output_dir: persist?.outputDir || "",
    repo_id: persist?.repoId || "",
    ...sseEmbed(persist?.embed),
    message_id: persist?.messageId || "",
    proxy_url: persist?.proxyUrl || "",
    style: persist?.style || "",
    style_template: persist?.styleTemplate || "",
    agent_id: persist?.agentId || "",
  }, (obj) => {
    if (obj.delta) onDelta(String(obj.delta));
    if (obj.image) onImage(String(obj.image), obj.image_id as string | undefined);
    if (obj.inspiration) onInspiration?.(obj.inspiration as Inspiration & { id?: string });
  }, onDone);
}

// 拉取某仓库已落盘的对话历史（刷新/进入仓库时回填）
export function fetchHistory(threadId: string) {  return apiGet<{ items: ChatTurn[] }>(
    `/ai/chat/history?thread_id=${encodeURIComponent(threadId)}`,
  );
}

// 清空某仓库对话线
export function clearHistory(threadId: string) {
  return apiPost<{ ok: boolean }>("/ai/chat/clear", { thread_id: threadId });
}

// 压缩对话上下文：AI 把历史+生成记录总结成一条摘要，清空对话线与快照，只留摘要。
// 知识库/资产不动，图与提示词保留。返回摘要消息（含 id），前端用它替换整个消息流。
export function compactHistory(
  threadId: string,
  chat: { baseUrl: string; apiKey: string; modelName: string },
  embed: { baseUrl: string; apiKey: string; modelName: string },
) {
  return apiPost<{ ok: boolean; summary: string; image_count: number; message: { id: string; role: string; text: string } }>(
    "/ai/chat/compact",
    { thread_id: threadId, ...chatBody(chat), ...sseEmbed(embed) },
  );
}

// 把已生成的有价值消息（提示词/图片）落盘，刷新后保留。不调模型。
export function appendMessage(
  threadId: string,
  role: "user" | "assistant",
  text: string,
  images: string[] = [],
) {
  return apiPost<{ ok: boolean }>("/ai/chat/append", {
    thread_id: threadId,
    role,
    text,
    images,
  });
}

// 落盘前端完整消息流快照（含工作流卡/反推卡等非对话消息），作为可靠真源。
export function saveSnapshot(threadId: string, messages: unknown[]) {
  return apiPost<{ ok: boolean }>("/ai/chat/snapshot/save", {
    thread_id: threadId,
    messages,
  });
}

// 读取某仓库的消息流快照（localStorage 缺失时回填，关浏览器/清端口不丢）
export function fetchSnapshot(threadId: string) {
  return apiGet<{ items: unknown[] }>(
    `/ai/chat/snapshot?thread_id=${encodeURIComponent(threadId)}`,
  );
}

// 该仓库是否有后台生成任务在跑（切回/刷新时据此轮询快照等落盘）
export function fetchAgentRunning(threadId: string) {
  return apiGet<{ running: boolean }>(
    `/ai/image-agent/running?thread_id=${encodeURIComponent(threadId)}`,
  );
}

// 打断该仓库的后台生成（半成品文本会落盘并补进记忆供下一轮续写=合并）
export function cancelAgent(threadId: string) {
  return apiPost<{ ok: boolean; running: boolean }>("/ai/image-agent/cancel", {
    thread_id: threadId,
  });
}

// ---- AI 搭工作流：节点知识库 + 自动搭建 ----

type ChatCfg = { baseUrl: string; apiKey: string; modelName: string };

// 启动后台同步：扫描 ComfyUI 已装节点入库。立即返回总包数，进度经 syncProgress 轮询。
export function syncNodes(embed: Embed, comfyUrl: string, full = false) {
  return apiPost<{ total_packs: number; already_running: boolean }>(
    "/ai/nodes/sync",
    { ...sseEmbed(embed), comfy_url: comfyUrl, full },
  );
}

export interface SyncProgress {
  running: boolean; done: number; total: number; current: string;
  synced: number; skipped: number; error: string; finished: boolean;
}
// 同步进度快照（轮询）
export function syncProgress() {
  return apiGet<SyncProgress>("/ai/nodes/sync-progress");
}

// 节点知识库现状（包数 + 节点数）
export function nodeStats(embed: Embed) {
  return apiPost<{ packs: number; nodes: number }>("/ai/nodes/stats", sseEmbed(embed));
}

export interface NodePackItem { id: string; title: string; node_count: number; python_module: string; }
export interface NodePackDetail extends NodePackItem { content: string; node_names: string[]; categories: string[]; }

// 全部节点包列表（管理页）
export function listNodePacks(embed: Embed) {
  return apiPost<{ packs: NodePackItem[] }>("/ai/nodes/packs", sseEmbed(embed));
}
// 单个包完整内容（含用途正文）
export function getNodePack(embed: Embed, packId: string) {
  return apiPost<NodePackDetail>("/ai/nodes/pack", { ...sseEmbed(embed), pack_id: packId });
}
// 修订某包用途正文并重嵌入
export function updateNodePackContent(embed: Embed, packId: string, content: string) {
  return apiPost<{ ok: boolean }>("/ai/nodes/pack/update", { ...sseEmbed(embed), pack_id: packId, content });
}

export interface BuildResult {
  ok: boolean;
  path: string;
  graph: Record<string, unknown>;
  errors: string[];
  warnings?: string[];   // 非阻断提示（如断链孤岛：节点还没接进主链）
  missing_nodes?: string[];  // 本机没装、已从图里移除的节点类型（供「去安装」按钮）
  alternatives?: Record<string, string[]>;  // {缺失节点: [本机同类平替...]}（供「用平替重搭」）
}

// 按需求自动搭工作流：检索节点→AI 生成→校验重试→（可选）落盘到 workflowDir
// currentGraph 非空=在当前画布基础上增量改；save=false 只回图不落盘（多轮迭代中途）
export function buildWorkflow(args: {
  need: string; chat: ChatCfg; embed: Embed; comfyUrl: string; workflowDir: string; name?: string;
  currentGraph?: Record<string, unknown>; save?: boolean; proxy?: string;
}) {
  return apiPost<BuildResult>("/ai/build", {
    base_url: args.chat.baseUrl, api_key: args.chat.apiKey, model: args.chat.modelName, proxy: args.proxy || "",
    ...sseEmbed(args.embed),
    need: args.need, comfy_url: args.comfyUrl, workflow_dir: args.workflowDir, name: args.name || "",
    current_graph: args.currentGraph || {}, save: args.save !== false,
  }, 240000);  // 4 分钟超时，防前端永久“思考中…”
}

// 分模块增量搭建：冻结当前图，AI 只出新模块+锚点，后端合并进整图。返回合并后完整图，前端写回画布。
export function buildModule(args: {
  need: string; chat: ChatCfg; embed: Embed; comfyUrl: string;
  currentGraph: Record<string, unknown>; proxy?: string;
}) {
  return apiPost<BuildResult>("/ai/build/module", {
    base_url: args.chat.baseUrl, api_key: args.chat.apiKey, model: args.chat.modelName, proxy: args.proxy || "",
    ...sseEmbed(args.embed),
    need: args.need, comfy_url: args.comfyUrl, current_graph: args.currentGraph,
  }, 240000);  // 4 分钟超时
}

// 精简直连：信任强模型(Opus)一次到位，只调 1 次模型，不 audit 自修/不重写/不回喂重试。最快。
export function buildDirect(args: {
  need: string; chat: ChatCfg; embed: Embed; comfyUrl: string;
  currentGraph?: Record<string, unknown>; proxy?: string;
}) {
  return apiPost<BuildResult>("/ai/build/direct", {
    base_url: args.chat.baseUrl, api_key: args.chat.apiKey, model: args.chat.modelName, proxy: args.proxy || "",
    ...sseEmbed(args.embed),
    need: args.need, comfy_url: args.comfyUrl, current_graph: args.currentGraph || {},
  }, 180000);  // 单次调用，3 分钟足够
}

// 顾问模式：只产出给人看的中文方案文本，不改画布。用户确认后再走 build/module 执行。
export function buildPlan(args: {
  need: string; chat: ChatCfg; embed: Embed; comfyUrl: string;
  currentGraph?: Record<string, unknown>; proxy?: string;
}) {
  return apiPost<{ plan: string }>("/ai/build/plan", {
    base_url: args.chat.baseUrl, api_key: args.chat.apiKey, model: args.chat.modelName, proxy: args.proxy || "",
    ...sseEmbed(args.embed),
    need: args.need, comfy_url: args.comfyUrl, current_graph: args.currentGraph || {},
  }, 180000);  // 3 分钟超时（只出方案，较快）
}

// 把前端手改后的画布 graph 直接落盘（不经 AI）
export function saveWorkflow(args: {
  graph: Record<string, unknown>; embed: Embed; workflowDir: string; name?: string;
}) {
  return apiPost<{ ok: boolean; path: string }>("/ai/build/save", {
    ...sseEmbed(args.embed),
    graph: args.graph, workflow_dir: args.workflowDir, name: args.name || "",
  });
}

// —— 骨架底座：AI 搭工作流的正确起点 ——
export interface Skeleton {
  id: string; name: string; desc: string; kind: string;
  source: "builtin" | "file"; node_count: number; path: string;
}
// 列出骨架候选（内置 + 工作流文件夹里的 .json）
export function listSkeletons(workflowDir: string) {
  return apiPost<{ skeletons: Skeleton[] }>("/ai/skeletons", { workflow_dir: workflowDir });
}
// 取某骨架的 graph（load 进画布用；文件只读不改）
export function skeletonGraph(skeletonId: string, workflowDir: string) {
  return apiPost<{ graph: Record<string, unknown> }>("/ai/skeleton/graph", {
    skeleton_id: skeletonId, workflow_dir: workflowDir,
  });
}

// —— 搭建会话：进度保存 + 多开 ——
export interface BuildSessionMeta { id: string; name: string; updated_at: number; node_count: number; msg_count: number; }
export interface BuildSessionFull { id: string; name: string; msgs: unknown[]; graph: Record<string, unknown>; skeleton_id: string; updated_at: number; }

export function listBuildSessions() {
  return apiGet<{ sessions: BuildSessionMeta[] }>("/ai/build/sessions");
}
export function getBuildSession(id: string) {
  return apiGet<BuildSessionFull>(`/ai/build/session?id=${encodeURIComponent(id)}`);
}
export function saveBuildSession(args: {
  id?: string; name: string; msgs: unknown[]; graph: Record<string, unknown>; skeletonId?: string;
}) {
  return apiPost<{ id: string; name: string; updated_at: number }>("/ai/build/session/save", {
    id: args.id || "", name: args.name, msgs: args.msgs, graph: args.graph, skeleton_id: args.skeletonId || "",
  });
}
export function deleteBuildSession(id: string) {
  return apiPost<{ ok: boolean }>("/ai/build/session/delete", { id });
}

// 生图完成后把这次生成的提示词/标签/图片入全局 RAG 知识库
export function indexGeneration(
  threadId: string,
  data: { prompt?: string; tags?: string; image_url?: string },
  embed: { baseUrl: string; apiKey: string; modelName: string },
) {
  return apiPost<{ ok: boolean }>("/rag/index-generation", {
    thread_id: threadId,
    prompt: data.prompt || "",
    tags: data.tags || "",
    image_url: data.image_url || "",
    ...ragEmbed(embed),
  });
}

// 手动上传参考资料入全局 RAG 知识库
export function indexDocument(
  threadId: string,
  text: string,
  title: string,
  embed: { baseUrl: string; apiKey: string; modelName: string },
) {
  return apiPost<{ ok: boolean; chunks: number }>("/rag/index-document", {
    thread_id: threadId,
    text,
    title,
    ...ragEmbed(embed),
  });
}

export interface RagDoc {
  id: string;
  content: string;
  kind: string;       // system | document | generation
  title: string;
  locked: boolean;    // 系统指令条目，不可删改
  image_url: string;
}

// 列出「系统库 + 本仓库库」所有条目（顺带幂等播种系统指令）
export function listDocs(repoId: string, embed: Embed) {
  return apiPost<{ items: RagDoc[] }>("/rag/list", {
    repo_id: repoId,
    ...ragEmbed(embed),
  });
}

export interface Generation {
  id: string;
  prompt: string;
  image_url: string;
  tags: string[];
  created_at?: number;   // 入库毫秒时间戳（权威排序键；历史记录可能为 0/缺失）
}

// 列出某仓库的生成记录（图片+提示词+标签），供仓库详情页图片网格
export function listGenerations(repoId: string, embed: Embed) {
  return apiPost<{ items: Generation[] }>("/rag/generations", {
    repo_id: repoId,
    ...ragEmbed(embed),
  });
}

// 清理僵尸记录：指向本机留存图但磁盘文件已不存在的条目（手动删文件留下的裂图）。返回删除条数。
export function pruneGenerations(repoId: string, embed: Embed) {
  return apiPost<{ ok: boolean; removed: number }>("/rag/prune-generations", {
    repo_id: repoId,
    ...ragEmbed(embed),
  });
}

// 聚合仓库集合的标签→图片数量（按量降序），供加标签/搜索的输入补全
export interface TagStat { tag: string; count: number; }
export function tagStats(repoIds: string[], embed: Embed) {
  return apiPost<{ items: TagStat[] }>("/rag/tag-stats", {
    repo_ids: repoIds,
    ...ragEmbed(embed),
  });
}

// 覆盖某资产条目的标签（手动增删 / AI 打标落库）
export function setTags(id: string, repoId: string, tags: string[], embed: Embed) {
  return apiPost<{ ok: boolean }>("/rag/set-tags", {
    id, repo_id: repoId, tags,
    ...ragEmbed(embed),
  });
}

// 把提示词轻量切分成关键词标签（纯文本，非反推，省 token）
export function extractKeywords(
  text: string,
  chat: { baseUrl: string; apiKey: string; modelName: string },
) {
  return apiPost<{ tags: string[] }>("/ai/extract-keywords", {
    text, ...chatBody(chat),
  });
}

// 删除单条（系统条目后端会拒绝）
export function deleteDoc(id: string, repoId: string, embed: Embed, removeFile = false) {
  return apiPost<{ ok: boolean }>("/rag/delete", {
    id, repo_id: repoId, remove_file: removeFile,
    ...ragEmbed(embed),
  });
}

// 编辑单条（系统条目后端会拒绝）
export function updateDoc(id: string, text: string, title: string, repoId: string, embed: Embed) {
  return apiPost<{ ok: boolean }>("/rag/update", {
    id, text, title, repo_id: repoId,
    ...ragEmbed(embed),
  });
}

// 右下角 AI 客服：检索（系统库 + 指定仓库库）流式回答。返回中止函数。
export function supportStream(
  message: string,
  repoId: string,
  chat: Embed,
  embed: Embed,
  onDelta: (text: string) => void,
  onDone: (err?: string) => void,
): () => void {
  return openSSE("/ai/support", {
    message, repo_id: repoId,
    ...chatBody(chat),
    embed_base_url: embed.baseUrl, embed_api_key: embed.apiKey, embed_model: embed.modelName,
  }, (obj) => { if (obj.delta) onDelta(String(obj.delta)); }, onDone);
}
