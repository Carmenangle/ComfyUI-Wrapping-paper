import json
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.config import COMFYUI_BASE_URL
from app.services import (
    comfyui_client, comfy_launcher, generation_store, image_store,
    template_store, workflow_injector,
)
from app.services.comfyui_client import ComfyError
from app.services.comfy_launcher import LaunchError
from app.services.workflow_convert import ui_to_api

router = APIRouter()

_is_up = comfyui_client.is_up


@router.get("/")
def list_comfyui() -> dict[str, object]:
    return {"items": []}


class StartRequest(BaseModel):
    path: str          # ComfyUI 目录（含 main.py）
    url: str = COMFYUI_BASE_URL


@router.get("/status")
def status(url: str = COMFYUI_BASE_URL) -> dict[str, object]:
    return {"running": _is_up(url), "managed": comfy_launcher.is_managed()}


class ComfyConfig(BaseModel):
    path: str = ""
    url: str = COMFYUI_BASE_URL


@router.get("/config")
def get_config() -> ComfyConfig:
    """读 ComfyUI 路径/地址配置（供 start-dev 脚本等读取）。"""
    return ComfyConfig(**comfy_launcher.load_config())


@router.post("/config")
def set_config(cfg: ComfyConfig) -> ComfyConfig:
    """保存 ComfyUI 路径/地址，落盘到 data/comfy_config.json（ps1 脚本据此启动）。"""
    return ComfyConfig(**comfy_launcher.save_config(cfg.path, cfg.url))


@router.post("/start")
def start(req: StartRequest) -> dict[str, object]:
    try:
        return comfy_launcher.start(req.path, req.url)
    except LaunchError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)


@router.post("/stop")
def stop(req: StartRequest) -> dict[str, object]:
    """关闭 ComfyUI（装插件/依赖后需先关）。"""
    return comfy_launcher.stop(req.url)


@router.post("/restart")
def restart(req: StartRequest) -> dict[str, object]:
    """重启 ComfyUI：先关再起（装完插件生效）。需提供 path 以重新拉起。"""
    import time
    comfy_launcher.stop(req.url)
    time.sleep(1.5)  # 等端口/进程释放
    try:
        return comfy_launcher.start(req.path, req.url)
    except LaunchError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)


class SubmitRequest(BaseModel):
    template_id: str
    values: dict[str, object] = {}   # key = "node_id.field" -> 覆盖值
    prompt: str = ""                 # 可选：自动注入到模板 prompt_node_id 的文本字段（/g 用）
    url: str = COMFYUI_BASE_URL


