from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps


BASE_ASSETS = (
    (
        "bright日光校准工作室对话背景.png",
        "backgrounds/bright/chat-daylight-calibration-studio.webp",
    ),
    (
        "bright极简斜裁工作台对话背景.png",
        "backgrounds/bright/chat-diagonal-workbench.webp",
    ),
)


def resize_alpha(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    return image.convert("RGBA").convert("RGBa").resize(size, Image.Resampling.LANCZOS).convert("RGBA")


def clean_alpha(image: Image.Image, threshold: int = 16) -> Image.Image:
    rgba = np.asarray(image.convert("RGBA")).copy()
    rgba[rgba[:, :, 3] < threshold] = 0
    return Image.fromarray(rgba, "RGBA")


def crop_visible(image: Image.Image, padding: int = 4) -> Image.Image:
    image = clean_alpha(image)
    bbox = image.getchannel("A").getbbox()
    if bbox is None:
        raise ValueError("Crop does not contain visible pixels")
    left = max(0, bbox[0] - padding)
    top = max(0, bbox[1] - padding)
    right = min(image.width, bbox[2] + padding)
    bottom = min(image.height, bbox[3] + padding)
    return image.crop((left, top, right, bottom))


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


def mirrored_tile(image: Image.Image) -> Image.Image:
    tile = image.convert("RGB").resize((512, 512), Image.Resampling.LANCZOS)
    output = Image.new("RGB", (1024, 1024))
    output.paste(tile, (0, 0))
    output.paste(ImageOps.mirror(tile), (512, 0))
    output.paste(ImageOps.flip(tile), (0, 512))
    output.paste(ImageOps.flip(ImageOps.mirror(tile)), (512, 512))
    return output


def process_base_assets(source_dir: Path, output_dir: Path) -> None:
    texture_sources = (
        ("bright瓷白斜纹无缝纹理.png", "textures/bright/porcelain-twill-tile.webp"),
        ("bright石墨弹力织物无缝纹理.png", "textures/bright/graphite-stretch-twill-tile.webp"),
    )
    for source_name, relative_output in texture_sources:
        target = output_dir / relative_output
        target.parent.mkdir(parents=True, exist_ok=True)
        mirrored_tile(Image.open(source_dir / source_name)).save(
            target, format="WEBP", lossless=True, method=6
        )

    for source_name, relative_output in BASE_ASSETS:
        image = ImageOps.fit(
            Image.open(source_dir / source_name).convert("RGB"),
            (3840, 2160),
            method=Image.Resampling.LANCZOS,
        )
        target = output_dir / relative_output
        target.parent.mkdir(parents=True, exist_ok=True)
        image.save(target, format="WEBP", quality=90, method=6)


def process_stitch_strip(source_dir: Path, output_dir: Path) -> None:
    source = clean_alpha(Image.open(source_dir / "bright蓝紫双针压线条.png"))
    strip = crop_visible(source.crop((0, 360, source.width, 660)), padding=0)
    strip = resize_alpha(strip, (1536, 192))
    target = output_dir / "textures/bright/double-stitch-strip.webp"
    target.parent.mkdir(parents=True, exist_ok=True)
    strip.save(target, format="WEBP", lossless=True, method=6)


def process_cut_corners(source_dir: Path, output_dir: Path) -> None:
    source = clean_alpha(Image.open(source_dir / "bright不对称切角图集.png"))
    save_png(resize_alpha(source, (2048, 2048)), output_dir / "ornaments/bright/cut-corners.png")
    regions = {
        "cut-corner-porcelain.png": (240, 120, 620, 410),
        "cut-corner-graphite.png": (780, 120, 1140, 410),
        "cut-corner-node.png": (240, 565, 620, 885),
        "cut-corner-silver.png": (780, 565, 1140, 885),
    }
    for name, box in regions.items():
        save_png(crop_visible(source.crop(box)), output_dir / "ornaments/bright" / name)


def process_dividers(source_dir: Path, output_dir: Path) -> None:
    source = clean_alpha(Image.open(source_dir / "bright分隔线与状态节点图集.png"))
    line_boxes = (
        (20, 130, 1450, 160),
        (20, 245, 1450, 300),
        (20, 375, 1450, 425),
        (20, 490, 1450, 550),
        (20, 620, 1450, 675),
    )
    line_names = ("single", "double", "node", "graphite", "porcelain")
    lines = [crop_visible(source.crop(box)) for box in line_boxes]
    for name, image in zip(line_names, lines):
        save_png(image, output_dir / f"ornaments/bright/divider-{name}.png")

    node_boxes = (
        (330, 770, 460, 885),
        (500, 770, 635, 885),
        (680, 770, 815, 885),
        (850, 770, 985, 885),
        (1025, 770, 1160, 885),
    )
    node_names = ("default", "active", "success", "warning", "error")
    nodes = [crop_visible(source.crop(box)) for box in node_boxes]
    for name, image in zip(node_names, nodes):
        save_png(image, output_dir / f"ornaments/bright/node-{name}.png")

    atlas = Image.new("RGBA", (2048, 1024), (0, 0, 0, 0))
    for index, image in enumerate(lines):
        place_center(atlas, image, (50, 24 + index * 130, 1998, 124 + index * 130))
    for index, image in enumerate(nodes):
        place_center(atlas, image, (460 + index * 230, 770, 600 + index * 230, 960))
    save_png(atlas, output_dir / "ornaments/bright/dividers-and-nodes.png")


def edge_overlay(image: Image.Image) -> Image.Image:
    image = crop_visible(image, padding=2)
    rgba = np.asarray(image).copy()
    if image.width <= 80 or image.height <= 36:
        raise ValueError("Button crop is too small for the shared border-image slices")
    rgba[18:-18, 40:-40, 3] = 0
    rgba[rgba[:, :, 3] == 0, :3] = 0
    return Image.fromarray(rgba, "RGBA")


def process_buttons(source_dir: Path, output_dir: Path) -> None:
    source = clean_alpha(Image.open(source_dir / "bright按钮状态纹理图集.png"))
    row_boxes = ((18, 18, 438, 145), (18, 185, 438, 320), (18, 355, 438, 487), (18, 525, 438, 657))
    secondary_boxes = tuple((486, top, 906, bottom) for _, top, _, bottom in row_boxes)
    states = ("default", "hover", "pressed", "disabled")
    main = [edge_overlay(source.crop(box)) for box in row_boxes]
    secondary = [edge_overlay(source.crop(box)) for box in secondary_boxes]
    for state, image in zip(states, main):
        save_png(image, output_dir / f"controls/bright/button-main-{state}.png")
    for state, image in zip(states, secondary):
        save_png(image, output_dir / f"controls/bright/button-secondary-{state}.png")

    atlas = Image.new("RGBA", (2048, 1024), (0, 0, 0, 0))
    for column, image in enumerate(main):
        place_center(atlas, image, (column * 512 + 16, 32, (column + 1) * 512 - 16, 480))
    for column, image in enumerate(secondary):
        place_center(atlas, image, (column * 512 + 16, 544, (column + 1) * 512 - 16, 992))
    save_png(atlas, output_dir / "controls/bright/button-state-overlays.png")


def process_messages(source_dir: Path, output_dir: Path) -> None:
    source = clean_alpha(Image.open(source_dir / "bright消息气泡纹理图集.png"))
    boxes = ((125, 40, 900, 440), (125, 490, 900, 920), (125, 980, 900, 1450))
    names = ("assistant", "user", "system")
    panels = [crop_visible(source.crop(box), padding=2) for box in boxes]
    for name, image in zip(names, panels):
        save_png(image, output_dir / f"controls/bright/message-{name}.png")

    atlas = Image.new("RGBA", (2048, 1024), (0, 0, 0, 0))
    for index, image in enumerate(panels):
        place_center(atlas, image, (index * 682 + 24, 38, (index + 1) * 682 - 24, 986))
    save_png(atlas, output_dir / "controls/bright/message-surface-overlays.png")


def process_composer(source_dir: Path, output_dir: Path) -> None:
    source = clean_alpha(Image.open(source_dir / "bright输入区与拖动手柄边饰.png"))
    top = crop_visible(source.crop((45, 155, 995, 210)))
    handle = crop_visible(source.crop((285, 400, 745, 490)))
    divider = crop_visible(source.crop((50, 675, 980, 740)))
    items = {"composer-top.png": top, "composer-handle.png": handle, "composer-divider.png": divider}
    for name, image in items.items():
        save_png(image, output_dir / "controls/bright" / name)

    atlas = Image.new("RGBA", (2048, 512), (0, 0, 0, 0))
    place_center(atlas, top, (70, 20, 1978, 150))
    place_center(atlas, handle, (760, 170, 1288, 330))
    place_center(atlas, divider, (70, 350, 1978, 492))
    save_png(atlas, output_dir / "controls/bright/composer-ornaments.png")


def process_empty_state(source_dir: Path, output_dir: Path) -> None:
    source = clean_alpha(Image.open(source_dir / "bright空状态校准徽记.png"))
    save_png(resize_alpha(source, (1024, 1024)), output_dir / "ornaments/bright/empty-state-calibrator.png")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    process_base_assets(args.source_dir, args.output_dir)
    process_stitch_strip(args.source_dir, args.output_dir)
    process_cut_corners(args.source_dir, args.output_dir)
    process_dividers(args.source_dir, args.output_dir)
    process_buttons(args.source_dir, args.output_dir)
    process_messages(args.source_dir, args.output_dir)
    process_composer(args.source_dir, args.output_dir)
    process_empty_state(args.source_dir, args.output_dir)


if __name__ == "__main__":
    main()
