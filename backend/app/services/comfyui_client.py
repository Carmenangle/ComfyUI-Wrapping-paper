"""与 ComfyUI 的 HTTP 对话集中于此：探活、提交 /prompt、轮询 /history、
取图 /view、打断、上传图片。协议怪癖（端点、错误模式、响应结构）只此一处。
路由层只做适配（读模板、落盘、进程），不再直接拼 ComfyUI 请求。
"""
import json
import socket
from urllib.error import HTTPError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

import requests


class ComfyError(Exception):
    """ComfyUI 通信/校验错误。detail 供路由透出，status 建议 HTTP 码。"""

    def __init__(self, detail: str, status: int = 502):
        super().__init__(detail)
        self.detail = detail
        self.status = status


def _base(url: str) -> str:
    return url.rstrip("/")


def is_up(url: str, timeout: float = 1.5) -> bool:
    """探测 ComfyUI 是否在响应；HTTP 失败则退化为 TCP 端口探测。"""
    try:
        with urlopen(url, timeout=timeout) as r:
            return r.status < 500
    except Exception:
        try:
            p = urlparse(url)
            host = p.hostname or "127.0.0.1"
            port = p.port or 8188
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except Exception:
            return False


def fetch_object_info(url: str, node: str = "", timeout: float = 15) -> dict:
    """拉取 /object_info（全量节点 schema）或 /object_info/{node}（单节点）。
    返回 {节点名: schema}。失败抛 ComfyError。自动搭工作流的地基。"""
    endpoint = _base(url) + "/object_info" + (f"/{node}" if node else "")
    try:
        with urlopen(endpoint, timeout=timeout) as r:
            return json.loads(r.read())
    except HTTPError as e:
        raise ComfyError(f"取 object_info 失败：{e}", 502)
    except Exception as e:
        raise ComfyError(str(e), 502)


def submit_prompt(url: str, api: dict) -> str | None:
    """POST /prompt，返回 prompt_id。HTTPError 透出 ComfyUI 校验详情。"""
    body = json.dumps({"prompt": api}).encode("utf-8")
    rq = Request(_base(url) + "/prompt", data=body, headers={"Content-Type": "application/json"})
    try:
        with urlopen(rq, timeout=10) as r:
            res = json.loads(r.read())
        return res.get("prompt_id")
    except HTTPError as e:
        try:
            detail = e.read().decode("utf-8", "replace")
        except Exception:
            detail = str(e)
        raise ComfyError(detail, 500)
    except Exception as e:
        raise ComfyError(str(e), 500)


def fetch_result(url: str, prompt_id: str) -> dict:
    """轮询 /history/{id}，归一为 {status, images, texts}。"""
    try:
        with urlopen(_base(url) + f"/history/{prompt_id}", timeout=10) as r:
            hist = json.loads(r.read())
    except Exception as e:
        raise ComfyError(f"查询历史失败：{e}", 502)

    entry = hist.get(prompt_id)
    if not entry:
        return {"status": "pending", "images": [], "texts": []}

    completed = entry.get("status", {}).get("completed", False)
    images: list[dict[str, str]] = []
    texts: list[str] = []
    for node_out in entry.get("outputs", {}).values():
        for img in node_out.get("images", []):
            images.append({
                "filename": img.get("filename", ""),
                "subfolder": img.get("subfolder", ""),
                "type": img.get("type", "output"),
            })
        for t in node_out.get("text", []) or []:
            if isinstance(t, str) and t.strip():
                texts.append(t)
    return {
        "status": "completed" if completed else "running",
        "images": images,
        "texts": texts,
    }


def fetch_view(url: str, filename: str, type: str = "output", subfolder: str = "",
               timeout: int = 15) -> tuple[bytes, str]:
    """代理取 /view 图片二进制，返回 (data, content_type)。"""
    qs = urlencode({"filename": filename, "type": type, "subfolder": subfolder})
    try:
        with urlopen(_base(url) + f"/view?{qs}", timeout=timeout) as r:
            return r.read(), r.headers.get("Content-Type", "image/png")
    except Exception as e:
        raise ComfyError(f"取图失败：{e}", 502)


def interrupt(url: str, prompt_id: str = "") -> dict:
    """先从队列删未执行项，再中断正在执行的。ComfyUI 未起/已完成均不报错。"""
    base = _base(url)
    deleted = False
    interrupted = False
    if prompt_id:
        try:
            requests.post(base + "/queue", json={"delete": [prompt_id]}, timeout=5)
            deleted = True
        except Exception:
            pass
    try:
        requests.post(base + "/interrupt", timeout=5)
        interrupted = True
    except Exception:
        pass
    return {"deleted": deleted, "interrupted": interrupted}


def upload_image(url: str, filename: str, data: bytes, content_type: str = "image/png") -> str:
    """转发上传到 ComfyUI 的 input 目录，返回 LoadImage 可引用的相对名。"""
    files = {"image": (filename, data, content_type or "image/png")}
    try:
        resp = requests.post(
            _base(url) + "/upload/image",
            files=files,
            data={"overwrite": "true"},
            timeout=30,
        )
        resp.raise_for_status()
        res = resp.json()
    except requests.RequestException as e:
        raise ComfyError(f"上传失败：{e}", 500)
    name = res.get("name", "")
    sub = res.get("subfolder", "")
    ref = f"{sub}/{name}" if sub else name
    return ref
