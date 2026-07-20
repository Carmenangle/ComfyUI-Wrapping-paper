import type { PanelProps } from "./GeneralPanel";

export function PathsPanel({ draft, setDraft }: PanelProps) {
  return (
    <div className="settings-section">
      <h4>路径</h4>
      <div className="field">
        <label>工作流默认读取路径</label>
        <input
          value={draft.workflowDir}
          onChange={(e) => setDraft((d) => ({ ...d, workflowDir: e.target.value }))}
          placeholder="D:\\ComfyUI\\workflows"
        />
      </div>
      <div className="field">
        <label>输出图片默认存放路径</label>
        <input
          value={draft.outputDir}
          onChange={(e) => setDraft((d) => ({ ...d, outputDir: e.target.value }))}
          placeholder="D:\\ComfyUI\\output"
        />
      </div>
      <div className="field">
        <label>ComfyUI 目录（含 main.py）</label>
        <input
          value={draft.comfyuiPath}
          onChange={(e) => setDraft((d) => ({ ...d, comfyuiPath: e.target.value }))}
          placeholder="D:\\tool\\ComfyUI\\ComfyUI_aaaki\\ComfyUI"
        />
      </div>
      <div className="field">
        <label>ComfyUI 访问地址</label>
        <input
          value={draft.comfyuiUrl}
          onChange={(e) => setDraft((d) => ({ ...d, comfyuiUrl: e.target.value }))}
          placeholder="http://127.0.0.1:8188"
        />
      </div>
      <div className="field">
        <label>ComfyUI Python（可选）</label>
        <input
          value={draft.comfyuiPython || ""}
          onChange={(e) => setDraft((d) => ({ ...d, comfyuiPython: e.target.value }))}
          placeholder="D:\\ComfyUI\\.venv\\Scripts\\python.exe"
        />
        <p className="field-hint">
          留空时自动查找 ComfyUI 整合包或 .venv/venv；不会使用本工具的 Python。
        </p>
      </div>
      <div className="field">
        <label>
          <input
            type="checkbox"
            checked={draft.proxyEnabled}
            onChange={(e) => setDraft((d) => ({ ...d, proxyEnabled: e.target.checked }))}
            style={{ marginRight: 6, verticalAlign: "-1px" }}
          />
          启用联网搜索代理
        </label>
        <input
          value={draft.proxyUrl}
          disabled={!draft.proxyEnabled}
          onChange={(e) => setDraft((d) => ({ ...d, proxyUrl: e.target.value }))}
          placeholder="http://127.0.0.1:7897"
          style={draft.proxyEnabled ? undefined : { opacity: 0.5 }}
        />
        <p className="field-hint">
          联网找灵感（/find、AI 搜索）走此代理访问外网。关闭则直连（国内多半连不上）。
        </p>
      </div>
      <div className="field">
        <label>模型目录（models）</label>
        <input
          value={draft.modelsDir}
          onChange={(e) => setDraft((d) => ({ ...d, modelsDir: e.target.value }))}
          placeholder="D:\\tool\\ComfyUI\\...\\ComfyUI\\models"
        />
        <p className="field-hint">
          下载的模型按类型存进此目录的子文件夹（checkpoints/loras/vae 等），ComfyUI 原生识别。
        </p>
      </div>
    </div>
  );
}
