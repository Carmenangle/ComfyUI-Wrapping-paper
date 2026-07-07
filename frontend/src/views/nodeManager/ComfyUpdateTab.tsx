import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { StateHint } from "../../components/layout/PageShell";
import { ConfirmModal } from "../../components/Modal";
import { useSettings } from "../../stores/settings";
import { comfyuiGitVersions, switchComfyui, startQueue, type GitVersion } from "../../api/nodeManager";
import { useQueueProgress } from "./useQueueProgress";

// ComfyUI 本体：全量版本列表(读 git tag，带发布日期) + 正式版/开发版 + 切换。
// 正式版 = git tag(vX.Y.Z)；开发版 = nightly(最新 master)。切换后需重启生效。
export function ComfyUpdateTab({ url }: { url: string }) {
  const { settings } = useSettings();
  const path = settings.comfyuiPath;
  const [versions, setVersions] = useState<GitVersion[]>([]);
  const [current, setCurrent] = useState("");
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [channel, setChannel] = useState<"stable" | "dev">("stable");
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [pendingVer, setPendingVer] = useState("");  // 切换成功待重启的目标版本
  const { prog, track, setResult } = useQueueProgress(url);

  const load = () => {
    if (!path) { setErr("未配置 ComfyUI 目录（设置 → 路径）"); setLoading(false); return; }
    setLoading(true); setErr("");
    comfyuiGitVersions(path)
      .then((r) => { setVersions(r.versions); setCurrent(r.current); })
      .catch((e) => setErr((e as Error).message))
      .finally(() => setLoading(false));
  };
  useEffect(load, [path]); // eslint-disable-line react-hooks/exhaustive-deps

  const doSwitch = async () => {
    setConfirm(false);
    setBusy("");
    const target = selected;
    try {
      await switchComfyui(url, target);
      await startQueue(url);
      // 队列进度轮询；完成后复查 current 是否真变成目标版本（Manager 队列只报空否、不报成败）
      track(`切换到 ${target}`, async () => {
        try {
          const r = await comfyuiGitVersions(path);
          setVersions(r.versions);
          setCurrent(r.current);
          if (r.current === target) {
            setPendingVer(target);
            setResult(`已切换到 ${target}，重启 ComfyUI 后生效（右上角「重启」）。`);
          } else {
            setResult(`切换未完成：当前仍为 ${r.current}。可能失败，请查看 comfyui.log 后重试。`);
          }
        } catch (e) {
          setResult(`已提交切换到 ${target}，但版本复查失败：${(e as Error).message}。可点「刷新版本列表」确认。`);
        }
      });
    } catch (e) {
      setBusy(`切换失败：${(e as Error).message}`);
    }
  };

  // 正式版 = git tag 全量；开发版 = 单个 nightly 选项
  const stableRows = versions;
  const devRows: GitVersion[] = [{ version: "nightly", date: "最新开发分支" }];
  const rows = channel === "stable" ? stableRows : devRows;

  if (loading) return <StateHint>读取 ComfyUI 版本列表…</StateHint>;
  if (err) return <StateHint kind="error">{err}</StateHint>;

  return (
    <div>
      <p style={{ fontSize: 14, marginTop: 0 }}>
        当前版本：<strong style={{ color: "var(--accent)" }}>{current}</strong>
        <button className="btn" style={{ marginLeft: 12 }} onClick={load}>
          <RefreshCw size={14} style={{ verticalAlign: "-2px", marginRight: 4 }} />刷新版本列表
        </button>
      </p>

      <div className="page-toolbar">
        <label style={{ fontSize: 13, cursor: "pointer" }}>
          <input type="radio" checked={channel === "stable"} onChange={() => { setChannel("stable"); setSelected(""); }} /> 正式版
        </label>
        <label style={{ fontSize: 13, cursor: "pointer" }}>
          <input type="radio" checked={channel === "dev"} onChange={() => { setChannel("dev"); setSelected(""); }} /> 开发版
        </label>
        <span style={{ fontSize: 12, color: "var(--text-muted)" }}>共 {stableRows.length} 个正式版</span>
      </div>

      <div className="node-table" style={{ maxHeight: 420, overflow: "auto" }}>
        <div className="ver-row ver-row-head"><span>版本</span><span>发布日期</span></div>
        {rows.map((v) => (
          <button
            key={v.version}
            className={`ver-row ${selected === v.version ? "sel" : ""}`}
            onClick={() => setSelected(v.version)}
          >
            <span>
              {v.version}
              {v.version === pendingVer
                ? <span style={{ color: "var(--warning)", marginLeft: 8 }}>（待重启）</span>
                : v.version === current && <span style={{ color: "var(--success)", marginLeft: 8 }}>（当前版本）</span>}
            </span>
            <span style={{ color: "var(--text-muted)" }}>{v.date}</span>
          </button>
        ))}
      </div>

      <button
        className="btn primary"
        style={{ marginTop: 12 }}
        disabled={!selected || selected === current || prog.active}
        onClick={() => setConfirm(true)}
      >
        {prog.active ? "切换中…" : `更新到选中版本${selected ? `（${selected}）` : ""}`}
      </button>
      {prog.text && (
        <div className="build-result ok" style={{ marginTop: 12 }}>
          {prog.active && <span className="bot-spinner" style={{ marginRight: 8 }} />}
          {prog.text}
        </div>
      )}
      {busy && <p style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 12 }}>{busy}</p>}

      {confirm && (
        <ConfirmModal
          title="切换 ComfyUI 版本"
          message={`将把 ComfyUI 从 ${current} 切换到 ${selected}，可能影响插件兼容性。完成后需重启。确认？`}
          confirmText="切换"
          onConfirm={doSwitch}
          onCancel={() => setConfirm(false)}
        />
      )}
    </div>
  );
}
