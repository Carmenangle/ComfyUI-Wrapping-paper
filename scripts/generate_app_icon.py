"""从 release/app-icon.png 生成多尺寸打包图标。

产物：
- release/app-icon.ico  —— Windows PyInstaller --icon 用（内嵌 16~256 多尺寸）
- release/app-icon.icns —— macOS PyInstaller --icon 用（若 Pillow 支持则生成）

Linux 无需图标文件（PyInstaller 忽略）。源图为 2048×2048 方图即可，
白底无透明也没关系。打包脚本调用 icon_for_target() 拿对应平台的图标路径。
"""
from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PNG = PROJECT_ROOT / "release" / "app-icon.png"
ICO_PATH = PROJECT_ROOT / "release" / "app-icon.ico"
ICNS_PATH = PROJECT_ROOT / "release" / "app-icon.icns"

# Windows .ico 内嵌尺寸：任务栏/资源管理器/开始菜单各取所需
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]


def generate(source: Path = SOURCE_PNG) -> list[Path]:
    """生成 .ico（+ 尽力生成 .icns），返回已生成的文件列表。"""
    from PIL import Image

    if not source.is_file():
        raise FileNotFoundError(f"找不到图标源图：{source}")
    img = Image.open(source).convert("RGBA")
    # 非正方形先居中裁成正方形，避免 ico 拉伸变形
    if img.width != img.height:
        side = min(img.width, img.height)
        left = (img.width - side) // 2
        top = (img.height - side) // 2
        img = img.crop((left, top, left + side, top + side))

    generated: list[Path] = []
    img.save(ICO_PATH, format="ICO", sizes=[(s, s) for s in ICO_SIZES])
    generated.append(ICO_PATH)

    # .icns 供 macOS；老版本 Pillow 可能不支持，失败则跳过（mac 打包时再补）
    try:
        icns_src = img.resize((1024, 1024), Image.LANCZOS)
        icns_src.save(ICNS_PATH, format="ICNS")
        generated.append(ICNS_PATH)
    except Exception as exc:  # noqa: BLE001
        print(f"跳过 .icns 生成（{exc}）")
    return generated


def icon_for_os(target_os: str) -> Path | None:
    """按目标平台返回应传给 PyInstaller --icon 的图标路径；无则 None。

    Windows→.ico，macOS→.icns，Linux→无。文件不存在时返回 None，
    让打包脚本在无图标时也能继续。"""
    if target_os == "windows":
        return ICO_PATH if ICO_PATH.is_file() else None
    if target_os == "macos":
        return ICNS_PATH if ICNS_PATH.is_file() else None
    return None


def main() -> None:
    for path in generate():
        print(f"已生成：{path}")


if __name__ == "__main__":
    main()
