import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "runtime_release", ROOT / "scripts" / "runtime_release.py"
)
assert SPEC and SPEC.loader
runtime_release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime_release)


def test_runtime_target_matrix_covers_supported_editions_and_platforms():
    targets = runtime_release.load_targets(ROOT / "release" / "runtime-targets.json")

    assert set(targets) == {
        "windows-x64-standard",
        "windows-x64-full-rag",
        "macos-arm64-standard",
        "macos-arm64-full-rag",
        "macos-x64-standard",
        "linux-x64-standard",
        "linux-x64-full-rag",
    }
    assert targets["windows-x64-full-rag"].accelerator == "cuda"
    assert targets["macos-arm64-full-rag"].accelerator == "mps"
    assert targets["linux-x64-full-rag"].accelerator == "cuda"
    assert all(target.python_version == "3.13.11" for target in targets.values())


def test_standard_and_full_rag_pyinstaller_plans_are_distinct(tmp_path):
    targets = runtime_release.load_targets(ROOT / "release" / "runtime-targets.json")
    standard = runtime_release.pyinstaller_command(
        targets["windows-x64-standard"], ROOT, tmp_path
    )
    full = runtime_release.pyinstaller_command(
        targets["windows-x64-full-rag"], ROOT, tmp_path
    )

    assert "sentence_transformers" in standard
    assert "--exclude-module" in standard
    assert "--collect-all" in full
    assert "sentence_transformers" in full
    full_excludes = {
        full[index + 1]
        for index, value in enumerate(full[:-1])
        if value == "--exclude-module"
    }
    assert "sentence_transformers" not in full_excludes
    assert "torch" not in full_excludes


def test_runtime_environment_uses_writable_data_and_bundled_reranker(tmp_path):
    env = runtime_release.runtime_environment(tmp_path, "full-rag")

    assert env["LAF_DATA_DIR"] == str(tmp_path / "data")
    assert env["LAF_FRONTEND_DIST"] == str(tmp_path / "frontend")
    assert env["LAF_COMFY_EXT_DIR"] == str(tmp_path / "comfyui-ext")
    assert Path(env["LAF_BUNDLED_RERANKER_DIR"]) == (
        tmp_path / "models" / "reranker" / "Qwen3-Reranker-0.6B"
    )


def test_full_rag_tree_requires_complete_bundled_model(tmp_path):
    target = runtime_release.load_targets(
        ROOT / "release" / "runtime-targets.json"
    )["macos-arm64-full-rag"]
    tree = tmp_path / "runtime"
    (tree / "frontend").mkdir(parents=True)
    (tree / "frontend" / "index.html").write_text("ok", encoding="utf-8")
    (tree / target.executable_name).write_text("bin", encoding="utf-8")
    model = tree / "models" / "reranker" / "Qwen3-Reranker-0.6B"
    model.mkdir(parents=True)
    (model / "config.json").write_text("{}", encoding="utf-8")

    errors = runtime_release.validate_runtime_tree(tree, target)
    assert any("Reranker" in error for error in errors)

    (model / "model.safetensors").write_bytes(b"weights")
    assert runtime_release.validate_runtime_tree(tree, target) == []


def test_split_asset_writes_reassembly_manifest(tmp_path):
    archive = tmp_path / "runtime.zip"
    archive.write_bytes(b"0123456789")

    parts = runtime_release.split_asset(archive, max_part_bytes=4)
    manifest = json.loads(
        (tmp_path / "runtime.zip.parts.json").read_text(encoding="utf-8")
    )

    assert [part.read_bytes() for part in parts] == [b"0123", b"4567", b"89"]
    assert manifest["archive"] == "runtime.zip"
    assert manifest["parts"] == [part.name for part in parts]
    assert manifest["sha256"] == runtime_release.sha256_file(archive)


def test_npm_executable_resolves_windows_command_wrapper(monkeypatch):
    monkeypatch.setattr(
        runtime_release.shutil,
        "which",
        lambda name: "C:/node/npm.cmd" if name == "npm.cmd" else None,
    )
    assert runtime_release.npm_executable() == "C:/node/npm.cmd"


def test_runtime_ci_does_not_reuse_foreign_offline_npm_cache(monkeypatch, tmp_path):
    commands = []
    monkeypatch.setattr(runtime_release, "_run", lambda command, cwd: commands.append(command))

    runtime_release.install_frontend_dependencies(
        tmp_path, tmp_path / "frontend", "npm", prefer_offline=False
    )

    assert commands == [["npm", "ci"]]
