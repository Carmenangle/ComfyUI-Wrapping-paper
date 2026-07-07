from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import init_db
from app.routers import ai, ai_providers, assets, characters, comfyui, loras, models, node_manager, rag, runs, workflows

app = FastAPI(title="Local AI ComfyUI Frontend API")
init_db()

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


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}