"""图像智能体端点：SSE 流式生成 + 后台运行状态 + 打断。
生成跑在后台线程（agent_runner），与 HTTP 连接解耦。
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.routers.ai_common import EmbedModelReq
from app.services.sse import sse_response

router = APIRouter()


class ImageAgentRequest(EmbedModelReq):
    thread_id: str = "home"            # 对话线 = 仓库 id
    message: str = ""                  # 本轮用户输入
    images: list[str] = []             # 随文图片（data URI 或 URL）
    gen_base_url: str = ""             # 生图模型（imageModels）
    gen_api_key: str = ""
    gen_model: str = ""
    size: str = "1024x1024"            # 生图尺寸（前端比例+分辨率档算好的 宽x高）
    output_dir: str = ""               # 输出图片路径（后端落盘留存云图）
    repo_id: str = ""                  # 留存/入库归属仓库（空则用 thread_id）
    message_id: str = ""               # 前端 botId：最终文本按此 id 落盘去重
    proxy_url: str = ""                # 联网搜索代理（search_inspiration 工具用）
    style: str = ""                    # 用户手动选的提示词风格 sd/gpt/banana/""(自动)
    style_template: str = ""           # 自定义风格存档的整段内容（非空时优先于 style）
    agent_id: str = ""                 # 多 Agent：选中的 Agent 预设 id（空=内置默认行为）


# 单 agent 生成入口（POST /ai/image-agent → agent_runner.run_stream）已下线。
# 其 ReAct 大脑降级为多 Agent 的 tool_agent 专家节点（承接 MCP/工具串联），自由文本一律走 /multi-agent。
# 下方 /image-agent/running 与 /image-agent/cancel 保留：后台化的共用机制，多 Agent 同用同一 thread 计数/取消信号。


class MultiAgentRequest(ImageAgentRequest):
    route_model: str = ""   # supervisor 判分派用的（快）模型，空则用主对话模型


@router.post("/multi-agent")
def multi_agent(req: MultiAgentRequest) -> StreamingResponse:
    """Supervisor 多 Agent（LangGraph）：主管判意图→分派生图/图生图/反推/灵感专家。SSE 流式，
    透出节点流转({trace})供前端展示协作过程。生成同样跑在 agent_runner 后台线程里。"""
    from app.services import agent_runner
    from app.services.agent_contracts import ModelConfig, RunContext

    if not req.message.strip() and not req.images:
        raise HTTPException(status_code=400, detail="内容为空")

    context = RunContext(
        thread_id=req.thread_id,
        message=req.message,
        images=req.images or [],
        chat=ModelConfig(req.base_url, req.api_key, req.model),
        generation=ModelConfig(req.gen_base_url, req.gen_api_key, req.gen_model),
        embedding=ModelConfig(req.embed_base_url, req.embed_api_key, req.embed_model),
        size=req.size,
        output_dir=req.output_dir,
        repo_id=req.repo_id or req.thread_id,
        message_id=req.message_id,
        proxy_url=req.proxy_url,
        route_model=req.route_model,
        style_template=req.style_template,
        agent_id=req.agent_id,
    )
    try:
        q = agent_runner.run_multi_stream(context)
    except agent_runner.RunAlreadyActive as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return sse_response(lambda: agent_runner.drain(q))


@router.get("/image-agent/running")
def image_agent_running(thread_id: str = "home") -> dict[str, object]:
    """该 thread 是否有后台生成任务在跑。前端切回/刷新时据此轮询快照等落盘。"""
    from app.services import agent_runner
    return {"running": agent_runner.is_running(thread_id)}


class CancelRequest(BaseModel):
    thread_id: str = "home"


@router.post("/image-agent/cancel")
def image_agent_cancel(req: CancelRequest) -> dict[str, object]:
    """打断该 thread 的后台生成：协作式取消，半成品文本落盘并补进记忆供下一轮续写=合并。"""
    from app.services import agent_runner
    running = agent_runner.cancel(req.thread_id)
    return {"ok": True, "running": running}
