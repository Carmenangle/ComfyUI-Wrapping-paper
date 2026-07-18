import ipaddress
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.db import init_db
from app.routers import ai, ai_providers, agents, assets, characters, comfyui, loras, mcp, models, node_manager, rag, runs, skills, user_state, workflows

app = FastAPI(title="Local AI ComfyUI Frontend API")
init_db()

# 默认只服务本机：这是单机桌面壳，含无鉴权的进程控制/文件读写接口（start/stop/interrupt/
# save-local/local-view 等）。CORS 只挡浏览器跨源，挡不住非浏览器客户端；故加回环门禁作纵深防御。
# 确需局域网访问时，设环境变量 LAF_ALLOW_REMOTE=1 放开（自担风险）。
_ALLOW_REMOTE = os.environ.get("LAF_ALLOW_REMOTE", "") == "1"


@app.middleware("http")
async def _loopback_only(request: Request, call_next):
    if not _ALLOW_REMOTE:
        client = request.client.host if request.client else ""
        try:
            is_loopback = ipaddress.ip_address(client).is_loopback
        except ValueError:
            is_loopback = client in ("localhost", "")
        if not is_loopback:
            return JSONResponse(
                status_code=403,
                content={"detail": "仅允许本机访问（如需局域网访问请设 LAF_ALLOW_REMOTE=1）"},
            )
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(workflows.router, prefix="/api/workflows", tags=["workflows"])
app.include_router(runs.router, prefix="/api/runs", tags=["runs"])
app.include_router(ai.router, prefix="/api/ai", tags=["ai"])
app.include_router(ai_providers.router, prefix="/api/ai/providers", tags=["ai-providers"])
app.include_router(rag.router, prefix="/api/rag", tags=["rag"])
app.include_router(assets.router, prefix="/api/assets", tags=["assets"])
app.include_router(characters.router, prefix="/api/characters", tags=["characters"])
app.include_router(loras.router, prefix="/api/loras", tags=["loras"])
app.include_router(comfyui.router, prefix="/api/comfyui", tags=["comfyui"])
app.include_router(models.router, prefix="/api/models", tags=["models"])
app.include_router(node_manager.router, prefix="/api/node-manager", tags=["node-manager"])
app.include_router(user_state.router, prefix="/api/user-state", tags=["user-state"])
app.include_router(mcp.router, prefix="/api/mcp", tags=["mcp"])
app.include_router(skills.router, prefix="/api/skills", tags=["skills"])
app.include_router(agents.router, prefix="/api/agents", tags=["agents"])


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}