from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image


BASE_ASSETS = (
    ("象牙纸面无缝纹理.png", "textures/eye-care/ivory-paper-tile.webp", (1024, 1024), True),
    ("鼠尾草斜纹无缝纹理.png", "textures/eye-care/sage-twill-tile.webp", (1024, 1024), True),
    ("文学学院对话背景.png", "backgrounds/eye-care/chat-literature-study.webp", (3840, 2160), False),
    ("极简刺绣对话背景.png", "backgrounds/eye-care/chat-embroidery-paper.webp", (3840, 2160), False),
)


def resize_alpha(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    return image.convert("RGBA").convert("RGBa").resize(size, Image.Resampling.LANCZOS).convert("RGBA")


def white_to_alpha(image: Image.Image, transparent_at: int = 10, opaque_at: int = 48) -> Image.Image:
    rgba = np.asarray(image.convert("RGBA")).copy()
    distance = 255 - rgba[:, :, :3].min(axis=2).astype(np.int16)
    matte = np.clip((distance - transparent_at) * 255 / (opaque_at - transparent_at), 0, 255)
    rgba[:, :, 3] = np.minimum(rgba[:, :, 3], matte.astype(np.uint8))
    rgba[rgba[:, :, 3] == 0, :3] = 0
    return Image.fromarray(rgba, "RGBA")


def remove_low_alpha_haze(image: Image.Image, threshold: int = 112) -> Image.Image:
    rgba = np.asarray(image.convert("RGBA")).copy()
    rgba[rgba[:, :, 3] < threshold] = 0
    return Image.fromarray(rgba, "RGBA")


def crop_region(image: Image.Image, box: tuple[int, int, int, int], padding: int = 6) -> Image.Image:
    region = image.crop(box).convert("RGBA")
    bbox = region.getchannel("A").getbbox()
    if bbox is None:
        raise ValueError(f"No visible pixels in crop {box}")
    left = max(0, bbox[0] - padding)
    top = max(0, bbox[1] - padding)
    right = min(region.width, bbox[2] + padding)
    bottom = min(region.height, bbox[3] + padding)
    return region.crop((left, top, right, bottom))


def save_png(image: Image.Image, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, format="PNG", optimize=True, compress_level=9)


def contain(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    ratio = min(size[0] / image.width, size[1] / image.height)
    return resize_alpha(image, (max(1, round(image.width * ratio)), max(1, round(image.height * ratio))))


def place_center(canvas: Image.Image, image: Image.Image, box: tuple[int, int, int, int]) -> None:
    fitted = contain(image, (box[2] - box[0], box[3] - box[1]))
    x = box[0] + (box[2] - box[0] - fitted.width) // 2
    y = box[1] + (box[3] - box[1] - fitted.height) // 2
    canvas.alpha_composite(fitted, (x, y))


def process_base_assets(source_dir: Path, output_dir: Path) -> None:
    for source_name, relative_output, size, lossless in BASE_ASSETS:
        image = Image.open(source_dir / source_name).convert("RGB")
        if image.size != size:
            image = image.resize(size, Image.Resampling.LANCZOS)
        target = output_dir / relative_output
        target.parent.mkdir(parents=True, exist_ok=True)
        image.save(target, format="WEBP", lossless=lossless, quality=90, method=6)


def process_leather(source_dir: Path, output_dir: Path) -> None:
    image = Image.open(source_dir / "深茶皮革压线条.png").convert("RGB")
    pixels = np.asarray(image)
    row_distance = (255 - pixels.mean(axis=2)).mean(axis=1)
    rows = np.flatnonzero(row_distance > 10)
    center = round((int(rows[0]) + int(rows[-1])) / 2)
    crop_height = round(image.width / 8)
    top = max(0, min(image.height - crop_height, center - crop_height // 2))
    strip = image.crop((0, top, image.width, top + crop_height)).resize((1536, 192), Image.Resampling.LANCZOS)
    target = output_dir / "textures/eye-care/leather-stitch-strip.webp"
    target.parent.mkdir(parents=True, exist_ok=True)
    strip.save(target, format="WEBP", quality=92, method=6)


def process_gold_corners(source_dir: Path, output_dir: Path) -> None:
    source = Image.open(source_dir / "古金角饰图集.png").convert("RGBA")
    save_png(resize_alpha(source, (2048, 2048)), output_dir / "ornaments/eye-care/gold-corners.png")
    regions = {
        "gold-corner-vine.png": (90, 60, 590, 510),
        "gold-corner-lace.png": (620, 60, 1165, 510),
        "gold-corner-gem.png": (90, 500, 590, 990),
        "gold-corner-double.png": (620, 500, 1165, 990),
        "gold-endpoint-leaf.png": (90, 1010, 590, 1185),
        "gold-endpoint-diamond.png": (620, 1010, 1165, 1185),
    }
    for name, box in regions.items():
        save_png(crop_region(source, box), output_dir / "ornaments/eye-care" / name)


def process_dividers(source_dir: Path, output_dir: Path) -> None:
    source = white_to_alpha(Image.open(source_dir / "分隔线与状态节点图集.png"))
    line_boxes = (
        (65, 65, 1605, 150),
        (65, 185, 1605, 275),
        (65, 305, 1605, 405),
        (65, 425, 1605, 520),
        (65, 535, 1605, 630),
        (65, 650, 1605, 745),
    )
    line_names = ("single", "double", "gem", "leaves", "leather", "lace")
    lines = [crop_region(source, box) for box in line_boxes]
    for name, image in zip(line_names, lines):
        save_png(image, output_dir / f"ornaments/eye-care/divider-{name}.png")

    node_boxes = (
        (430, 765, 555, 900),
        (660, 765, 785, 900),
        (890, 765, 1015, 900),
        (1120, 765, 1245, 900),
    )
    node_names = ("default", "active", "success", "warning")
    nodes = [crop_region(source, box) for box in node_boxes]
    for name, image in zip(node_names, nodes):
        save_png(image, output_dir / f"ornaments/eye-care/node-{name}.png")

    atlas = Image.new("RGBA", (2048, 1024), (0, 0, 0, 0))
    for index, image in enumerate(lines):
        place_center(atlas, image, (60, 30 + index * 125, 1988, 135 + index * 125))
    for index, image in enumerate(nodes):
        place_center(atlas, image, (570 + index * 230, 800, 710 + index * 230, 960))
    save_png(atlas, output_dir / "ornaments/eye-care/dividers-and-nodes.png")


def button_surface(image: Image.Image) -> Image.Image:
    surface = image.convert("RGBA")
    center = surface.getpixel((surface.width // 2, surface.height // 2))
    if center[3] < 250 or min(center[:3]) < 230:
        raise ValueError("Button surface center must remain opaque and near-white")
    return surface


def process_buttons(source_dir: Path, output_dir: Path) -> None:
    source = Image.open(source_dir / "按钮状态纹理图集.png").convert("RGBA")
    rows = ((20, 105, 610, 335), (20, 370, 610, 610), (20, 640, 610, 885), (20, 915, 610, 1160))
    secondary_rows = tuple((635, top, 1235, bottom) for _, top, _, bottom in rows)
    states = ("default", "hover", "pressed", "disabled")
    main = [button_surface(crop_region(source, box, padding=2)) for box in rows]
    secondary = [button_surface(crop_region(source, box, padding=2)) for box in secondary_rows]
    for state, image in zip(states, main):
        save_png(image, output_dir / f"controls/eye-care/button-main-{state}.png")
    for state, image in zip(states, secondary):
        save_png(image, output_dir / f"controls/eye-care/button-secondary-{state}.png")

    atlas = Image.new("RGBA", (2048, 1024), (0, 0, 0, 0))
    for column, image in enumerate(main):
        place_center(atlas, image, (column * 512 + 16, 32, (column + 1) * 512 - 16, 480))
    for column, image in enumerate(secondary):
        place_center(atlas, image, (column * 512 + 16, 544, (column + 1) * 512 - 16, 992))
    save_png(atlas, output_dir / "controls/eye-care/button-state-overlays.png")


def process_messages(source_dir: Path, output_dir: Path) -> None:
    source = Image.open(source_dir / "消息气泡纹理图集.png").convert("RGBA")
    boxes = ((55, 55, 770, 665), (55, 655, 770, 1270), (55, 1260, 770, 1880))
    names = ("assistant", "user", "system")
    panels = [crop_region(source, box, padding=2) for box in boxes]
    for name, image in zip(names, panels):
        save_png(image, output_dir / f"controls/eye-care/message-{name}.png")
    atlas = Image.new("RGBA", (2048, 1024), (0, 0, 0, 0))
    for index, image in enumerate(panels):
        place_center(atlas, image, (index * 682 + 24, 38, (index + 1) * 682 - 24, 986))
    save_png(atlas, output_dir / "controls/eye-care/message-surface-overlays.png")


def process_composer(source_dir: Path, output_dir: Path) -> None:
    source_path = source_dir / "输入区与拖动手柄边饰.png"
    if not source_path.exists():
        source_path = source_dir / "输入区与拖动手柄边饰1.png"
    source = white_to_alpha(Image.open(source_path))
    top = crop_region(source, (35, 410, 855, 535))
    handle = crop_region(source, (285, 760, 610, 920))
    divider = crop_region(source, (35, 1090, 855, 1250))
    items = {"composer-top.png": top, "composer-handle.png": handle, "composer-divider.png": divider}
    for name, image in items.items():
        save_png(image, output_dir / "controls/eye-care" / name)
    atlas = Image.new("RGBA", (2048, 512), (0, 0, 0, 0))
    place_center(atlas, top, (70, 20, 1978, 150))
    place_center(atlas, handle, (760, 170, 1288, 330))
    place_center(atlas, divider, (70, 350, 1978, 492))
    save_png(atlas, output_dir / "controls/eye-care/composer-ornaments.png")


def process_empty_state(source_dir: Path, output_dir: Path) -> None:
    source = remove_low_alpha_haze(Image.open(source_dir / "eye-care空状态徽记.png"))
    save_png(resize_alpha(source, (1024, 1024)), output_dir / "ornaments/eye-care/empty-state-crest.png")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    process_base_assets(args.source_dir, args.output_dir)
    process_leather(args.source_dir, args.output_dir)
    process_gold_corners(args.source_dir, args.output_dir)
    process_dividers(args.source_dir, args.output_dir)
    process_buttons(args.source_dir, args.output_dir)
    process_messages(args.source_dir, args.output_dir)
    process_composer(args.source_dir, args.output_dir)
    process_empty_state(args.source_dir, args.output_dir)


if __name__ == "__main__":
    main()
