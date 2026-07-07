// 生成流程的纯判定/整形逻辑（无 React、无 I/O）：从 useChatSession 闭包里抽出，
// 让「图像门 / 快照瘦身 / 文本打分」这些真会咬人的分支可被单测。
// 依赖注入原则：涉及落盘的部分（persist）由调用方传入函数，本模块只管遍历与决策。
import type { ChatMessage } from "../types/chat";
import type { Template } from "../api/workflows";

// ===== 图像门（image gate）=====
// 判断一个工作流模板是否声明了图像输入口，以及抓取到的画布里该输入口是否已填图。
// 用于 /s 出图前拦截「图生图工作流但没给图」。

// 模板是否定义了图像输入口
export function needsImageInput(tpl: Template): boolean {
  return !!tpl.image_node_id || (tpl.exposed || []).some((f) => f.control === "image");
}

// 值是否算「已填」：非 null/undefined/空串、非空数组
function nonEmpty(v: unknown): boolean {
  return v !== null && v !== undefined && v !== "" && !(Array.isArray(v) && v.length === 0);
}

// capturedGraph 里图像输入节点是否已有图值。
// 同时兼容两种图结构：litegraph { nodes:[{id,widgets_values}] } 与 API { id:{inputs} }。
// 拿不准（两种结构都不匹配）就放行，不误拦。
export function hasImageProvided(graph: unknown, tpl: Template): boolean {
  const g = graph as any;
  const ids = new Set<string>();
  if (tpl.image_node_id) ids.add(String(tpl.image_node_id));
  for (const f of tpl.exposed || []) if (f.control === "image") ids.add(String(f.node_id));
  if (ids.size === 0) return true;
  if (g && Array.isArray(g.nodes)) {
    for (const n of g.nodes) {
      if (!ids.has(String(n.id))) continue;
      const wv = n.widgets_values;
      if (Array.isArray(wv) ? wv.some(nonEmpty) : nonEmpty(wv)) return true;
    }
    return false;
  }
  if (g && typeof g === "object") {
    for (const id of ids) {
      const node = g[id];
      const inp = node?.inputs;
      if (inp && Object.values(inp).some(nonEmpty)) return true;
    }
    return false;
  }
  return true; // 拿不准就放行
}

// ===== 文本打分：从生成结果的多段文本里挑最优 =====
// 过滤掉「有效字符占比过低」的噪声段（如纯符号/乱码），再按长度取最长的一段。
// 有效字符 = 字母数字 + 中文。占比阈值 0.3。
export function pickBestText(texts: readonly string[] | undefined): string {
  const cleaned = (texts || [])
    .map((t) => t.trim())
    .filter((t) => t.length > 0)
    .filter((t) => (t.replace(/[^\w一-龥]/g, "").length / t.length) > 0.3);
  return cleaned.sort((a, b) => b.length - a.length)[0] || "";
}

// ===== 快照瘦身：把消息流里的 data:URI 大图落盘转小地址 =====
// 遍历与决策是纯的；实际落盘由调用方注入 persist（data:URI → 小地址，失败返回原值）。
export async function slimSnapshot(
  msgs: readonly ChatMessage[],
  persist: (src: string) => Promise<string>,
): Promise<ChatMessage[]> {
  const out: ChatMessage[] = [];
  for (const m of msgs) {
    let nm = m;
    // 1) 用户消息 parts 里的上传图 → 落盘转小地址
    if (nm.parts?.some((p) => p.type === "image" && p.url?.startsWith("data:"))) {
      const parts = await Promise.all(
        nm.parts.map(async (p) =>
          p.type === "image" && p.url ? { ...p, url: await persist(p.url) } : p,
        ),
      );
      nm = { ...nm, parts };
    }
    // 2) portsPlan.images
    if (nm.portsPlan?.images?.length) {
      const pp = nm.portsPlan;
      if (pp.status === "applied" || pp.status === "ignored") {
        nm = { ...nm, portsPlan: { ...pp, images: [] } };  // 已执行：副本无用，清空
      } else {
        const imgs = await Promise.all(pp.images.map((s) => persist(s)));  // 待执行：落盘保留
        nm = { ...nm, portsPlan: { ...pp, images: imgs } };
      }
    }
    out.push(nm);
  }
  return out;
}
