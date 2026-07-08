// 纯逻辑：URL hash 解析/构建 与 生图尺寸计算。
// 从 App.tsx 提出，脱离 1829 行大组件，接口即测试面（无需渲染整模块即可单测）。

export type View =
  | "home" | "repos" | "repo-detail" | "chat"     // 创作/资产
  | "assets"                                        // 资产库(全站聚合)
  | "workflows" | "ai-build" | "node-index"         // 工作流区
  | "models" | "node-manager"                       // 系统区
  | "settings";                                     // 设置中心（整页路由）

// 单段 hash 的 view 集合（无 repoId 参数），parse/build 共用避免重复。
const SIMPLE_VIEWS: View[] = ["repos", "assets", "workflows", "ai-build", "node-index", "models", "node-manager", "settings"];

// URL hash <-> 视图状态：刷新后停留在当前页面
export function parseHash(): { view: View; repoId: string | null } {
  const h = decodeURIComponent(window.location.hash.replace(/^#\/?/, ""));
  const [seg, id] = h.split("/");
  if ((SIMPLE_VIEWS as string[]).includes(seg)) return { view: seg as View, repoId: null };
  if (seg === "repo" && id) return { view: "repo-detail", repoId: id };
  if (seg === "chat" && id) return { view: "chat", repoId: id };
  return { view: "home", repoId: null };
}

export function buildHash(view: View, repoId: string | null): string {
  if ((SIMPLE_VIEWS as string[]).includes(view)) return `#/${view}`;
  if (view === "repo-detail" && repoId) return `#/repo/${repoId}`;
  if (view === "chat" && repoId) return `#/chat/${repoId}`;
  return "#/home";
}

// 比例 + 分辨率档 → 像素宽高。基准短边按档位取（1k=1024,2k=2048,4k=4096），长边按比例放大，
// 都对齐到 8 的倍数（生图模型通常要求）。返回 "宽x高" 字符串。
export const ASPECTS = ["21:9", "16:9", "4:3", "1:1", "3:4", "9:16", "9:21"];
export const RES_TIERS: Record<string, number> = { "1k": 1024, "2k": 2048, "4k": 4096 };

export function calcSize(aspect: string, tier: string): string {
  const [aw, ah] = aspect.split(":").map(Number);
  const base = RES_TIERS[tier] || 1024;
  const round8 = (n: number) => Math.max(8, Math.round(n / 8) * 8);
  let w: number, h: number;
  if (aw >= ah) { h = base; w = base * (aw / ah); }  // 横向/方形：短边=高
  else { w = base; h = base * (ah / aw); }            // 纵向：短边=宽
  return `${round8(w)}x${round8(h)}`;
}
