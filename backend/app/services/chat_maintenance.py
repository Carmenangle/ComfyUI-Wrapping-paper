"""对话维护：集中清理、缓存清理与压缩的保留规则和失败语义。"""
from __future__ import annotations

import hashlib
import json
import shutil
import threading
import uuid
from dataclasses import dataclass

from app.services import agent_runner, chat_memory, chat_snapshot, rag_store, repo_meta
from app.services.pathnames import safe_seg
from app.services.rag_store import EmbedConfig


class MaintenanceConflict(RuntimeError):
    pass


class MaintenanceFailed(RuntimeError):
    pass


class NothingToCompact(ValueError):
    pass


@dataclass(frozen=True)
class ClearCacheResult:
    removed: int


_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock(thread_id: str) -> threading.RLock:
    key = safe_seg(thread_id or "home", "home", strip=False)
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


def _ensure_idle(thread_id: str) -> None:
    if agent_runner.is_running(thread_id):
        raise MaintenanceConflict("该对话仍有后台生成任务，请等待完成或先停止")


def _revision(history: list[dict]) -> str:
    raw = json.dumps(history, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def clear(thread_id: str) -> dict:
    with _lock(thread_id):
        _ensure_idle(thread_id)
        try:
            chat_memory.clear_history(thread_id)
        except Exception as exc:
            raise MaintenanceFailed(f"清空对话失败：{exc}") from exc
    return {"ok": True}


def clear_cache(thread_id: str, output_dir: str) -> ClearCacheResult:
    with _lock(thread_id):
        _ensure_idle(thread_id)
        try:
            old_snapshot = chat_snapshot.load_strict(thread_id)
            chat_snapshot.save(thread_id, [])
        except Exception as exc:
            raise MaintenanceFailed(f"清空消息快照失败：{exc}") from exc
        try:
            chat_memory.clear_history(thread_id)
        except Exception as exc:
            try:
                chat_snapshot.save(thread_id, old_snapshot)
            except Exception:
                pass
            raise MaintenanceFailed(f"清空对话失败：{exc}") from exc

        removed = 0
        if output_dir:
            reference = repo_meta.repo_folder_path(output_dir, thread_id) / "reference"
            if reference.is_dir():
                removed = sum(1 for path in reference.iterdir() if path.is_file())
                try:
                    shutil.rmtree(reference)
                except Exception as exc:
                    raise MaintenanceFailed(f"删除参考图失败：{exc}") from exc
                if reference.exists():
                    raise MaintenanceFailed("删除参考图失败：目录仍然存在")
        return ClearCacheResult(removed=removed)


def compact(thread_id: str, llm, embed_cfg: EmbedConfig) -> dict:
    lock = _lock(thread_id)
    with lock:
        _ensure_idle(thread_id)
        try:
            history = chat_memory.get_history(thread_id)
            old_snapshot = chat_snapshot.load_strict(thread_id)
        except Exception as exc:
            raise MaintenanceFailed(f"读取对话状态失败：{exc}") from exc
        revision = _revision(history)

    try:
        generations = rag_store.list_generations(thread_id, embed_cfg)
    except Exception as exc:
        raise MaintenanceFailed(f"读取生成记录失败：{exc}") from exc
    result = chat_memory.summarize_history(history, llm, generations)
    if not result.get("ok"):
        error = result.get("error")
        if error:
            raise MaintenanceFailed(f"生成摘要失败：{error}")
        raise NothingToCompact("无可压缩内容或摘要为空")

    summary = result["summary"]
    message = {
        "id": str(uuid.uuid4()),
        "role": "assistant",
        "text": "【历史摘要】\n" + summary,
    }
    checkpoint_summary = [{
        "role": "assistant",
        "content": "【历史摘要】\n" + summary,
        "images": [],
    }]

    with lock:
        _ensure_idle(thread_id)
        current = chat_memory.get_history(thread_id)
        if _revision(current) != revision:
            raise MaintenanceConflict("对话在压缩期间已更新，请重试")
        try:
            chat_snapshot.save(thread_id, [message])
        except Exception as exc:
            raise MaintenanceFailed(f"写入摘要快照失败：{exc}") from exc
        try:
            chat_memory.replace_history(thread_id, checkpoint_summary)
        except Exception as exc:
            try:
                chat_snapshot.save(thread_id, old_snapshot)
            except Exception:
                pass
            try:
                chat_memory.replace_history(thread_id, history)
            except Exception:
                pass
            raise MaintenanceFailed(f"写入摘要对话失败：{exc}") from exc

    return {
        "ok": True,
        "summary": summary,
        "image_count": result.get("image_count", 0),
        "message": message,
    }
