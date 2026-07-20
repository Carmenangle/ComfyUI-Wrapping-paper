from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps


def resize_alpha(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    return image.convert("RGBA").convert("RGBa").resize(
        size, Image.Resampling.LANCZOS,
    ).convert("RGBA")


def clean_alpha(image: Image.Image, threshold: int = 16) -> Image.Image:
    rgba = np.asarray(image.convert("RGBA")).copy()
    rgba[rgba[:, :, 3] < threshold] = 0
    return Image.fromarray(rgba, "RGBA")


def white_to_alpha(
    image: Image.Image,
    transparent_at: int = 10,
    opaque_at: int = 48,
) -> Image.Image:
    rgba = np.asarray(image.convert("RGBA")).copy()
    distance = 255 - rgba[:, :, :3].min(axis=2).astype(np.int16)
    matte = np.clip(
        (distance - transparent_at) * 255 / (opaque_at - transparent_at), 0, 255,
    )
    rgba[:, :, 3] = np.minimum(rgba[:, :, 3], matte.astype(np.uint8))
    rgba[rgba[:, :, 3] == 0, :3] = 0
    return Image.fromarray(rgba, "RGBA")


def remove_low_alpha_haze(image: Image.Image, threshold: int = 112) -> Image.Image:
    rgba = np.asarray(image.convert("RGBA")).copy()
    rgba[rgba[:, :, 3] < threshold] = 0
    return Image.fromarray(rgba, "RGBA")


def crop_visible(image: Image.Image, padding: int = 4) -> Image.Image:
    bbox = image.getchannel("A").getbbox()
    if bbox is None:
        raise ValueError("Crop does not contain visible pixels")
    left = max(0, bbox[0] - padding)
    top = max(0, bbox[1] - padding)
    right = min(image.width, bbox[2] + padding)
    bottom = min(image.height, bbox[3] + padding)
    return image.crop((left, top, right, bottom))


def contain(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    ratio = min(size[0] / image.width, size[1] / image.height)
    return resize_alpha(
        image,
        (max(1, round(image.width * ratio)), max(1, round(image.height * ratio))),
    )


def place_center(
    canvas: Image.Image,
    image: Image.Image,
    box: tuple[int, int, int, int],
) -> None:
    fitted = contain(image, (box[2] - box[0], box[3] - box[1]))
    x = box[0] + (box[2] - box[0] - fitted.width) // 2
    y = box[1] + (box[3] - box[1] - fitted.height) // 2
    canvas.alpha_composite(fitted, (x, y))


def _safe_relative(value: str, label: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} 必须是安全相对路径：{value}")
    return path


def _source_path(source_dir: Path, value: str | list[str]) -> Path:
    choices = [value] if isinstance(value, str) else value
    for choice in choices:
        path = source_dir / _safe_relative(choice, "source")
        if path.is_file():
            return path
    raise FileNotFoundError(f"找不到主题素材：{' / '.join(choices)}")


def _target_path(output_dir: Path, value: str) -> Path:
    path = output_dir / _safe_relative(value, "target")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _box(image: Image.Image, values: list[int]) -> tuple[int, int, int, int]:
    if len(values) != 4:
        raise ValueError(f"crop box 必须有四个整数：{values}")
    left, top, right, bottom = values
    return left, top, image.width if right == -1 else right, image.height if bottom == -1 else bottom


def _preprocess(image: Image.Image, spec: str | dict | None) -> Image.Image:
    if not spec or spec == "none":
        return image.convert("RGBA")
    if isinstance(spec, str):
        name, options = spec, {}
    else:
        name, options = str(spec.get("name", "none")), spec
    if name == "clean_alpha":
        return clean_alpha(image, int(options.get("threshold", 16)))
    if name == "white_to_alpha":
        return white_to_alpha(
            image,
            int(options.get("transparent_at", 10)),
            int(options.get("opaque_at", 48)),
        )
    if name == "remove_low_alpha_haze":
        return remove_low_alpha_haze(image, int(options.get("threshold", 112)))
    raise ValueError(f"未知 preprocess：{name}")


def _transform(image: Image.Image, name: str | None) -> Image.Image:
    if not name:
        return image
    if name == "edge_overlay":
        rgba = np.asarray(image.convert("RGBA")).copy()
        if image.width <= 80 or image.height <= 36:
            raise ValueError("Button crop is too small for border-image slices")
        rgba[18:-18, 40:-40, 3] = 0
        rgba[rgba[:, :, 3] == 0, :3] = 0
        return Image.fromarray(rgba, "RGBA")
    if name == "button_surface":
        surface = image.convert("RGBA")
        center = surface.getpixel((surface.width // 2, surface.height // 2))
        if center[3] < 250 or min(center[:3]) < 230:
            raise ValueError("Button surface center must remain opaque and near-white")
        return surface
    raise ValueError(f"未知 transform：{name}")


def _save_png(image: Image.Image, target: Path) -> None:
    image.save(target, format="PNG", optimize=True, compress_level=9)


def _save_webp(image: Image.Image, target: Path, step: dict) -> None:
    options = {
        "format": "WEBP",
        "lossless": bool(step.get("lossless", False)),
        "method": 6,
    }
    if "quality" in step:
        options["quality"] = int(step["quality"])
    image.save(target, **options)


def _webp_image(source: Image.Image, step: dict) -> Image.Image:
    mode = step.get("mode", "resize")
    size = tuple(step.get("size", []))
    if mode == "resize":
        image = source.convert("RGB")
        return image.resize(size, Image.Resampling.LANCZOS) if size and image.size != size else image
    if mode == "fit":
        return ImageOps.fit(source.convert("RGB"), size, method=Image.Resampling.LANCZOS)
    if mode == "mirror_tile":
        tile = source.convert("RGB").resize((512, 512), Image.Resampling.LANCZOS)
        output = Image.new("RGB", (1024, 1024))
        output.paste(tile, (0, 0))
        output.paste(ImageOps.mirror(tile), (512, 0))
        output.paste(ImageOps.flip(tile), (0, 512))
        output.paste(ImageOps.flip(ImageOps.mirror(tile)), (512, 512))
        return output
    if mode == "crop_resize":
        image = _preprocess(source, step.get("preprocess"))
        image = image.crop(_box(image, step["box"]))
        if step.get("visible", True):
            image = crop_visible(image, int(step.get("padding", 0)))
        return resize_alpha(image, size)
    if mode == "dark_row_strip":
        image = source.convert("RGB")
        pixels = np.asarray(image)
        row_distance = (255 - pixels.mean(axis=2)).mean(axis=1)
        rows = np.flatnonzero(row_distance > float(step.get("threshold", 10)))
        if not len(rows):
            raise ValueError("Dark row strip does not contain a detectable line")
        center = round((int(rows[0]) + int(rows[-1])) / 2)
        crop_height = round(image.width / int(step.get("aspect", 8)))
        top = max(0, min(image.height - crop_height, center - crop_height // 2))
        return image.crop((0, top, image.width, top + crop_height)).resize(
            size, Image.Resampling.LANCZOS,
        )
    raise ValueError(f"未知 webp mode：{mode}")


def validate_plan(plan: dict) -> None:
    if not isinstance(plan.get("theme"), str) or not isinstance(plan.get("steps"), list):
        raise ValueError("主题清单必须包含 theme 和 steps")
    known: set[str] = set()
    for index, step in enumerate(plan["steps"]):
        if step.get("op") not in {"png", "webp", "atlas"}:
            raise ValueError(f"步骤 {index} 的 op 不受支持：{step.get('op')}")
        if step.get("target"):
            _safe_relative(str(step["target"]), "target")
        ident = step.get("id")
        if ident:
            if ident in known:
                raise ValueError(f"重复主题资产 id：{ident}")
            known.add(ident)
        if step.get("op") == "atlas":
            for item in step.get("items", []):
                if item.get("ref") not in known:
                    raise ValueError(f"atlas 引用了尚未生成的资产：{item.get('ref')}")


def load_plan(path: Path) -> dict:
    plan = json.loads(path.read_text(encoding="utf-8"))
    validate_plan(plan)
    return plan


def process_plan(plan: dict, source_dir: Path, output_dir: Path) -> list[Path]:
    validate_plan(plan)
    images: dict[str, Image.Image] = {}
    outputs: list[Path] = []
    for step in plan["steps"]:
        op = step["op"]
        target = _target_path(output_dir, step["target"])
        if op == "webp":
            source = Image.open(_source_path(source_dir, step["source"]))
            image = _webp_image(source, step)
            _save_webp(image, target, step)
        elif op == "png":
            image = _preprocess(
                Image.open(_source_path(source_dir, step["source"])),
                step.get("preprocess"),
            )
            if step.get("box"):
                image = image.crop(_box(image, step["box"]))
            if step.get("visible"):
                image = crop_visible(image, int(step.get("padding", 4)))
            image = _transform(image, step.get("transform"))
            if step.get("size"):
                image = resize_alpha(image, tuple(step["size"]))
            _save_png(image, target)
        else:
            image = Image.new("RGBA", tuple(step["size"]), (0, 0, 0, 0))
            for item in step.get("items", []):
                place_center(image, images[item["ref"]], tuple(item["box"]))
            _save_png(image, target)
        if step.get("id"):
            images[step["id"]] = image.copy()
        outputs.append(target)
    return outputs


def run_manifest(manifest: Path, source_dir: Path, output_dir: Path) -> list[Path]:
    return process_plan(load_plan(manifest), source_dir, output_dir)


def main_for_manifest(manifest: Path) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    run_manifest(manifest, args.source_dir, args.output_dir)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    run_manifest(args.manifest, args.source_dir, args.output_dir)


if __name__ == "__main__":
    main()
