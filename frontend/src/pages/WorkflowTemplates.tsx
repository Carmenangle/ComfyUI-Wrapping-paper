import { useEffect, useRef, useState } from "react";
import { FileUp, FolderSearch, Workflow as WorkflowIcon, Trash2, Pencil, FileText, Eye, List, ChevronUp, ChevronDown } from "lucide-react";
import { type Settings, activeChatModel } from "../stores/settings";
import { comfyStatus } from "../api/comfyui";
import { lockUrl, postToFrame, isLafMessageFromStrict } from "../lib/lafLock";
import { useWorkflowTemplates } from "../lib/useWorkflowTemplates";
import { DescribeModal, type DescribeValue } from "../components/DescribeModal";
import { ConfirmModal, AlertModal, PromptModal } from "../components/Modal";
import { PageShell } from "../components/layout/PageShell";
import {
  rawWorkflowByPath,
  createTemplate,
  updateTemplate,
  type ParsedNode,
  type ParsedField,
  type Template,
  type ExposedField,
  type ControlType,
} from "../api/workflows";

const CONTROL_LABELS: Record<ControlType, string> = {
  text: "单行文本",
  textarea: "多行文本",
  number: "数字",
  select: "下拉选择",
  image: "图片",
  seed: "随机种子",
  boolean: "开关",
};

// 按字段名/值推断默认控件类型
function inferControl(f: ParsedField): ControlType {
  const n = f.name.toLowerCase();
  if (n.includes("image") || n.includes("mask")) return "image";
  if (n === "seed" || n === "noise_seed") return "seed";
  if (typeof f.value === "boolean") return "boolean";
  if (typeof f.value === "number") return "number";
  if (n.includes("text") || n.includes("prompt")) return "textarea";
  return "text";
}

// 截断超长默认值显示
function shortVal(v: unknown): string {
  const s = String(v);
  return s.length > 60 ? s.slice(0, 60) + "…" : s;
}

