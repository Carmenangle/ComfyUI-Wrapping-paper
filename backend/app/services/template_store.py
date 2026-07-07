"""工作流模板持久化：每个模板存为一个 JSON 文件。

模板结构：
{
  "id": "uuid",
  "name": "模板名",
  "source_path": "原始 workflow 文件路径（可选）",
  "exposed": [
    {
      "node_id": "5",
      "field": "steps",
      "label": "采样步数",       # 展示用标签
      "control": "number",       # 控件类型 text/number/textarea/select/image/seed/boolean
      "semantic": "steps",       # 语义标签，供 AI 自动填充
      "default": 20              # 默认值
    }
  ],
  "created_at": 1700000000.0,
  "updated_at": 1700000000.0
}
"""
from __future__ import annotations

import json
import time
import uuid

from app.config import TEMPLATES_DIR


def _ensure_dir() -> None:
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)


def _path(template_id: str) -> "object":
    return TEMPLATES_DIR / f"{template_id}.json"


def _normalize(record: dict) -> dict:
    """归一化模板：把旧的 prompt_node_id/image_node_id 合并进 input_node_ids，
    保证老模板无缝兼容新的「替换输入节点 / 替换输出节点」多选结构。"""
    if not isinstance(record, dict):
        return record
    inputs = list(record.get("input_node_ids") or [])
    for legacy in (record.get("prompt_node_id"), record.get("image_node_id")):
        s = str(legacy or "")
        if s and s not in inputs:
            inputs.append(s)
    record["input_node_ids"] = inputs
    record["output_node_ids"] = list(record.get("output_node_ids") or [])
    return record


def list_templates() -> list[dict]:
    _ensure_dir()
    items: list[dict] = []
    for p in sorted(TEMPLATES_DIR.glob("*.json")):
        try:
            items.append(_normalize(json.loads(p.read_text(encoding="utf-8"))))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
    items.sort(key=lambda t: t.get("updated_at", 0), reverse=True)
    return items


def get_template(template_id: str) -> dict | None:
    p = _path(template_id)
    if not p.exists():
        return None
    try:
        return _normalize(json.loads(p.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def save_template(data: dict, template_id: str | None = None) -> dict:
    _ensure_dir()
    now = time.time()
    if template_id:
        existing = get_template(template_id) or {}
        created = existing.get("created_at", now)
    else:
        template_id = uuid.uuid4().hex
        created = now
    record = {
        "id": template_id,
        "name": data.get("name", "未命名模板"),
        "source_path": data.get("source_path", ""),
        "exposed": data.get("exposed", []),
        "node_order": data.get("node_order", []),
        "description": data.get("description", ""),
        "prompt_node_id": data.get("prompt_node_id", ""),
        "image_node_id": data.get("image_node_id", ""),
        "input_node_ids": list(data.get("input_node_ids") or []),
        "output_node_ids": list(data.get("output_node_ids") or []),
        "created_at": created,
        "updated_at": now,
    }
    _path(template_id).write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return record


def delete_template(template_id: str) -> bool:
    p = _path(template_id)
    if p.exists():
        p.unlink()
        return True
    return False
