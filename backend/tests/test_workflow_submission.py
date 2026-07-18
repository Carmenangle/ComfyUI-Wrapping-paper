import json

import pytest

from app.services import workflow_submission
from app.services.comfyui_client import ComfyError


def _ready(monkeypatch):
    monkeypatch.setattr(workflow_submission.comfyui_client, "is_up", lambda url: True)


def test_模板提交集中完成读取注入和上游提交(tmp_path, monkeypatch):
    source = tmp_path / "workflow.json"
    source.write_text(json.dumps({"1": {"class_type": "Node", "inputs": {}}}), encoding="utf-8")
    monkeypatch.setattr(workflow_submission.template_store, "get_template", lambda _id: {
        "source_path": str(source), "exposed": [], "prompt_node_id": "",
    })
    _ready(monkeypatch)
    calls = []
    monkeypatch.setattr(
        workflow_submission.comfyui_client,
        "submit_prompt",
        lambda url, api, client_id: calls.append((url, api, client_id)) or "prompt-1",
    )

    result = workflow_submission.submit_template(
        "template-1", {}, "", "http://127.0.0.1:8188", "client-1",
    )

    assert result == {"ok": True, "prompt_id": "prompt-1", "node_count": 1}
    assert calls[0][2] == "client-1"


def test_模板缺少必填输入返回422(tmp_path, monkeypatch):
    source = tmp_path / "workflow.json"
    source.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(workflow_submission.template_store, "get_template", lambda _id: {
        "source_path": str(source), "exposed": [], "prompt_node_id": "",
    })
    _ready(monkeypatch)
    monkeypatch.setattr(workflow_submission.workflow_injector, "inject_template_values", lambda *args: ["steps"])

    with pytest.raises(workflow_submission.WorkflowSubmissionError) as exc_info:
        workflow_submission.submit_template("template-1", {}, "", "http://127.0.0.1:8188")

    assert exc_info.value.status == 422
    assert exc_info.value.detail == {"missing": ["steps"]}


def test_图提交保留ComfyUI错误语义(monkeypatch):
    _ready(monkeypatch)
    monkeypatch.setattr(
        workflow_submission.comfyui_client,
        "submit_prompt",
        lambda *args: (_ for _ in ()).throw(ComfyError("invalid node", 400)),
    )

    with pytest.raises(workflow_submission.WorkflowSubmissionError) as exc_info:
        workflow_submission.submit_graph({}, "http://127.0.0.1:8188")

    assert exc_info.value.status == 400
    assert exc_info.value.detail == "ComfyUI 拒绝：invalid node"
