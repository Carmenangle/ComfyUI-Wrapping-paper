from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw


AVATARS = {
    "bright默认.png": "hostess-main.png",
    "bright聆听.png": "hostess-listening.png",
    "bright思考.png": "hostess-thinking.png",
    "bright完成.png": "hostess-success.png",
}


def resize_alpha(image: Image.Image, size: int) -> Image.Image:
    premultiplied = image.convert("RGBA").convert("RGBa")
    return premultiplied.resize((size, size), Image.Resampling.LANCZOS).convert("RGBA")


def checkerboard(size: int, cell: int = 24) -> Image.Image:
    image = Image.new("RGBA", (size, size), "#F8F7FA")
    draw = ImageDraw.Draw(image)
    for y in range(0, size, cell):
        for x in range(0, size, cell):
            if (x // cell + y // cell) % 2:
                draw.rectangle((x, y, x + cell - 1, y + cell - 1), fill="#4B4553")
    return image


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--preview", type=Path, required=True)
    args = parser.parse_args()

    previews: list[Image.Image] = []
    for source_name, output_name in AVATARS.items():
        source = Image.open(args.source_dir / source_name).convert("RGBA")
        if source.getchannel("A").getextrema() != (0, 255):
            raise ValueError(f"{source_name} does not contain usable transparency")
        for size in (1024, 168, 112):
            target_dir = args.output_dir if size == 1024 else args.output_dir / str(size)
            target_dir.mkdir(parents=True, exist_ok=True)
            resize_alpha(source, size).save(
                target_dir / output_name, format="PNG", optimize=True, compress_level=9
            )
        tile = checkerboard(384)
        tile.alpha_composite(resize_alpha(source, 384))
        previews.append(tile.convert("RGB"))

    preview = Image.new("RGB", (768, 768), "white")
    for index, tile in enumerate(previews):
        preview.paste(tile, ((index % 2) * 384, (index // 2) * 384))
    args.preview.parent.mkdir(parents=True, exist_ok=True)
    preview.save(args.preview, format="PNG", optimize=True)


if __name__ == "__main__":
    main()
