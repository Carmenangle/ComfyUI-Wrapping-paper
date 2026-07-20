"""固定 Runtime 的单一启动入口。"""
from __future__ import annotations

import os
import importlib
import json
import sys
import threading
import webbrowser
from pathlib import Path


def runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def configure_environment(root: Path) -> None:
    edition = os.environ.get("LAF_RUNTIME_EDITION", "standard")
    os.environ.update({
        "LAF_RUNTIME_ROOT": str(root),
        "LAF_DATA_DIR": str(root / "data"),
        "LAF_FRONTEND_DIST": str(root / "frontend"),
        "LAF_COMFY_EXT_DIR": str(root / "comfyui-ext"),
    })
    bundled = root / "models" / "reranker" / "Qwen3-Reranker-0.6B"
    if edition == "full-rag" or bundled.is_dir():
        os.environ["LAF_RUNTIME_EDITION"] = "full-rag"
        os.environ["LAF_BUNDLED_RERANKER_DIR"] = str(bundled)
    (root / "data").mkdir(parents=True, exist_ok=True)


def self_check() -> None:
    modules = [
        "app.main", "chromadb", "langchain_chroma", "langgraph",
        "langchain_mcp_adapters",
    ]
    if os.environ.get("LAF_RUNTIME_EDITION") == "full-rag":
        modules.extend(("torch", "transformers", "sentence_transformers"))
    for module in modules:
        importlib.import_module(module)
    print(json.dumps({"status": "ok", "modules": modules}))


def main() -> None:
    root = runtime_root()
    configure_environment(root)
    if os.environ.get("LAF_RUNTIME_SELF_TEST", "") == "1":
        self_check()
        return
    if os.environ.get("LAF_NO_BROWSER", "") != "1":
        threading.Timer(1.2, lambda: webbrowser.open("http://127.0.0.1:8010")).start()
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8010, log_level="info")


if __name__ == "__main__":
    main()
