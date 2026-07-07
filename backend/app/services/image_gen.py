"""云端生图：OpenAI 兼容 images/generations。

httpx 直调（不依赖 langchain-community 的 DallEAPIWrapper，更可控）。
设置里的「生图模型」(imageModels) 透传 base_url/api_key/model。
返回图片地址：优先直链 URL；若接口只回 b64_json 则拼成 data URI。
trust_env=False 规避本地系统代理劫持 127.0.0.1 的坑（与 rag_store 一致）。
"""
import httpx


def _norm_url(base_url: str) -> str:
    url = (base_url or "").rstrip("/")
    if "/images/generations" in url:
        return url
    if not url.endswith("/v1"):
        url += "/v1"
    return url + "/images/generations"


def _norm_edits_url(base_url: str) -> str:
    url = (base_url or "").rstrip("/")
    if "/images/edits" in url:
        return url
    if "/images/generations" in url:  # 用户填的是生成地址，换成编辑地址
        return url.replace("/images/generations", "/images/edits")
    if not url.endswith("/v1"):
        url += "/v1"
    return url + "/images/edits"


def _load_image_bytes(img: str) -> tuple[bytes, str, str]:
    """把 data URI / http(s) URL 图片读成 (字节, 文件名, mime)。图生图上传用。"""
    import base64
    import re
    if img.startswith("data:"):
        header, b64 = img.split(",", 1)
        data = base64.b64decode(re.sub(r"\s+", "", b64))
        mime = header.split(":", 1)[1].split(";")[0] if ":" in header else "image/png"
    else:
        with httpx.Client(trust_env=False, timeout=120) as c:  # 规避本地代理劫持
            r = c.get(img)
            r.raise_for_status()
            data = r.content
            mime = r.headers.get("content-type", "image/png").split(";")[0]
    ext = (mime.split("/")[1] if "/" in mime else "png") or "png"
    return data, f"image.{ext}", mime


def generate(base_url: str, api_key: str, model: str, prompt: str,
             size: str = "1024x1024") -> str:
    """纯文生图，返回可展示地址（http URL 或 data:image/...;base64,...）。

    失败抛异常，由调用方（工具/路由）捕获转成错误文本。
    """
    if not base_url or not model:
        raise ValueError("未配置生图模型（设置 → 生图模型：API URL / 模型名）")
    url = _norm_url(base_url)
    headers = {"Authorization": f"Bearer {api_key or 'not-needed'}",
               "Content-Type": "application/json"}
    payload = {"model": model, "prompt": prompt, "n": 1, "size": size,
               "moderation": "low", "quality": "high"}
    with httpx.Client(trust_env=False, timeout=300) as c:
        r = c.post(url, headers=headers, json=payload)
        if r.status_code >= 400:
            raise RuntimeError(f"生图接口 {r.status_code}：{r.text[:300]}（请求地址 {url}）")
        data = r.json()
    items = data.get("data") or []
    if not items:
        raise RuntimeError(f"生图接口未返回图片：{str(data)[:200]}")
    first = items[0] or {}
    if first.get("url"):
        return first["url"]
    b64 = first.get("b64_json")
    if b64:
        return f"data:image/png;base64,{b64}"
    raise RuntimeError(f"生图返回无 url/b64_json：{str(first)[:200]}")


def generate_with_images(base_url: str, api_key: str, model: str, prompt: str,
                         images: list[str], size: str = "1024x1024") -> str:
    """图生图：把提示词 + 一张或多张参考图交给 images/edits 接口，返回图片地址。

    走 OpenAI 官方 multipart/form-data，多图用同名 image[] 字段全部上传。
    失败抛异常，由调用方（工具）捕获转成错误文本。
    """
    if not base_url or not model:
        raise ValueError("未配置生图模型（设置 → 生图模型：API URL / 模型名）")
    if not images:
        raise ValueError("图生图需要至少一张参考图")
    url = _norm_edits_url(base_url)
    headers = {"Authorization": f"Bearer {api_key or 'not-needed'}"}  # multipart 不设 Content-Type
    files = []
    for img in images:
        data, name, mime = _load_image_bytes(img)
        files.append(("image[]", (name, data, mime)))
    payload = {"model": model, "prompt": prompt, "n": "1", "size": size,
               "moderation": "low", "quality": "high"}
    with httpx.Client(trust_env=False, timeout=300) as c:
        r = c.post(url, headers=headers, data=payload, files=files)
        if r.status_code >= 400:
            raise RuntimeError(f"图生图接口 {r.status_code}：{r.text[:300]}（请求地址 {url}）")
        data = r.json()
    items = data.get("data") or []
    if not items:
        raise RuntimeError(f"图生图接口未返回图片：{str(data)[:200]}")
    first = items[0] or {}
    if first.get("url"):
        return first["url"]
    b64 = first.get("b64_json")
    if b64:
        return f"data:image/png;base64,{b64}"
    raise RuntimeError(f"图生图返回无 url/b64_json：{str(first)[:200]}")

