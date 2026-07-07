import { useEffect, useState } from "react";
import { Boxes, Bot, Download, Home, Images, Package, Settings, Sparkles, Workflow, type LucideIcon } from "lucide-react";
import { useRepos, type Repo } from "./stores/repos";
import { useSettings, activeChatModel } from "./stores/settings";
import { SupportWidget } from "./components/SupportWidget";
import { SettingsModal } from "./components/SettingsModal";
import { WorkflowTemplates } from "./pages/WorkflowTemplates";
import { ModelDownload } from "./pages/ModelDownload";
import { ConfirmModal, PromptModal } from "./components/Modal";
import { Lightbox } from "./components/Lightbox";
import { ReposView, RepoDetailView } from "./views/repos/RepoViews";
import { ChatView } from "./views/ChatView";
import { AssetsView } from "./views/PlaceholderViews";
import { NodeIndexView } from "./views/NodeIndexView";
import { AIBuildView } from "./views/AIBuildView";
import { NodeManagerView } from "./views/NodeManagerView";
import { listGenerations } from "./api/ai";
import { parseHash, buildHash, type View } from "./lib/viewRouting";

// 侧边栏分组导航（四大区，settings 走弹窗不在此列）。见 FRONTEND_ADAPT_PLAN.md。
const NAV_GROUPS: { label: string; items: { view: View; label: string; icon: LucideIcon }[] }[] = [
  { label: "创作", items: [{ view: "home", label: "首页", icon: Home }] },
  { label: "资产", items: [
    { view: "repos", label: "仓库", icon: Boxes },
    { view: "assets", label: "资产库", icon: Images },
  ] },
  { label: "工作流", items: [
    { view: "workflows", label: "模板管理", icon: Workflow },
    { view: "ai-build", label: "AI 搭工作流", icon: Sparkles },
    { view: "node-index", label: "节点知识库", icon: Bot },
  ] },
  { label: "系统", items: [
    { view: "models", label: "模型下载", icon: Download },
    { view: "node-manager", label: "节点管理", icon: Package },
  ] },
];

// 二级项高亮：repo-detail/chat 归属「仓库」项高亮。
function navActive(view: View, item: View): boolean {
  if (item === "repos") return view === "repos" || view === "repo-detail" || view === "chat";
  return view === item;
}

