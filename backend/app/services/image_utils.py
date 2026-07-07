"""万能图片块提取器（搬自参考实现，去依赖）。

兼容 OpenAI / Anthropic / LangChain 新旧多模态格式，清洗 base64 脏数据、
按魔数推断缺失的 MIME。返回标准 URL 或 data URI，认不出返回 None。
agent 工具从对话消息里捞图片时用。
"""
import re
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote
from uuid import uuid4

from app.services.pathnames import safe_seg as _safe_seg

# 与前端 api 一致的本地留存图访问地址（后端落盘后回给前端的地址=快照地址，重开不重复）
_LOCAL_VIEW_BASE = "http://127.0.0.1:8010/api/comfyui/local-view"


def save_remote_image(url: str, output_dir: str, repo_id: str = "home") -> str:
    """把云端生成图（直链 URL 或 data URI）下载落盘到 output_dir/repo_id，
    返回本地 local-view 访问地址（与前端 saveLocalSrc+localViewUrl 等价）。
    无 output_dir 或任何失败时回退原 url（不阻断出图）。
    """
    if not output_dir or not url:
        return url
    try:
        if url.startswith("data:"):
            import base64
            header, b64 = url.split(",", 1)
            data = base64.b64decode(re.sub(r"\s+", "", b64))
            ext = "png"
            if "image/" in header:
                ext = header.split("image/")[1].split(";")[0] or "png"
            name = f"{uuid4().hex}.{_safe_seg(ext)}"
        else:
            import httpx
            with httpx.Client(trust_env=False, timeout=120) as c:  # 规避本地代理劫持
                r = c.get(url)
                r.raise_for_status()
                data = r.content
            tail = _safe_seg(Path(url.split("?")[0]).name)
            name = tail if "." in tail else f"{uuid4().hex}.png"
        from app.services import repo_meta
        base = repo_meta.repo_folder(output_dir, repo_id)  # 文件夹名=仓库名(保中文)，并写 _repo.json
        dest = base / name
        dest.write_bytes(data)
        return f"{_LOCAL_VIEW_BASE}?path={quote(str(dest))}"
    except Exception:
        return url  # 失败回退原地址，图仍能显示，只是不落盘


def extract_image_url(block: Any) -> Optional[str]:
    if not isinstance(block, dict):
        return None
    btype = block.get("type")
    # 1. OpenAI: {"type":"image_url","image_url":{"url":...}}
    if btype == "image_url":
        url_data = block.get("image_url")
        if isinstance(url_data, dict):
            return _clean_and_format(url_data.get("url"))
        return _clean_and_format(url_data)
    # 2. LangChain 新式 / Anthropic: {"type":"image",...}
    if btype == "image":
        if block.get("source_type") == "base64":
            return _build_data_uri(block.get("data"), block.get("mime_type"))
        if block.get("source_type") == "url":
            return _clean_and_format(block.get("url"))
        source = block.get("source")
        if isinstance(source, dict):
            if source.get("type") == "base64":
                return _build_data_uri(source.get("data"), source.get("media_type"))
            if source.get("type") == "url":
                return _clean_and_format(source.get("url"))
    return None


def _build_data_uri(raw_b64: Optional[str], mime: Optional[str]) -> Optional[str]:
    clean = _clean_b64(raw_b64)
    if not clean:
        return None
    final_mime = mime or _guess_mime(clean)
    return f"data:{final_mime};base64,{clean}"


def _clean_b64(b64_str: Optional[str]) -> str:
    if not b64_str:
        return ""
    return re.sub(r"\s+", "", b64_str)


def _clean_and_format(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    url = url.strip()
    if url.startswith("data:"):
        return re.sub(r"\s+", "", url)
    return url


def _guess_mime(b64_str: str) -> str:
    if not b64_str:
        return "image/png"
    head = b64_str[:10]
    if head.startswith("/9j/"):
        return "image/jpeg"
    if head.startswith("iVBOR"):
        return "image/png"
    if head.startswith("R0lGOD"):
        return "image/gif"
    if head.startswith("UklGR"):
        return "image/webp"
    return "image/png"