export function WorkflowTemplates({ settings }: { settings: Settings }) {
  const {
    files, parsed, setParsed, fileName, sourcePath, editingTemplate, templates,
    error, busy, describeTarget, setDescribeTarget, deleting, setDeleting,
    nodeSyncing, building, showBuild, setShowBuild, alertMsg, setAlertMsg,
    onSyncNodes, onBuild, onScan, onOpenScanned, onPickFile, onEditTemplate,
    onEditDescribe, saveDescribe, onSaved, onDeleteTemplate,
  } = useWorkflowTemplates(settings);

  return (
    <PageShell
      title="工作流模板"
      actions={
        <>
          <button className="btn" onClick={onSyncNodes} disabled={nodeSyncing}
            title="扫描 ComfyUI 已装节点建立知识库，供 AI 搭工作流检索">
            <WorkflowIcon size={15} style={{ verticalAlign: "-2px", marginRight: 4 }} />
            {nodeSyncing ? "同步中…" : "同步节点库"}
          </button>
          <button className="btn" onClick={() => setShowBuild(true)} disabled={building || !settings.workflowDir}
            title="用自然语言描述需求，AI 检索节点自动搭建工作流并存到默认路径">
            <WorkflowIcon size={15} style={{ verticalAlign: "-2px", marginRight: 4 }} />
            {building ? "搭建中…" : "AI 搭工作流"}
          </button>
          <button className="btn" onClick={onScan} disabled={!settings.workflowDir || busy}>
            <FolderSearch size={15} style={{ verticalAlign: "-2px", marginRight: 4 }} />
            扫描默认目录
          </button>
          <label className="btn primary" style={{ cursor: "pointer" }}>
            <FileUp size={15} style={{ verticalAlign: "-2px", marginRight: 4 }} />
            选择文件导入
            <input type="file" accept=".json" hidden onChange={onPickFile} />
          </label>
        </>
      }
    >

      {!settings.workflowDir && (
        <p style={{ color: "var(--text-muted)" }}>
          未设置工作流默认读取路径。可在「设置 → 路径」中配置后扫描该目录，或直接「选择文件导入」。
        </p>
      )}

      {error && <p style={{ color: "#d23b3b" }}>{error}</p>}

      {!parsed && (
        <>
          {files.length > 0 && (
            <div className="list" style={{ marginTop: 12 }}>
              {files.map((f) => (
                <div className="row" key={f.path}>
                  <div>
                    <strong>{f.name}</strong>
                    <p style={{ margin: "4px 0 0", color: "var(--text-muted)", fontSize: 12 }}>{f.rel}</p>
                  </div>
                  <button className="btn" onClick={() => onOpenScanned(f)} disabled={busy}>
                    新建模板
                  </button>
                </div>
              ))}
            </div>
          )}

          <h2 style={{ marginTop: 28, fontSize: 16 }}>已保存模板</h2>
          {templates.length === 0 ? (
            <div style={{ marginTop: 8, color: "var(--text-muted)" }}>
              <WorkflowIcon size={18} style={{ verticalAlign: "-3px", marginRight: 6 }} />
              还没有模板。扫描目录或导入文件，勾选要暴露的参数后保存。
            </div>
          ) : (
            <div className="list" style={{ marginTop: 8 }}>
              {templates.map((t) => (
                <div className="row" key={t.id}>
                  <div>
                    <strong>{t.name}</strong>
                    <p style={{ margin: "4px 0 0", color: "var(--text-muted)", fontSize: 12 }}>
                      {(t.node_order?.length ?? 0)} 个节点
                      {t.exposed.length > 0 ? ` · ${t.exposed.length} 个暴露字段` : ""}
                      {t.source_path ? ` · ${t.source_path}` : "（无原始路径）"}
                    </p>
                  </div>
                  <div style={{ display: "flex", gap: 6 }}>
                    <button className="icon-btn" title="编辑" onClick={() => onEditTemplate(t)}>
                      <Pencil size={15} />
                    </button>
                    <button className="icon-btn" title="编写能力描述" onClick={() => onEditDescribe(t)}>
                      <FileText size={15} />
                    </button>
                    <button className="icon-btn" title="删除" onClick={() => setDeleting(t)}>
                      <Trash2 size={15} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {parsed && (
        <NodeEditor
          fileName={fileName}
          sourcePath={sourcePath}
          nodes={parsed}
          template={editingTemplate}
          comfyUrl={settings.comfyuiUrl}
          chat={activeChatModel(settings)}
          onBack={() => setParsed(null)}
          onSaved={onSaved}
        />
      )}

      {describeTarget && (
        <DescribeModal
          workflowName={describeTarget.template.name}
          nodes={describeTarget.nodes.map((n) => ({ id: n.id, type: n.class_type, title: n.title }))}
          chat={activeChatModel(settings)}
          comfyUrl={settings.comfyuiUrl}
          sourcePath={describeTarget.template.source_path}
          initial={{
            description: describeTarget.template.description || "",
            input_node_ids: describeTarget.template.input_node_ids || [],
            output_node_ids: describeTarget.template.output_node_ids || [],
            primary_output_node_id: describeTarget.template.primary_output_node_id || "",
          }}
          onConfirm={saveDescribe}
          onCancel={() => setDescribeTarget(null)}
        />
      )}
      {deleting && (
        <ConfirmModal
          title="删除模板"
          message={`确认删除模板「${deleting.name}」？`}
          confirmText="删除"
          danger
          onConfirm={() => { const t = deleting; setDeleting(null); onDeleteTemplate(t); }}
          onCancel={() => setDeleting(null)}
        />
      )}
      {showBuild && (
        <PromptModal
          title="AI 搭工作流：描述你要的功能"
          defaultValue=""
          confirmText="开始搭建"
          onConfirm={onBuild}
          onCancel={() => setShowBuild(false)}
        />
      )}
      {alertMsg && (
        <AlertModal title={alertMsg.title} message={alertMsg.message} onClose={() => setAlertMsg(null)} />
      )}
    </PageShell>
  );
}

const fieldKey = (nodeId: string, field: string) => `${nodeId}.${field}`;

function NodeEditor({
  fileName,
  sourcePath,
  nodes,
  template,
  comfyUrl,
  chat,
  onBack,
  onSaved,
}: {
  fileName: string;
  sourcePath: string;
  nodes: ParsedNode[];
  template: Template | null;
  comfyUrl: string;
  chat: { baseUrl: string; apiKey: string; modelName: string };
  onBack: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(template?.name || fileName.replace(/\.json$/i, ""));
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const [showDescribe, setShowDescribe] = useState(false);
  // 视图模式：list=参数清单（可勾选暴露），comfy=嵌真实 ComfyUI 画布预览
  const [viewMode, setViewMode] = useState<"list" | "comfy">("list");
  const [comfyHint, setComfyHint] = useState("");
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  // 画布模式下长按选中的节点，按选择顺序排列；供后续 AI 对话按此顺序提供节点
  const [picked, setPicked] = useState<{ id: string; title: string }[]>(
    () => (template?.node_order || []).map((id) => ({ id, title: `#${id}` })),
  );

  // key -> 暴露配置
  const [exposed, setExposed] = useState<Map<string, ExposedField>>(() => {
    const m = new Map<string, ExposedField>();
    // 仅在编辑已保存模板时回填；新建时全不勾，由用户手动选择
    if (template) {
      for (const ef of template.exposed) m.set(fieldKey(ef.node_id, ef.field), ef);
    }
    return m;
  });

  const toggle = (n: ParsedNode, f: ParsedField) => {
    const key = fieldKey(n.id, f.name);
    setExposed((prev) => {
      const next = new Map(prev);
      if (next.has(key)) next.delete(key);
      else
        next.set(key, {
          node_id: n.id,
          field: f.name,
          label: f.name,
          control: inferControl(f),
          semantic: f.name,
          default: f.value,
        });
      return next;
    });
  };

  const patch = (key: string, p: Partial<ExposedField>) =>
    setExposed((prev) => {
      const cur = prev.get(key);
      if (!cur) return prev;
      const next = new Map(prev);
      next.set(key, { ...cur, ...p });
      return next;
    });

  const onSave = async () => {
    // 先弹能力描述弹窗（方案 C），确定后才真正保存
    setShowDescribe(true);
  };

  const doSave = async (d: DescribeValue) => {
    setShowDescribe(false);
    setErr("");
    setSaving(true);
    const payload = {
      name,
      source_path: sourcePath,
      exposed: [...exposed.values()],
      node_order: picked.map((p) => p.id),
      description: d.description,
      input_node_ids: d.input_node_ids,
      output_node_ids: d.output_node_ids,
      primary_output_node_id: d.primary_output_node_id || "",
    };
    try {
      if (template) await updateTemplate(template.id, payload);
      else await createTemplate(payload);
      onSaved();
    } catch (e) {
      setErr(`保存失败：${(e as Error).message}`);
      setSaving(false);
    }
  };

  // 切换到 ComfyUI 画布模式：先确认 ComfyUI 在跑
  const toggleComfyMode = async () => {
    if (viewMode === "comfy") {
      setViewMode("list");
      return;
    }
    setComfyHint("");
    try {
      const s = await comfyStatus(comfyUrl);
      if (!s.running) {
        setComfyHint("ComfyUI 未启动。请在对话页「ComfyUI 节点面板」启动，或运行 start-dev。");
        return;
      }
      setViewMode("comfy");
    } catch {
      setComfyHint("无法连接 ComfyUI，请确认已启动。");
    }
  };

  // 画布模式：iframe 内扩展 ready 后，把整张工作流发去载入（exposedIds 空=显示全部节点）
  useEffect(() => {
    if (viewMode !== "comfy") return;
    const post = (type: string, payload: unknown) =>
      postToFrame(iframeRef.current?.contentWindow, type, payload, comfyUrl);
    const onMsg = async (ev: MessageEvent) => {
      if (!isLafMessageFromStrict(ev, iframeRef.current?.contentWindow, comfyUrl)) return;
      const d = ev.data;
      if (d.type === "ready") {
        try {
          const r = await rawWorkflowByPath(sourcePath);
          post("load", { workflow: r.workflow, exposedIds: [] });
        } catch (e) {
          setComfyHint(`载入失败：${(e as Error).message}`);
        }
      } else if (d.type === "loaded") {
        // 载图后回填已选节点的高亮（重新进入画布时保持选择状态）
        for (const p of picked) post("reselect", { id: p.id });
      } else if (d.type === "node_selected") {
        const id = String(d.payload.id);
        setPicked((prev) =>
          prev.some((p) => p.id === id)
            ? prev
            : [...prev, { id, title: d.payload.title || `#${id}` }],
        );
      } else if (d.type === "node_title") {
        // 重新进入画布时扩展回传真实标题，替换占位的 #id
        const id = String(d.payload.id);
        setPicked((prev) =>
          prev.map((p) => (p.id === id ? { ...p, title: d.payload.title || p.title } : p)),
        );
      }
    };
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, [viewMode, sourcePath, picked, comfyUrl]);

  // 从右侧列表删除一个选中节点（同步取消画布高亮）
  const removePicked = (id: string) => {
    setPicked((prev) => prev.filter((p) => p.id !== id));
    postToFrame(iframeRef.current?.contentWindow, "deselect", { id }, comfyUrl);
  };

  // 列表排序：上移/下移
  const movePicked = (idx: number, dir: -1 | 1) => {
    setPicked((prev) => {
      const next = [...prev];
      const j = idx + dir;
      if (j < 0 || j >= next.length) return prev;
      [next[idx], next[j]] = [next[j], next[idx]];
      return next;
    });
  };

  return (
    <div style={{ marginTop: 16 }}>
      <div className="template-editor-summary">
        <button className="back-btn" onClick={onBack}>
          ← 返回列表
        </button>
        <span style={{ color: "var(--text-muted)" }}>
          {fileName}　{nodes.length} 个节点，已选 {picked.length} 个节点
          {exposed.size > 0 ? `，已暴露 ${exposed.size} 个字段` : ""}。
        </span>
      </div>

      <div className="template-editor-toolbar">
        <div className="field" style={{ maxWidth: 360, flex: 1, margin: 0 }}>
          <label>模板名称</label>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="模板名称" />
        </div>
        <button className="btn" onClick={toggleComfyMode} title="在真实 ComfyUI 画布中查看节点">
          {viewMode === "comfy" ? (
            <>
              <List size={15} style={{ verticalAlign: "-2px", marginRight: 4 }} />
              参数清单模式
            </>
          ) : (
            <>
              <Eye size={15} style={{ verticalAlign: "-2px", marginRight: 4 }} />
              ComfyUI 界面模式
            </>
          )}
        </button>
      </div>
      {comfyHint && <p style={{ color: "#c98a1a", fontSize: 13, marginTop: 6 }}>{comfyHint}</p>}

      {viewMode === "comfy" && (
        <div className="template-canvas-layout">
          <div className="lock-canvas" style={{ height: 600, flex: 1 }}>
            <iframe
              ref={iframeRef}
              src={lockUrl(comfyUrl)}
              title="ComfyUI 画布预览"
              className="lock-frame"
            />
          </div>
          <div className="picked-panel">
            <div className="picked-head">
              已选节点 <span style={{ color: "var(--text-muted)" }}>({picked.length})</span>
            </div>
            <p className="picked-tip">在画布上长按节点选择；列表顺序即 AI 对话提供节点的顺序。</p>
            {picked.length === 0 ? (
              <div className="picked-empty">长按画布中的节点加入</div>
            ) : (
              <div className="picked-list">
                {picked.map((p, i) => (
                  <div className="picked-item" key={p.id}>
                    <span className="picked-idx">{i + 1}</span>
                    <span className="picked-name" title={p.title}>
                      {p.title} <span style={{ color: "var(--text-muted)" }}>#{p.id}</span>
                    </span>
                    <button className="icon-btn" title="上移" disabled={i === 0} onClick={() => movePicked(i, -1)}>
                      <ChevronUp size={14} />
                    </button>
                    <button
                      className="icon-btn"
                      title="下移"
                      disabled={i === picked.length - 1}
                      onClick={() => movePicked(i, 1)}
                    >
                      <ChevronDown size={14} />
                    </button>
                    <button className="icon-btn" title="移除" onClick={() => removePicked(p.id)}>
                      <Trash2 size={14} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {viewMode === "list" && nodes.map((n) => (
        <div className="image-model-card" key={n.id} style={{ opacity: n.bypassed ? 0.55 : 1 }}>
          <div className="row-head">
            <strong>
              {n.title || n.class_type}{" "}
              <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>
                #{n.id} · {n.class_type}
              </span>
            </strong>
            {n.bypassed && (
              <span style={{ color: "#c98a1a", fontSize: 12 }}>已绕过 / 静音</span>
            )}
          </div>
          {n.fields.map((f) => {
            const key = fieldKey(n.id, f.name);
            const cfg = exposed.get(key);
            return (
              <div key={key} style={{ padding: "6px 0", opacity: f.linked ? 0.45 : 1 }}>
                <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <input
                    type="checkbox"
                    disabled={f.linked}
                    checked={!!cfg}
                    onChange={() => toggle(n, f)}
                    style={{ width: "auto", margin: 0 }}
                  />
                  <span style={{ flex: 1 }}>{f.name}</span>
                  {f.linked ? (
                    <span style={{ color: "var(--text-muted)", fontSize: 12 }}>连线（不可暴露）</span>
                  ) : f.value === null || f.value === "" ? (
                    <span style={{ color: "var(--text-muted)", fontSize: 12 }}>空值</span>
                  ) : (
                    <span
                      style={{ color: "var(--text-muted)", fontSize: 12, maxWidth: 380, textAlign: "right" }}
                      title={String(f.value)}
                    >
                      默认 {shortVal(f.value)}
                    </span>
                  )}
                </label>

                {cfg && (
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "1fr 1fr 1fr",
                      gap: 8,
                      margin: "8px 0 4px 24px",
                    }}
                  >
                    <div className="field" style={{ margin: 0 }}>
                      <label>显示标签</label>
                      <input
                        value={cfg.label}
                        onChange={(e) => patch(key, { label: e.target.value })}
                        placeholder="展示给用户的名称"
                      />
                    </div>
                    <div className="field" style={{ margin: 0 }}>
                      <label>控件类型</label>
                      <select
                        value={cfg.control}
                        onChange={(e) => patch(key, { control: e.target.value as ControlType })}
                      >
                        {(Object.keys(CONTROL_LABELS) as ControlType[]).map((c) => (
                          <option key={c} value={c}>
                            {CONTROL_LABELS[c]}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="field" style={{ margin: 0 }}>
                      <label>语义标签（供 AI）</label>
                      <input
                        value={cfg.semantic}
                        onChange={(e) => patch(key, { semantic: e.target.value })}
                        placeholder="如 positive_prompt"
                      />
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      ))}

      {err && <p style={{ color: "#d23b3b" }}>{err}</p>}

      {/* 右下角固定保存按钮，不随滚动移动；左移避开 AI 客服悬浮球 */}
      <button
        className="btn primary template-save-fab"
        onClick={onSave}
        disabled={saving || !name.trim()}
      >
        {saving ? "保存中…" : template ? "更新模板" : "保存模板"}
      </button>

      {showDescribe && (
        <DescribeModal
          workflowName={name}
          nodes={nodes.map((n) => ({ id: n.id, type: n.class_type, title: n.title }))}
          chat={chat}
          comfyUrl={comfyUrl}
          sourcePath={sourcePath}
          initial={{
            description: template?.description || "",
            input_node_ids: template?.input_node_ids || [],
            output_node_ids: template?.output_node_ids || [],
            primary_output_node_id: template?.primary_output_node_id || "",
          }}
          onConfirm={doSave}
          onCancel={() => setShowDescribe(false)}
        />
      )}
    </div>
  );
}
