import { useEffect, useState } from "react";

export interface Repo {
  id: string;
  name: string;
  parentId?: string; // 为空=顶层仓库；有值=某仓库下的小仓库
  cover?: string; // 该仓库最新生成图片
  coverAt?: number; // 封面更新时间戳（用于父仓库取子仓库里最新的一张）
  createdAt: number;
}

const KEY = "laf_repos";

function load(): Repo[] {
  try {
    return JSON.parse(localStorage.getItem(KEY) || "[]");
  } catch {
    return [];
  }
}

function save(repos: Repo[]) {
  localStorage.setItem(KEY, JSON.stringify(repos));
}

export function useRepos() {
  const [repos, setRepos] = useState<Repo[]>(load);

  useEffect(() => {
    save(repos);
  }, [repos]);

  const addRepo = (name: string, parentId?: string) => {
    setRepos((prev) => [
      ...prev,
      { id: crypto.randomUUID(), name, parentId, createdAt: Date.now() },
    ]);
  };

  const renameRepo = (id: string, name: string) => {
    setRepos((prev) => prev.map((r) => (r.id === id ? { ...r, name } : r)));
  };

  // 设置仓库封面（每次生图完成时回填为最新图），记录时间戳供父仓库取最新
  const setCover = (id: string, cover: string) => {
    setRepos((prev) => prev.map((r) => (r.id === id ? { ...r, cover, coverAt: Date.now() } : r)));
  };

  // 删除仓库时一并删除其下所有小仓库
  const deleteRepo = (id: string) => {
    setRepos((prev) => prev.filter((r) => r.id !== id && r.parentId !== id));
  };

  const childrenOf = (parentId?: string) => repos.filter((r) => r.parentId === parentId);

  // 取仓库展示封面：小仓库用自身；顶层仓库用其子仓库里 coverAt 最新的一张
  const coverOf = (r: Repo): string | undefined => {
    if (r.parentId) return r.cover; // 小仓库：自身封面
    const kids = repos.filter((x) => x.parentId === r.id && x.cover);
    if (kids.length === 0) return r.cover; // 没有带图的子仓库则用自身（通常为空）
    kids.sort((a, b) => (b.coverAt || 0) - (a.coverAt || 0));
    return kids[0].cover;
  };

  return { repos, addRepo, renameRepo, setCover, coverOf, deleteRepo, childrenOf };
}