export function App() {
  const initial = parseHash();
  const [view, setView] = useState<View>(initial.view);
  const [activeRepoId, setActiveRepoId] = useState<string | null>(initial.repoId);
  const { repos, addRepo, renameRepo, setCover, coverOf, deleteRepo, childrenOf } = useRepos();
  const settingsStore = useSettings();
  const { settings } = settingsStore;

  // 视图变化时写入 URL hash
  useEffect(() => {
    const want = buildHash(view, activeRepoId);
    if (window.location.hash !== want) window.location.hash = want;
  }, [view, activeRepoId]);

  // 浏览器前进/后退或手动改 hash 时同步视图
  useEffect(() => {
    const onHash = () => {
      const p = parseHash();
      setView(p.view);
      setActiveRepoId(p.repoId);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  // 弹窗状态
  const [creating, setCreating] = useState(false); // 新建顶层仓库
  const [creatingSubFor, setCreatingSubFor] = useState<string | null>(null); // 在某仓库下新建小仓库
  const [renaming, setRenaming] = useState<Repo | null>(null);
  const [deleting, setDeleting] = useState<Repo | null>(null);
  const [delBlocked, setDelBlocked] = useState<string | null>(null); // 删仓库被资产拦截的提示
  const [showSettings, setShowSettings] = useState(false);
  // 资产库「发送至对话」：先弹框选目标仓库，再跳该仓库 chat 并把图带进输入框
  const [sendImgUrl, setSendImgUrl] = useState<string | null>(null);   // 待发送的图（选仓库中）
  const [sendParent, setSendParent] = useState<string | null>(null);   // 两级选择：已选的顶层仓库
  const [marketSearch, setMarketSearch] = useState<string>("");        // AI搭工作流「去安装」跳市场时预填的搜索词
  const [pendingChatImage, setPendingChatImage] = useState<string | null>(null);  // 跳转后交给 ChatView 插入

  const activeRepo = repos.find((r) => r.id === activeRepoId) || null;

  const openRepo = (r: Repo) => {
    setActiveRepoId(r.id);
    // 小仓库（有父仓库）双击进入 AI 对话窗口；顶层仓库进入详情
    setView(r.parentId ? "chat" : "repo-detail");
  };

  return (
    <div className="layout">
      <Lightbox />
      <aside className="sidebar">
        <div className="brand">ComfyUI-Wrapping-paper</div>
        {NAV_GROUPS.map((g) => (
          <div className="nav-group" key={g.label}>
            <div className="nav-group-title">{g.label}</div>
            {g.items.map((it) => (
              <button
                key={it.view}
                className={`nav-item ${navActive(view, it.view) ? "active" : ""}`}
                onClick={() => setView(it.view)}
              >
                <it.icon size={17} /> {it.label}
              </button>
            ))}
          </div>
        ))}
        <div className="spacer" />
        <button className="nav-item" onClick={() => setShowSettings(true)}>
          <Settings size={18} /> 设置
        </button>
      </aside>

      <main className="main">
        {view === "home" && <ChatView settings={settings} update={settingsStore.update} presets={settingsStore} setCover={setCover} />}
        {view === "assets" && <AssetsView onSendToChat={(url) => setSendImgUrl(url)} />}
        {view === "ai-build" && <AIBuildView onInstallNode={(q) => { setMarketSearch(q); setView("node-manager"); }} />}
        {view === "node-index" && <NodeIndexView />}
        {view === "node-manager" && <NodeManagerView initialSearch={marketSearch} onSearchConsumed={() => setMarketSearch("")} />}
        {view === "repos" && (
          <ReposView
            repos={childrenOf(undefined)}
            title="仓库"
            coverOf={coverOf}
            onOpen={openRepo}
            onRename={setRenaming}
            onDelete={setDeleting}
            onNew={() => setCreating(true)}
          />
        )}
        {view === "repo-detail" && activeRepo && (
          <RepoDetailView
            repo={activeRepo}
            children={childrenOf(activeRepo.id)}
            coverOf={coverOf}
            settings={settings}
            onBack={() => setView("repos")}
            onOpen={openRepo}
            onRename={setRenaming}
            onDelete={setDeleting}
            onNewSub={() => setCreatingSubFor(activeRepo.id)}
          />
        )}
        {view === "workflows" && <WorkflowTemplates settings={settings} />}
        {view === "models" && <ModelDownload settings={settings} />}
        {view === "chat" && activeRepo && (
          <ChatView
            key={activeRepo.id}
            repo={activeRepo}
            settings={settings}
            update={settingsStore.update}
            presets={settingsStore}
            setCover={setCover}
            initialImage={pendingChatImage}
            onImageConsumed={() => setPendingChatImage(null)}
            onBack={() => {
              setActiveRepoId(activeRepo.parentId || null);
              setView(activeRepo.parentId ? "repo-detail" : "repos");
            }}
          />
        )}
        <SupportWidget chat={activeChatModel(settings)} embed={settings.embedModel} repoId={activeRepoId || "home"} />
      </main>

      {creating && (
        <PromptModal
          title="新建仓库"
          confirmText="创建"
          onConfirm={(name) => {
            addRepo(name);
            setCreating(false);
            setView("repos");
          }}
          onCancel={() => setCreating(false)}
        />
      )}

      {creatingSubFor && (
        <PromptModal
          title="新建小仓库"
          confirmText="创建"
          onConfirm={(name) => {
            addRepo(name, creatingSubFor);
            setCreatingSubFor(null);
          }}
          onCancel={() => setCreatingSubFor(null)}
        />
      )}

      {renaming && (
        <PromptModal
          title="重命名仓库"
          defaultValue={renaming.name}
          confirmText="保存"
          onConfirm={(name) => {
            renameRepo(renaming.id, name);
            setRenaming(null);
          }}
          onCancel={() => setRenaming(null)}
        />
      )}

      {deleting && (
        <ConfirmModal
          title="删除仓库"
          message={`确认删除「${deleting.name}」？此操作不可恢复。`}
          confirmText="删除"
          danger
          onConfirm={async () => {
            const target = deleting;
            setDeleting(null);
            // 资产保护：该仓库（含子仓库）若有生成图，拒绝删除，避免误删资产
            const ids = [target.id, ...childrenOf(target.id).map((c) => c.id)];
            let hasAssets = false;
            for (const id of ids) {
              try {
                const r = await listGenerations(id, settings.embedModel);
                if ((r.items || []).length > 0) { hasAssets = true; break; }
              } catch { /* 查询失败按无资产处理，不阻断 */ }
            }
            if (hasAssets) {
              setDelBlocked(`「${target.name}」里还有生成图（资产），已阻止删除。请先在资产库删除这些图片，再删仓库。`);
              return;
            }
            deleteRepo(target.id);
            if (activeRepoId === target.id) setView("repos");
          }}
          onCancel={() => setDeleting(null)}
        />
      )}

      {delBlocked && (
        <ConfirmModal
          title="无法删除仓库"
          message={delBlocked}
          confirmText="知道了"
          onConfirm={() => setDelBlocked(null)}
          onCancel={() => setDelBlocked(null)}
        />
      )}

      {showSettings && (
        <SettingsModal
          settings={settingsStore.settings}
          update={settingsStore.update}
          onClose={() => setShowSettings(false)}
        />
      )}

      {sendImgUrl && (
        <div className="modal-mask" onClick={() => { setSendImgUrl(null); setSendParent(null); }}>
          <div className="modal" style={{ width: 420, maxHeight: "70vh", overflow: "auto" }} onClick={(e) => e.stopPropagation()}>
            <h3 style={{ marginTop: 0 }}>
              {sendParent ? "选择小仓库（对话）" : "发送到哪个仓库？"}
            </h3>
            <p style={{ color: "var(--text-muted)", fontSize: 13, marginTop: 0 }}>
              {sendParent
                ? "对话属于小仓库。选一个小仓库，图片将填入其对话输入框。"
                : "先选顶层仓库，再选其下的小仓库（对话在小仓库里）。"}
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {!sendParent ? (
                <>
                  {childrenOf(undefined).length === 0 && <p style={{ color: "var(--text-muted)", fontSize: 13 }}>还没有仓库。</p>}
                  {childrenOf(undefined).map((r) => (
                    <button key={r.id} className="btn" style={{ justifyContent: "flex-start" }}
                      onClick={() => setSendParent(r.id)}>
                      {r.name} <span style={{ color: "var(--text-muted)", marginLeft: "auto", fontSize: 12 }}>
                        {childrenOf(r.id).length} 个小仓库 ›
                      </span>
                    </button>
                  ))}
                </>
              ) : (
                <>
                  <button className="btn" style={{ justifyContent: "flex-start", color: "var(--text-muted)" }}
                    onClick={() => setSendParent(null)}>← 返回选顶层仓库</button>
                  {childrenOf(sendParent).length === 0 && (
                    <p style={{ color: "var(--text-muted)", fontSize: 13 }}>该仓库下还没有小仓库。</p>
                  )}
                  {childrenOf(sendParent).map((r) => (
                    <button key={r.id} className="btn" style={{ justifyContent: "flex-start" }}
                      onClick={() => {
                        setPendingChatImage(sendImgUrl);
                        setSendImgUrl(null); setSendParent(null);
                        setActiveRepoId(r.id);
                        setView("chat");
                      }}>
                      {r.name}
                    </button>
                  ))}
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
