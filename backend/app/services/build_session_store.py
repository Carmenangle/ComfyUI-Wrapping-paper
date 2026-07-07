"""AI 搭工作流的「搭建会话」持久化：进度保存 + 多开。

痛点：AIBuildView 的进度（左栏对话 msgs + 右栏画布图）原本全在内存，切走页面/刷新/
重启 ComfyUI（装完新节点必重启）都会丢——尤其顾问模式推荐装节点后重启，搭到一半全没。

一个会话 = 一次搭建任务：{id, name, msgs[], graph(API格式), skeleton_id, updated_at}。
- 进度保存：msgs 和当前画布 graph 都落盘，重启后重新 load graph 回画布 + 恢复对话。
- 多开：多个命名会话并存，可切换/新建/删除，互不干扰。
每会话一个 JSON 文件，沿用 chat_snapshot 的落盘思路（原子写）。
"""
import json
import time
from uuid import uuid4

from app.config import DATA_DIR
from app.services.pathnames import safe_seg

SESS_DIR = DATA_DIR / "build_sessions"


def _path(sess_id: str):
    return SESS_DIR / f"{safe_seg(sess_id, 'x', strip=False)}.json"


def list_sessions() -> list[dict]:
    """列出全部会话的元信息（不含 msgs/graph 大字段），按更新时间倒序。"""
    if not SESS_DIR.exists():
        return []
    out = []
    for p in SESS_DIR.glob("*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        out.append({
            "id": d.get("id", p.stem),
            "name": d.get("name", "未命名"),
            "updated_at": d.get("updated_at", 0),
            "node_count": len(d.get("graph", {})) if isinstance(d.get("graph"), dict) else 0,
            "msg_count": len(d.get("msgs", [])),
        })
    out.sort(key=lambda x: x.get("updated_at", 0), reverse=True)
    return out


def get_session(sess_id: str) -> dict | None:
    """读取单个会话完整内容（含 msgs + graph），不存在返回 None。"""
    p = _path(sess_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_session(sess_id: str, name: str, msgs: list, graph: dict, skeleton_id: str = "") -> dict:
    """保存/覆盖会话。sess_id 为空则新建一个 id。返回会话元信息（含 id）。"""
    SESS_DIR.mkdir(parents=True, exist_ok=True)
    sid = (sess_id or "").strip() or uuid4().hex
    data = {
        "id": sid,
        "name": (name or "").strip() or "未命名工作流",
        "msgs": msgs or [],
        "graph": graph or {},
        "skeleton_id": skeleton_id or "",
        "updated_at": int(time.time() * 1000),
    }
    p = _path(sid)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)  # 原子替换
    return {"id": sid, "name": data["name"], "updated_at": data["updated_at"]}


def delete_session(sess_id: str) -> bool:
    """删除会话文件。不存在返回 False。"""
    p = _path(sess_id)
    if not p.exists():
        return False
    p.unlink()
    return True
