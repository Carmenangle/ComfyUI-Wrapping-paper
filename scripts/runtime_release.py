"""固定 Runtime 发布 Module：目标矩阵、组装、校验、归档与分片。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import NamedTuple


GITHUB_ASSET_LIMIT = 1_900_000_000
APP_NAME = "ComfyUI-Wrapping-paper"


class RuntimeTarget(NamedTuple):
    id: str
    os: str
    arch: str
    edition: str
    runner: str
    accelerator: str
    python_version: str
    pyinstaller_version: str
    reranker_repo: str
    reranker_revision: str
    reranker_directory: str
    torch_version: str = ""
    torch_index_url: str = ""

    @property
    def executable_name(self) -> str:
        return APP_NAME + (".exe" if self.os == "windows" else "")

    @property
    def full_rag(self) -> bool:
        return self.edition == "full-rag"


def load_targets(path: Path) -> dict[str, RuntimeTarget]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1:
        raise ValueError("不支持的 Runtime 目标清单版本")
    reranker = raw["reranker"]
    targets: dict[str, RuntimeTarget] = {}
    for item in raw["targets"]:
        target = RuntimeTarget(
            id=item["id"], os=item["os"], arch=item["arch"],
            edition=item["edition"], runner=item["runner"],
            accelerator=item["accelerator"],
            python_version=raw["python_version"],
            pyinstaller_version=raw["pyinstaller_version"],
            reranker_repo=reranker["repo_id"],
            reranker_revision=reranker["revision"],
            reranker_directory=reranker["directory"],
            torch_version=item.get("torch_version", ""),
            torch_index_url=item.get("torch_index_url", ""),
        )
        if target.id in targets:
            raise ValueError(f"Runtime 目标重复：{target.id}")
        if target.full_rag and not target.torch_version:
            raise ValueError(f"完整 RAG 目标缺少固定 Torch 版本：{target.id}")
        targets[target.id] = target
    return targets


def runtime_environment(root: Path, edition: str) -> dict[str, str]:
    root = root.resolve()
    env = {
        "LAF_RUNTIME_ROOT": str(root),
        "LAF_RUNTIME_EDITION": edition,
        "LAF_DATA_DIR": str(root / "data"),
        "LAF_FRONTEND_DIST": str(root / "frontend"),
        "LAF_COMFY_EXT_DIR": str(root / "comfyui-ext"),
    }
    if edition == "full-rag":
        env["LAF_BUNDLED_RERANKER_DIR"] = str(
            root / "models" / "reranker" / "Qwen3-Reranker-0.6B"
        )
    return env


def pyinstaller_command(target: RuntimeTarget, root: Path, work_dir: Path) -> list[str]:
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
        "--name", APP_NAME,
        "--paths", str(root / "backend"),
        "--distpath", str(work_dir / "dist"),
        "--workpath", str(work_dir / "build"),
        "--specpath", str(work_dir / "spec"),
        "--hidden-import", "app.main",
    ]
    command.extend((
        "--collect-submodules", "chromadb",
        "--collect-data", "chromadb",
        "--collect-binaries", "chromadb",
        "--exclude-module", "chromadb.test",
        "--exclude-module", "chromadb.server",
        "--exclude-module", "pytest",
    ))
    for module in ("langchain_chroma", "langgraph", "langchain_mcp_adapters"):
        command.extend(("--collect-all", module))
    if target.full_rag:
        for module in ("sentence_transformers", "transformers", "torch", "safetensors"):
            command.extend(("--collect-all", module))
    else:
        for module in ("sentence_transformers", "transformers", "torch"):
            command.extend(("--exclude-module", module))
    command.append(str(root / "scripts" / "runtime_entry.py"))
    return command


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _model_complete(model_dir: Path) -> bool:
    single = model_dir / "model.safetensors"
    if single.is_file() and single.stat().st_size > 0:
        return True
    index_path = model_dir / "model.safetensors.index.json"
    if not index_path.is_file():
        return False
    try:
        shards = set(
            json.loads(index_path.read_text(encoding="utf-8"))
            .get("weight_map", {}).values()
        )
    except (OSError, ValueError, TypeError):
        return False
    return bool(shards) and all(
        (model_dir / shard).is_file() and (model_dir / shard).stat().st_size > 0
        for shard in shards
    )


def validate_runtime_tree(tree: Path, target: RuntimeTarget) -> list[str]:
    errors: list[str] = []
    if not (tree / target.executable_name).is_file():
        errors.append(f"缺少运行入口：{target.executable_name}")
    if not (tree / "frontend" / "index.html").is_file():
        errors.append("缺少已构建前端：frontend/index.html")
    if target.full_rag:
        model_dir = tree / "models" / "reranker" / target.reranker_directory
        if not _model_complete(model_dir):
            errors.append("完整 RAG 版缺少完整的内置 Reranker 权重")
    return errors


def run_runtime_self_check(tree: Path, target: RuntimeTarget) -> None:
    with tempfile.TemporaryDirectory(prefix="runtime-self-check-", dir=tree.parent) as temp_data:
        env = os.environ.copy()
        env.update(runtime_environment(tree, target.edition))
        env["LAF_DATA_DIR"] = temp_data
        env["LAF_RUNTIME_SELF_TEST"] = "1"
        env["LAF_NO_BROWSER"] = "1"
        result = subprocess.run(
            [str(tree / target.executable_name)],
            cwd=tree, env=env, text=True, capture_output=True, check=False,
        )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"Runtime 自检失败：{detail}")
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError) as exc:
        raise RuntimeError("Runtime 自检没有返回有效结果") from exc
    if payload.get("status") != "ok":
        raise RuntimeError("Runtime 自检未通过")


def write_runtime_manifest(tree: Path, target: RuntimeTarget, version: str) -> Path:
    files = []
    for path in sorted(candidate for candidate in tree.rglob("*") if candidate.is_file()):
        if path.name == "runtime-manifest.json":
            continue
        files.append({
            "path": path.relative_to(tree).as_posix(),
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    manifest = {
        "schema_version": 1,
        "app_version": version,
        "target": target.id,
        "edition": target.edition,
        "python_version": target.python_version,
        "accelerator": target.accelerator,
        "files": files,
    }
    path = tree / "runtime-manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def create_archive(tree: Path, target: RuntimeTarget, version: str, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    base_name = f"{APP_NAME}-{version}-{target.id}"
    if target.os == "windows":
        archive = output_dir / f"{base_name}.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for path in sorted(candidate for candidate in tree.rglob("*") if candidate.is_file()):
                bundle.write(path, Path(base_name) / path.relative_to(tree))
        return archive
    archive = output_dir / f"{base_name}.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(tree, arcname=base_name)
    return archive


def split_asset(archive: Path, max_part_bytes: int = GITHUB_ASSET_LIMIT) -> list[Path]:
    if archive.stat().st_size <= max_part_bytes:
        return [archive]
    parts: list[Path] = []
    with archive.open("rb") as source:
        index = 1
        while block := source.read(max_part_bytes):
            part = archive.with_name(f"{archive.name}.part{index:02d}")
            part.write_bytes(block)
            parts.append(part)
            index += 1
    payload = {
        "schema_version": 1,
        "archive": archive.name,
        "size": archive.stat().st_size,
        "sha256": sha256_file(archive),
        "parts": [part.name for part in parts],
        "part_sha256": {part.name: sha256_file(part) for part in parts},
    }
    archive.with_name(archive.name + ".parts.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return parts


def _run(command: list[str], cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def npm_executable() -> str:
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm:
        raise RuntimeError("未找到 npm，无法构建前端")
    return npm


def install_frontend_dependencies(root: Path, frontend_work: Path, npm: str) -> None:
    cache = root / "vendor" / "npm"
    if cache.is_dir():
        offline = subprocess.run(
            [npm, "ci", "--offline", "--cache", str(cache)],
            cwd=frontend_work, check=False,
        )
        if offline.returncode == 0:
            return
        print("当前平台的 vendor/npm 不完整，回退联网安装。")
    _run([npm, "ci"], frontend_work)


def _host_matches(target: RuntimeTarget) -> bool:
    host_os = (
        "windows" if os.name == "nt"
        else "macos" if sys.platform == "darwin"
        else "linux" if sys.platform.startswith("linux")
        else "other"
    )
    machine = platform.machine().lower()
    host_arch = "arm64" if machine in {"arm64", "aarch64"} else "x64" if machine in {"amd64", "x86_64"} else machine
    return target.os == host_os and target.arch == host_arch


def install_build_dependencies(root: Path, target: RuntimeTarget) -> None:
    _run([sys.executable, "-m", "pip", "install", "-r", str(root / "backend" / "requirements.txt")], root)
    if target.full_rag:
        torch_command = [sys.executable, "-m", "pip", "install", f"torch=={target.torch_version}"]
        if target.torch_index_url:
            torch_command.extend(("--index-url", target.torch_index_url))
        _run(torch_command, root)
        _run([sys.executable, "-m", "pip", "install", "-r", str(root / "backend" / "requirements-reranker.txt")], root)
    _run([sys.executable, "-m", "pip", "install", f"pyinstaller=={target.pyinstaller_version}"], root)


def _prepare_model(target: RuntimeTarget, destination: Path, model_source: str) -> None:
    if model_source:
        source = Path(model_source).expanduser().resolve()
        if not _model_complete(source):
            raise RuntimeError(f"Reranker 权重不完整：{source}")
        shutil.copytree(source, destination, dirs_exist_ok=True)
        return
    from huggingface_hub import snapshot_download
    snapshot_download(
        repo_id=target.reranker_repo,
        revision=target.reranker_revision,
        local_dir=destination,
    )


def build_runtime(
    root: Path, target: RuntimeTarget, version: str, output_dir: Path,
    work_dir: Path, *, install_deps: bool, model_source: str,
) -> list[Path]:
    if not _host_matches(target):
        raise RuntimeError(f"当前主机不能构建目标 {target.id}")
    if install_deps:
        install_build_dependencies(root, target)
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)
    frontend_work = work_dir / "frontend-source"
    shutil.copytree(
        root / "frontend", frontend_work,
        ignore=shutil.ignore_patterns("node_modules", "dist"),
    )
    npm = npm_executable()
    install_frontend_dependencies(root, frontend_work, npm)
    _run([npm, "run", "build"], frontend_work)
    _run(pyinstaller_command(target, root, work_dir), root)
    tree = work_dir / "dist" / APP_NAME
    shutil.copytree(frontend_work / "dist", tree / "frontend", dirs_exist_ok=True)
    shutil.copytree(root / "comfyui-ext", tree / "comfyui-ext", dirs_exist_ok=True)
    shutil.copy2(root / "README.md", tree / "README.md")
    if target.full_rag:
        _prepare_model(
            target,
            tree / "models" / "reranker" / target.reranker_directory,
            model_source,
        )
    errors = validate_runtime_tree(tree, target)
    if errors:
        raise RuntimeError("；".join(errors))
    run_runtime_self_check(tree, target)
    write_runtime_manifest(tree, target, version)
    archive = create_archive(tree, target, version, output_dir)
    assets = split_asset(archive)
    if assets != [archive]:
        archive.unlink()
        assets.append(archive.with_name(archive.name + ".parts.json"))
    return assets


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--targets", type=Path,
        default=Path(__file__).resolve().parents[1] / "release" / "runtime-targets.json",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("matrix")
    build = sub.add_parser("build")
    build.add_argument("--target", required=True)
    build.add_argument("--version", required=True)
    build.add_argument("--output-dir", type=Path, required=True)
    build.add_argument("--work-dir", type=Path, required=True)
    build.add_argument("--install-deps", action="store_true")
    build.add_argument("--model-source", default="")
    verify = sub.add_parser("verify")
    verify.add_argument("--target", required=True)
    verify.add_argument("--tree", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    targets = load_targets(args.targets)
    if args.command == "matrix":
        print(json.dumps({"include": [
            {"target": item.id, "runner": item.runner, "python-version": item.python_version}
            for item in targets.values()
        ]}, separators=(",", ":")))
        return 0
    target = targets.get(args.target)
    if target is None:
        raise SystemExit(f"未知 Runtime 目标：{args.target}")
    if args.command == "verify":
        errors = validate_runtime_tree(args.tree, target)
        for error in errors:
            print("ERROR: " + error)
        return 1 if errors else 0
    root = Path(__file__).resolve().parents[1]
    assets = build_runtime(
        root, target, args.version, args.output_dir, args.work_dir,
        install_deps=args.install_deps, model_source=args.model_source,
    )
    for asset in assets:
        print(asset)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