@router.post("/submit")
def submit(req: SubmitRequest) -> dict[str, object]:
    """/s 启动：读模板原始工作流 → 转 API 格式 → 套用用户填的值 → 提交 /prompt。"""
    tpl = template_store.get_template(req.template_id)
    if tpl is None:
        raise HTTPException(status_code=400, detail="模板不存在")
    src = tpl.get("source_path", "")
    if not src or not Path(src).is_file():
        raise HTTPException(status_code=400, detail="模板缺少原始工作流文件，无法启动")
    if not _is_up(req.url):
        raise HTTPException(status_code=400, detail="ComfyUI 未运行，请先启动")

    try:
        workflow = json.loads(Path(src).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise HTTPException(status_code=400, detail=f"工作流 JSON 解析失败：{e}")

    api = ui_to_api(workflow, req.url)

    # 套用用户填写的值 + /g 自动注入提示词（纯变换，缺失必填输入 → 422）
    missing = workflow_injector.inject_template_values(
        api,
        tpl.get("exposed", []),
        req.values,
        req.prompt,
        str(tpl.get("prompt_node_id") or ""),
    )
    if missing:
        raise HTTPException(status_code=422, detail={"missing": missing})

    # 提交 /prompt
    try:
        prompt_id = comfyui_client.submit_prompt(req.url, api)
    except ComfyError as e:
        raise HTTPException(status_code=e.status, detail=f"提交失败：{e.detail}")
    return {"ok": True, "prompt_id": prompt_id, "node_count": len(api)}


class SubmitGraphRequest(BaseModel):
    workflow: dict[str, object]      # iframe 回传的完整工作流 JSON（含用户改过的 widget 值）
    url: str = COMFYUI_BASE_URL


@router.post("/submit_graph")
def submit_graph(req: SubmitGraphRequest) -> dict[str, object]:
    """从锁定画布回传的完整工作流直接转 API 并提交（用户在真实节点里改的值都在里面）。"""
    if not _is_up(req.url):
        raise HTTPException(status_code=400, detail="ComfyUI 未运行，请先启动")
    try:
        api = ui_to_api(req.workflow, req.url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"工作流转换失败：{e}")
    try:
        prompt_id = comfyui_client.submit_prompt(req.url, api)
    except ComfyError as e:
        # 落盘提交内容与错误，便于排查到底哪个节点/参数被拒
        try:
            dbg = Path(__file__).resolve().parent.parent.parent / "last_submit_error.json"
            dbg.write_text(
                json.dumps({"sent_prompt": api, "comfyui_error": e.detail}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass
        raise HTTPException(status_code=e.status, detail=f"ComfyUI 拒绝：{e.detail[:800]}")
    return {"ok": True, "prompt_id": prompt_id, "node_count": len(api)}


@router.post("/upload")
def upload_image(
    file: UploadFile = File(...),
    url: str = Form(COMFYUI_BASE_URL),
) -> dict[str, object]:
    """把图片转发上传到 ComfyUI 的 input 目录，返回其文件名（供 LoadImage 引用）。"""
    if not _is_up(url):
        raise HTTPException(status_code=400, detail="ComfyUI 未运行，无法上传图片")
    try:
        data = file.file.read()
        ref = comfyui_client.upload_image(url, file.filename, data, file.content_type or "image/png")
    except ComfyError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)
    return {"name": ref}


@router.get("/result")
def result(prompt_id: str, url: str = COMFYUI_BASE_URL) -> dict[str, object]:
    """轮询某次生成的状态与产出图片。返回 status 与 images（可直接用 /comfyui/view 取图）。"""
    try:
        return comfyui_client.fetch_result(url, prompt_id)
    except ComfyError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)


class FinalizeGenerationImage(BaseModel):
    filename: str
    subfolder: str = ""
    type: str = "output"


class FinalizeGenerationRequest(BaseModel):
    thread_id: str
    repo_id: str
    prompt_id: str
    prompt: str = ""
    images: list[FinalizeGenerationImage] = []
    output_dir: str = ""
    comfyui_url: str = COMFYUI_BASE_URL
    embed_base: str = ""
    embed_key: str = ""
    embed_model: str = "text-embedding-3-small"
    chat_base: str = ""
    chat_key: str = ""
    chat_model: str = ""


@router.post("/finalize-generation")
def finalize_generation(req: FinalizeGenerationRequest) -> dict[str, object]:
    """持久化一批已完成的工作流产出；查询结果的 GET 路由保持无副作用。"""
    try:
        return generation_store.finalize_workflow_batch(
            thread_id=req.thread_id,
            repo_id=req.repo_id,
            prompt_id=req.prompt_id,
            prompt=req.prompt,
            images=[image.model_dump() for image in req.images],
            output_dir=req.output_dir,
            comfyui_url=req.comfyui_url,
            embed_base=req.embed_base,
            embed_key=req.embed_key,
            embed_model=req.embed_model,
            chat_base=req.chat_base,
            chat_key=req.chat_key,
            chat_model=req.chat_model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class InterruptRequest(BaseModel):
    url: str = COMFYUI_BASE_URL
    prompt_id: str = ""            # 有则先从队列删除未执行项，再中断正在执行的


@router.post("/interrupt")
def interrupt(req: InterruptRequest) -> dict[str, object]:
    """强行停止 ComfyUI 生图（人工打断工作流用）。

    prompt_id 有值：先 POST /queue {"delete":[id]} 删掉排队中未执行项，
    再 POST /interrupt 中断正在执行的任务（覆盖排队/执行两种状态）。
    容错：ComfyUI 未起/已完成都不报错，返回 ok。
    """
    res = comfyui_client.interrupt(req.url, req.prompt_id)
    return {"ok": True, **res}


@router.get("/view")
def view(filename: str, type: str = "output", subfolder: str = "", url: str = COMFYUI_BASE_URL):
    """代理 ComfyUI 的 /view，返回图片二进制（避免前端跨域直连 8188）。"""
    from fastapi.responses import Response

    try:
        data, ctype = comfyui_client.fetch_view(url, filename, type, subfolder)
    except ComfyError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)
    return Response(content=data, media_type=ctype)


class SaveLocalRequest(BaseModel):
    filename: str = ""                   # ComfyUI 产物文件名（ComfyUI 模式）
    subfolder: str = ""
    type: str = "output"
    repo_id: str = "home"
    output_dir: str = ""                 # 设置里的输出图片路径
    url: str = COMFYUI_BASE_URL
    src: str = ""                        # 通用模式：完整图片 URL 或 data URI（云端生图用）
    subdir: str = ""                     # 落到 <repo>/<subdir>/ 子夹（用户上传参考图 → reference）


@router.post("/save-local")
def save_local(req: SaveLocalRequest) -> dict[str, object]:
    """把原图存到设置的 outputDir（全分辨率，不降质），返回本地访问 URL。

    两种来源：
    - ComfyUI 模式：给 filename，从 ComfyUI /view 取原图。
    - 通用模式：给 src（http(s) URL 或 data:image/...;base64,...），直接下载/解码（云端生图）。
    ComfyUI 未起/清理 output 后仍可显示与「再改进」，且不依赖在线。
    """
    try:
        path = image_store.save_local(
            req.output_dir,
            req.repo_id,
            src=req.src,
            filename=req.filename,
            subfolder=req.subfolder,
            type=req.type,
            url=req.url,
            subdir=req.subdir,
        )
    except ComfyError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)
    return {"ok": True, "path": path}


@router.get("/local-view")
def local_view(path: str):
    """读取已留存到 outputDir 的本地原图。"""
    from fastapi.responses import Response
    p = Path(path)
    if not p.is_file():
        raise HTTPException(status_code=404, detail="本地图片不存在")
    ext = p.suffix.lower().lstrip(".")
    ctype = f"image/{'jpeg' if ext in ('jpg','jpeg') else ext or 'png'}"
    return Response(content=p.read_bytes(), media_type=ctype)
