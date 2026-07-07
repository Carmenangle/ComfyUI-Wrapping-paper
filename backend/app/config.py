from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
WORKFLOWS_DIR = DATA_DIR / "workflows"
TEMPLATES_DIR = DATA_DIR / "templates"
ASSETS_DIR = DATA_DIR / "assets"
THUMBS_DIR = DATA_DIR / "thumbs"
DB_PATH = DATA_DIR / "app.db"
CHECKPOINT_DB = DATA_DIR / "checkpoints.db"   # LangGraph 对话多轮记忆（SqliteSaver）
CHROMA_DIR = DATA_DIR / "chroma"              # 仓库 RAG 知识库（Chroma 本地持久化）

# ComfyUI 锁定扩展目录（custom_nodes 形式，靠 extra_model_paths 外挂，不改 ComfyUI 本体）
COMFY_EXT_DIR = BASE_DIR.parent / "comfyui-ext"

COMFYUI_BASE_URL = "http://127.0.0.1:8188"
COMFYUI_INPUT_DIR = Path(r"D:\tool\ComfyUI\input")
COMFYUI_OUTPUT_DIR = Path(r"D:\tool\ComfyUI\output")