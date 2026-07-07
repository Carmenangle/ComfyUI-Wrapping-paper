import { useEffect, useState } from "react";
import { Boxes, Pencil, Plus, Search, Trash2 } from "lucide-react";
import { type Repo } from "../../stores/repos";
import { useSettings } from "../../stores/settings";
import { Pager } from "../../components/Pager";

// 仓库封面：图片加载失败（本地文件被删/ComfyUI 离线/地址失效）时回退占位，不显示破图
export function RepoCover({ src, name }: { src?: string; name: string }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => { setFailed(false); }, [src]);  // 换封面地址后重置
  if (!src || failed) return <>暂无图片</>;
  return <img src={src} alt={name} loading="lazy" onError={() => setFailed(true)} />;
}

export function RepoGrid({
  repos,
  emptyText,
  coverOf,
  onOpen,
  onRename,
  onDelete,
}: {
  repos: Repo[];
  emptyText: string;
  coverOf: (r: Repo) => string | undefined;
  onOpen: (r: Repo) => void;
  onRename: (r: Repo) => void;
  onDelete: (r: Repo) => void;
}) {
  if (repos.length === 0) {
    return (
      <div className="empty-state">
        <Boxes size={32} strokeWidth={1.4} style={{ opacity: 0.5 }} />
        <p style={{ margin: 0 }}>{emptyText}</p>
      </div>
    );
  }
  return (
    <div className="repo-grid">
      {repos.map((r) => {
        const cover = coverOf(r);
        return (
        <div className="repo-card" key={r.id}>
          <div className="repo-cover" onDoubleClick={() => onOpen(r)} title="双击打开">
            <RepoCover src={cover} name={r.name} />
          </div>
          <div className="repo-tools">
            <button className="icon-btn" title="重命名" onClick={() => onRename(r)}>
              <Pencil size={15} />
            </button>
            <button className="icon-btn" title="删除" onClick={() => onDelete(r)}>
              <Trash2 size={15} />
            </button>
          </div>
          <div className="repo-name">{r.name}</div>
        </div>
        );
      })}
    </div>
  );
}

export function ReposView({
  repos,
  title,
  coverOf,
  onOpen,
  onRename,
  onDelete,
  onNew,
}: {
  repos: Repo[];
  title: string;
  coverOf: (r: Repo) => string | undefined;
  onOpen: (r: Repo) => void;
  onRename: (r: Repo) => void;
  onDelete: (r: Repo) => void;
  onNew: () => void;
}) {
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const kw = q.trim().toLowerCase();
  const shownRepos = kw ? repos.filter((r) => r.name.toLowerCase().includes(kw)) : repos;
  const REPO_PAGE_SIZE = 20;  // 每行 5 个，一页最多 4 行；超过才翻页（正常向下增多）
  const repoPageCount = Math.max(1, Math.ceil(shownRepos.length / REPO_PAGE_SIZE));
  const curPage = Math.min(page, repoPageCount);
  const pagedRepos = shownRepos.slice((curPage - 1) * REPO_PAGE_SIZE, curPage * REPO_PAGE_SIZE);
  return (
    <div className="page">
      <div className="page-head">
        <h1>{title}</h1>
        <button className="btn" onClick={onNew}>
          <Plus size={15} style={{ verticalAlign: "-2px", marginRight: 4 }} />
          新建仓库
        </button>
      </div>
      {repos.length > 0 && (
        <div style={{ position: "relative", marginBottom: 16, maxWidth: 320 }}>
          <Search size={14} style={{ position: "absolute", left: 9, top: 9, color: "var(--text-muted)" }} />
          <input style={{ width: "100%", paddingLeft: 28, boxSizing: "border-box" }} placeholder="搜索仓库名称…"
            value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
        </div>
      )}
      <RepoGrid
        repos={pagedRepos}
        emptyText={kw ? `没有名称含「${q}」的仓库。` : "还没有仓库，点击右上角「新建仓库」创建一个。"}
        coverOf={coverOf}
        onOpen={onOpen}
        onRename={onRename}
        onDelete={onDelete}
      />
      <Pager page={curPage} pageCount={repoPageCount} onPage={setPage} />
    </div>
  );
}

export function RepoDetailView({
  repo,
  children,
  coverOf,
  settings,
  onBack,
  onOpen,
  onRename,
  onDelete,
  onNewSub,
}: {
  repo: Repo;
  children: Repo[];
  coverOf: (r: Repo) => string | undefined;
  settings: ReturnType<typeof useSettings>["settings"];
  onBack: () => void;
  onOpen: (r: Repo) => void;
  onRename: (r: Repo) => void;
  onDelete: (r: Repo) => void;
  onNewSub: () => void;
}) {
  const [subQ, setSubQ] = useState("");
  const [subPage, setSubPage] = useState(1);
  const SUB_PAGE_SIZE = 20;  // 每行 5 × 4 行，多了翻页（资产库已独立成一级页，这里不再嵌）
  const kw = subQ.trim().toLowerCase();
  const matched = kw ? children.filter((r) => r.name.toLowerCase().includes(kw)) : children;
  const subPageCount = Math.max(1, Math.ceil(matched.length / SUB_PAGE_SIZE));
  const subCur = Math.min(subPage, subPageCount);
  const shownChildren = matched.slice((subCur - 1) * SUB_PAGE_SIZE, subCur * SUB_PAGE_SIZE);
  return (
    <div className="page">
      <div className="page-head">
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <button className="back-btn" onClick={onBack}>
            ← 返回
          </button>
          <h1>{repo.name}</h1>
        </div>
        <button className="btn" onClick={onNewSub}>
          <Plus size={15} style={{ verticalAlign: "-2px", marginRight: 4 }} />
          新建小仓库
        </button>
      </div>

      <h3 style={{ margin: "4px 0 12px", fontSize: 15 }}>小仓库（角色 / 画风等）</h3>
      {children.length > 0 && (
        <div style={{ position: "relative", marginBottom: 12, maxWidth: 320 }}>
          <Search size={14} style={{ position: "absolute", left: 9, top: 9, color: "var(--text-muted)" }} />
          <input style={{ width: "100%", paddingLeft: 28, boxSizing: "border-box" }} placeholder="搜索小仓库名称…"
            value={subQ} onChange={(e) => { setSubQ(e.target.value); setSubPage(1); }} />
        </div>
      )}
      <RepoGrid
        repos={shownChildren}
        emptyText={kw ? `没有名称含「${subQ}」的小仓库。` : "还没有小仓库，点击右上角「新建小仓库」来存放角色、画风等内容。"}
        coverOf={coverOf}
        onOpen={onOpen}
        onRename={onRename}
        onDelete={onDelete}
      />
      <Pager page={subCur} pageCount={subPageCount} onPage={setSubPage} />
    </div>
  );
}

