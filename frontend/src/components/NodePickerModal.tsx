import { useEffect, useRef, useState } from "react";
import { rawWorkflowByPath } from "../api/workflows";
import { lockUrl, postToFrame, isLafMessageFromStrict } from "../lib/lafLock";

interface Props {
  title: string;            // 提示词输入口 / 图像输入口
  comfyUrl: string;
  sourcePath: string;       // 工作流原始文件路径
  onPick: (id: string, nodeTitle: string) => void;
  onCancel: () => void;
}

// 在真实 ComfyUI 画布里长按选择一个节点作为输入口；选中后弹确认。
export function NodePickerModal({ title, comfyUrl, sourcePath, onPick, onCancel }: Props) {
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const [hint, setHint] = useState("");
  const [pending, setPending] = useState<{ id: string; title: string } | null>(null);

  useEffect(() => {
    const post = (type: string, payload: unknown) =>
      postToFrame(iframeRef.current?.contentWindow, type, payload, comfyUrl);
    const onMsg = async (ev: MessageEvent) => {
      if (!isLafMessageFromStrict(ev, iframeRef.current?.contentWindow, comfyUrl)) return;
      const d = ev.data;
      if (d.type === "ready") {
        try {
          const r = await rawWorkflowByPath(sourcePath);
          // exposedIds 空 = 全量节点模式，启用长按选择
          post("load", { workflow: r.workflow, exposedIds: [] });
        } catch (e) {
          setHint(`载入失败：${(e as Error).message}`);
        }
      } else if (d.type === "node_selected") {
        const id = String(d.payload.id);
        setPending({ id, title: d.payload.title || `#${id}` });
      }
    };
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, [sourcePath, comfyUrl]);

  // 重选：取消当前候选并清除画布高亮
  const reselect = () => {
    if (pending) {
      postToFrame(iframeRef.current?.contentWindow, "deselect", { id: pending.id }, comfyUrl);
    }
    setPending(null);
  };

  return (
    <div className="modal-mask" style={{ zIndex: 110 }}>
      <div className="modal" onClick={(e) => e.stopPropagation()} style={{ width: "min(900px, 94vw)" }}>
        <h3>选择{title}</h3>
        <p style={{ color: "var(--text-muted)", marginTop: 0, fontSize: 13 }}>
          在画布上长按要作为「{title}」的节点；选中后确认。
        </p>
        {hint && <p style={{ color: "#c98a1a", fontSize: 13 }}>{hint}</p>}

        <div className="lock-canvas" style={{ height: "min(60vh, 520px)" }}>
          <iframe
            ref={iframeRef}
            src={lockUrl(comfyUrl)}
            title="选择节点"
            className="lock-frame"
          />
        </div>

        {pending && (
          <p style={{ marginTop: 10 }}>
            已选：<strong>{pending.title}</strong>{" "}
            <span style={{ color: "var(--text-muted)" }}>#{pending.id}</span>
          </p>
        )}

        <div className="modal-actions" style={{ marginTop: 12 }}>
          <button className="btn" onClick={onCancel}>
            取消
          </button>
          {pending && (
            <button className="btn" onClick={reselect}>
              重选
            </button>
          )}
          <button
            className="btn primary"
            disabled={!pending}
            onClick={() => pending && onPick(pending.id, pending.title)}
          >
            确认
          </button>
        </div>
      </div>
    </div>
  );
}
