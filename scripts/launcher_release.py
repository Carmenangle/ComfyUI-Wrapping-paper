"""把 scripts/launcher.py 用 PyInstaller 打成独立启动器 .exe。

启动器与主 Runtime 分开构建，托盘功能依赖 pystray 和 Pillow。

用法：
  python scripts/launcher_release.py build --output-dir release-assets
"""
from __future__ import annotations

import argparse
import platform
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_SRC = PROJECT_ROOT / "scripts" / "launcher.py"
CONFIG_SRC = PROJECT_ROOT / "release" / "launcher-config.json"
ICON_SRC = PROJECT_ROOT / "release" / "app-icon.ico"
ICON_PNG_SRC = PROJECT_ROOT / "release" / "app-icon.png"
APP_NAME = "ComfyUI-Wrapping-paper"


def _icon_args() -> list[str]:
    """给启动器 exe 加封面图标（缺图或非 Windows/mac 时静默跳过）。"""
    from generate_app_icon import generate, icon_for_os

    target_os = "windows" if platform.system() == "Windows" else (
        "macos" if platform.system() == "Darwin" else "linux"
    )
    icon = icon_for_os(target_os)
    if icon is None and target_os in ("windows", "macos"):
        try:
            generate()               # .ico/.icns 还没生成过就现生成
            icon = icon_for_os(target_os)
        except Exception as exc:     # noqa: BLE001
            print(f"跳过图标（{exc}）")
    return ["--icon", str(icon)] if icon else []


def build(output_dir: Path, work_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onefile",           # 单文件 exe
        "--windowed",          # 无控制台窗口（GUI 程序）
        "--hidden-import", "pystray._win32",
        "--add-data", f"{ICON_SRC}:.",
        "--add-data", f"{ICON_PNG_SRC}:.",
        "--exclude-module", "numpy",
        "--exclude-module", "pystray._appindicator",
        "--exclude-module", "pystray._gtk",
        "--exclude-module", "pystray._xorg",
        "--exclude-module", "pystray._darwin",
        "--name", APP_NAME,
        *_icon_args(),
        "--distpath", str(output_dir),
        "--workpath", str(work_dir / "build"),
        "--specpath", str(work_dir),
        str(LAUNCHER_SRC),
    ]
    subprocess.run(cmd, check=True, cwd=str(PROJECT_ROOT))

    # 把默认配置复制到输出目录（用户可编辑）
    exe_suffix = ".exe" if platform.system() == "Windows" else ""
    exe = output_dir / f"{APP_NAME}{exe_suffix}"
    output_config = output_dir / "launcher-config.json"
    if CONFIG_SRC.exists() and not output_config.exists():
        output_config.write_text(
            CONFIG_SRC.read_text(encoding="utf-8"), encoding="utf-8"
        )
    return exe


def main() -> None:
    parser = argparse.ArgumentParser(description="构建终端用户启动器")
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="用 PyInstaller 打包启动器")
    b.add_argument("--output-dir", default="release-assets", type=Path)
    b.add_argument("--work-dir", default=".launcher-work", type=Path)
    args = parser.parse_args()

    if args.cmd == "build":
        exe = build(args.output_dir, args.work_dir)
        print(f"启动器已生成：{exe}")


if __name__ == "__main__":
    main()
