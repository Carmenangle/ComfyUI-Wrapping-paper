"""组装 Windows 开箱即用支撑包：启动器、分层 Runtime、源码和 MinGit。"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import urllib.request
import zipfile
from pathlib import Path


APP_NAME = "ComfyUI-Wrapping-paper"
TARGET = "windows-x64-standard"
CHUNK_SIZE = 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(CHUNK_SIZE), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_target(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    resolved_root = root.resolve()
    if target != resolved_root and resolved_root not in target.parents:
        raise ValueError(f"压缩包包含非法路径：{relative}")
    return target


def extract_zip(archive: Path, destination: Path, *, strip_root: bool) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        infos = bundle.infolist()
        names = [info.filename.strip("/") for info in infos if info.filename.strip("/")]
        roots = {name.split("/", 1)[0] for name in names}
        prefix = next(iter(roots)) + "/" if strip_root and len(roots) == 1 else ""
        for info in infos:
            relative = info.filename[len(prefix):] if prefix and info.filename.startswith(prefix) else info.filename
            relative = relative.strip("/")
            if not relative:
                continue
            target = _safe_target(destination, relative)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def _manifest(assets_dir: Path, version: str) -> tuple[Path, dict]:
    matches = []
    for path in assets_dir.glob(f"{APP_NAME}-update-*-{TARGET}.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (
            payload.get("schema_version") == 2
            and payload.get("target") == TARGET
            and str(payload.get("app_version", "")).lstrip("v") == version.lstrip("v")
        ):
            matches.append((path, payload))
    if len(matches) != 1:
        raise RuntimeError(f"需要唯一的 {TARGET} v{version.lstrip('v')} 更新清单，实际找到 {len(matches)} 个")
    return matches[0]


def _assemble_layer(assets_dir: Path, layer: dict, work_dir: Path) -> Path:
    archive = work_dir / str(layer["archive"])
    archive.parent.mkdir(parents=True, exist_ok=True)
    with archive.open("wb") as output:
        for part in layer.get("assets", []):
            source = assets_dir / str(part["name"])
            if not source.is_file():
                raise FileNotFoundError(f"缺少分层资产：{source.name}")
            if source.stat().st_size != int(part["size"]) or sha256_file(source) != part["sha256"]:
                raise RuntimeError(f"分层资产校验失败：{source.name}")
            with source.open("rb") as stream:
                shutil.copyfileobj(stream, output)
    if archive.stat().st_size != int(layer["size"]) or sha256_file(archive) != layer["sha256"]:
        raise RuntimeError(f"分层归档校验失败：{archive.name}")
    return archive


def _write_zip(tree: Path, output: Path, root_name: str) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(candidate for candidate in tree.rglob("*") if candidate.is_file()):
            bundle.write(path, Path(root_name) / path.relative_to(tree))
    return output


def build_portable(
    assets_dir: Path, mingit_archive: Path, version: str,
    output_dir: Path, work_dir: Path,
) -> Path:
    assets_dir = assets_dir.resolve()
    _, manifest = _manifest(assets_dir, version)
    launcher = assets_dir / f"{APP_NAME}.exe"
    if not launcher.is_file():
        raise FileNotFoundError(f"缺少启动器：{launcher.name}")
    if work_dir.exists():
        shutil.rmtree(work_dir)
    tree = work_dir / "tree"
    runtime = tree / "data" / "runtime"
    tree.mkdir(parents=True)
    shutil.copy2(launcher, tree / launcher.name)

    layers = manifest["layers"]
    for name, folder, state_key in (
        ("base", "base", "base_id"),
        ("application", "apps", "application_id"),
    ):
        layer = layers[name]
        archive = _assemble_layer(assets_dir, layer, work_dir / "archives")
        extract_zip(archive, runtime / folder / str(manifest[state_key]), strip_root=True)

    state = {
        key: manifest.get(key, "")
        for key in (
            "schema_version", "app_version", "target", "edition",
            "base_id", "application_id", "rag_id",
        )
    }
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "current.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    userdata = tree / "data" / "userdata"
    userdata.mkdir(parents=True)
    (userdata / ".keep").write_bytes(b"")
    extract_zip(mingit_archive, tree / "dependencies" / "git", strip_root=False)
    if not (tree / "dependencies" / "git" / "cmd" / "git.exe").is_file():
        raise RuntimeError("MinGit 压缩包缺少 cmd/git.exe")

    root_name = f"{APP_NAME}-{version}-windows-x64-portable"
    return _write_zip(tree, output_dir / f"{root_name}.zip", root_name)


def _download_mingit(config: dict, destination: Path) -> Path:
    expected = str(config["sha256"])
    if destination.is_file() and sha256_file(destination) == expected:
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(str(config["url"]), headers={"User-Agent": APP_NAME})
    with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output)
    if sha256_file(destination) != expected:
        destination.unlink(missing_ok=True)
        raise RuntimeError("MinGit SHA256 校验失败")
    return destination


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config", type=Path,
        default=Path(__file__).resolve().parents[1] / "release" / "portable-windows.json",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--version", required=True)
    build.add_argument("--assets-dir", type=Path, required=True)
    build.add_argument("--output-dir", type=Path, required=True)
    build.add_argument("--work-dir", type=Path, required=True)
    build.add_argument("--mingit-archive", type=Path)
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    if config.get("schema_version") != 1 or config.get("target") != TARGET:
        raise RuntimeError("便携包配置无效")
    mingit = args.mingit_archive or _download_mingit(
        config["mingit"], args.work_dir / "downloads" / "mingit.zip"
    )
    output = build_portable(
        args.assets_dir, mingit, args.version,
        args.output_dir, args.work_dir / "bundle",
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
