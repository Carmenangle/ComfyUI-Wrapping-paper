# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all


root = Path(os.environ["LAF_BUILD_ROOT"])
work_dir = Path(os.environ["LAF_BUILD_WORK_DIR"])
runtime_name = os.environ["LAF_BUILD_RUNTIME_NAME"]
icon = os.environ.get("LAF_BUILD_ICON") or None

datas = []
binaries = []
hiddenimports = ["app.main", *sorted(sys.stdlib_module_names)]
for module in ("chromadb", "langchain_chroma", "langgraph", "langchain_mcp_adapters"):
    module_datas, module_binaries, module_hidden = collect_all(module)
    datas += module_datas
    binaries += module_binaries
    hiddenimports += module_hidden

a = Analysis(
    [str(root / "scripts" / "runtime_entry.py")],
    pathex=[str(root / "backend")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "chromadb.test", "chromadb.server", "pytest",
        "sentence_transformers", "transformers", "torch",
    ],
    noarchive=False,
    optimize=0,
)

# Analysis 仍负责发现 app 使用的第三方依赖，但业务代码不进入 PYZ。
external_app_pure = [
    entry for entry in a.pure
    if entry[0] != "app" and not entry[0].startswith("app.")
]
pyz = PYZ(external_app_pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=runtime_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name=runtime_name,
)
