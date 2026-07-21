"""Build platform-specific source archives with offline Python and npm dependencies."""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from typing import NamedTuple


APP_NAME = "ComfyUI-Wrapping-paper"


class SourceTarget(NamedTuple):
    id: str
    os: str
    arch: str
    runner: str
    archive: str
    build_python_version: str
    python_versions: tuple[str, ...]


def load_targets(path: Path) -> dict[str, SourceTarget]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1:
        raise ValueError("Unsupported source target manifest version")
    versions = tuple(raw["python_versions"])
    targets: dict[str, SourceTarget] = {}
    for item in raw["targets"]:
        target = SourceTarget(
            id=item["id"], os=item["os"], arch=item["arch"],
            runner=item["runner"], archive=item["archive"],
            build_python_version=raw["build_python_version"],
            python_versions=tuple(item.get("python_versions", versions)),
        )
        if target.id in targets:
            raise ValueError(f"Duplicate source target: {target.id}")
        targets[target.id] = target
    return targets


def _host_identity() -> tuple[str, str]:
    host_os = (
        "windows" if os.name == "nt"
        else "macos" if sys.platform == "darwin"
        else "linux" if sys.platform.startswith("linux")
        else "other"
    )
    machine = platform.machine().lower()
    arch = "arm64" if machine in {"arm64", "aarch64"} else "x64" if machine in {"amd64", "x86_64"} else machine
    return host_os, arch


def host_target(targets: dict[str, SourceTarget]) -> SourceTarget:
    identity = _host_identity()
    for target in targets.values():
        if (target.os, target.arch) == identity:
            return target
    raise RuntimeError(f"No source release target for host {identity[0]}/{identity[1]}")


def pip_download_command(
    target: SourceTarget, root: Path, vendor_dir: Path, version: str,
) -> list[str]:
    del target
    return [
        sys.executable, "-m", "pip", "download",
        "--only-binary=:all:", "--python-version", version,
        "--implementation", "cp", "--dest", str(vendor_dir),
        "-r", str(root / "backend" / "requirements.txt"),
    ]


def _pip_check_command(root: Path, vendor_dir: Path, version: str) -> list[str]:
    return [
        sys.executable, "-m", "pip", "install", "--dry-run",
        "--ignore-installed", "--no-index", "--only-binary=:all:",
        "--python-version", version, "--implementation", "cp",
        "--find-links", str(vendor_dir),
        "-r", str(root / "backend" / "requirements.txt"),
    ]


def _run(command: list[str], cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def _npm() -> str:
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm:
        raise RuntimeError("npm was not found")
    return npm


def install_native_npm_dependencies(
    frontend: Path, npm: str, cache: Path | None = None,
) -> None:
    command = [npm, "ci"]
    if cache is not None:
        command.extend(("--cache", str(cache)))
    _run(command, frontend)


def _snapshot(root: Path, tree: Path, work_dir: Path) -> None:
    snapshot = work_dir / "source.tar"
    _run(["git", "archive", "--format=tar", "-o", str(snapshot), "HEAD"], root)
    tree.mkdir(parents=True)
    with tarfile.open(snapshot, "r") as bundle:
        bundle.extractall(tree, filter="data")


def _refresh_pip_vendor(
    root: Path, tree: Path, target: SourceTarget,
) -> None:
    vendor_dir = tree / "vendor" / "pip"
    shutil.rmtree(vendor_dir, ignore_errors=True)
    vendor_dir.mkdir(parents=True)
    for version in target.python_versions:
        _run(pip_download_command(target, root, vendor_dir, version), root)
    for version in target.python_versions:
        _run(_pip_check_command(root, vendor_dir, version), root)


def _refresh_npm_vendor(tree: Path) -> None:
    npm = _npm()
    frontend = tree / "frontend"
    cache = tree / "vendor" / "npm"
    shutil.rmtree(cache, ignore_errors=True)
    cache.mkdir(parents=True)
    install_native_npm_dependencies(frontend, npm, cache)
    shutil.rmtree(frontend / "node_modules", ignore_errors=True)
    for junk in ("_logs", "_update-notifier-last-checked"):
        path = cache / junk
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    _run([npm, "ci", "--dry-run", "--offline", "--cache", str(cache)], frontend)


def _validate_reused_vendor(root: Path, tree: Path, target: SourceTarget) -> None:
    vendor_dir = tree / "vendor" / "pip"
    for version in target.python_versions:
        _run(_pip_check_command(root, vendor_dir, version), root)
    _run([
        _npm(), "ci", "--dry-run", "--offline", "--cache",
        str(tree / "vendor" / "npm"),
    ], tree / "frontend")


def archive_path(output_dir: Path, target: SourceTarget, version: str) -> Path:
    name = f"{APP_NAME}-{version}-source-{target.id}"
    suffix = ".zip" if target.archive == "zip" else ".tar.gz"
    return output_dir / f"{name}{suffix}"


def _write_manifest(tree: Path, target: SourceTarget, version: str) -> None:
    wheels = sorted(path.name for path in (tree / "vendor" / "pip").glob("*.whl"))
    payload = {
        "schema_version": 1,
        "app_version": version,
        "target": target.id,
        "python_versions": list(target.python_versions),
        "wheel_count": len(wheels),
    }
    (tree / "source-package.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _archive(tree: Path, target: SourceTarget, version: str, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = archive_path(output_dir, target, version)
    base = archive.name.removesuffix(".zip").removesuffix(".tar.gz")
    if target.archive == "zip":
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for path in sorted(item for item in tree.rglob("*") if item.is_file()):
                bundle.write(path, Path(base) / path.relative_to(tree))
    else:
        with tarfile.open(archive, "w:gz") as bundle:
            bundle.add(tree, arcname=base)
    return archive


def build_source(
    root: Path, target: SourceTarget, version: str,
    output_dir: Path, work_dir: Path, *, reuse_vendor: bool,
) -> Path:
    if (target.os, target.arch) != _host_identity():
        raise RuntimeError(f"Current host cannot build {target.id}")
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)
    tree = work_dir / "tree"
    _snapshot(root, tree, work_dir)
    if reuse_vendor:
        _validate_reused_vendor(root, tree, target)
    else:
        _refresh_pip_vendor(root, tree, target)
        _refresh_npm_vendor(tree)
    _write_manifest(tree, target, version)
    return _archive(tree, target, version, output_dir)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--targets", type=Path,
        default=Path(__file__).resolve().parents[1] / "release" / "source-targets.json",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("matrix")
    sub.add_parser("host-target")
    build = sub.add_parser("build")
    build.add_argument("--target", required=True)
    build.add_argument("--version", required=True)
    build.add_argument("--output-dir", type=Path, required=True)
    build.add_argument("--work-dir", type=Path, required=True)
    build.add_argument("--reuse-vendor", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    targets = load_targets(args.targets)
    if args.command == "matrix":
        print(json.dumps({"include": [
            {
                "source-target": target.id,
                "runner": target.runner,
                "python-version": target.build_python_version,
            }
            for target in targets.values()
        ]}, separators=(",", ":")))
        return 0
    if args.command == "host-target":
        print(host_target(targets).id)
        return 0
    target = targets.get(args.target)
    if target is None:
        raise SystemExit(f"Unknown source target: {args.target}")
    root = Path(__file__).resolve().parents[1]
    archive = build_source(
        root, target, args.version, args.output_dir, args.work_dir,
        reuse_vendor=args.reuse_vendor,
    )
    print(archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
