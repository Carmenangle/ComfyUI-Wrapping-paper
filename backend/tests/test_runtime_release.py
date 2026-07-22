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


def test_standard_and_full_rag_share_external_app_base(tmp_path):
    targets = runtime_release.load_targets(ROOT / "release" / "runtime-targets.json")
    standard = runtime_release.pyinstaller_command(
        targets["windows-x64-standard"], ROOT, tmp_path
    )
    full = runtime_release.pyinstaller_command(
        targets["windows-x64-full-rag"], ROOT, tmp_path
    )

    assert standard == full
    spec = (ROOT / "release" / "runtime-layered.spec").read_text(encoding="utf-8")
    assert 'entry[0].startswith("app.")' in spec
    assert "sys.stdlib_module_names" in spec
    assert '"sentence_transformers", "transformers", "torch"' in spec


def test_base_id_ignores_edition_but_rag_id_tracks_accelerator():
    targets = runtime_release.load_targets(ROOT / "release" / "runtime-targets.json")
    standard = targets["windows-x64-standard"]
    full = targets["windows-x64-full-rag"]

    assert runtime_release.base_id(ROOT, standard) == runtime_release.base_id(ROOT, full)
    assert runtime_release.rag_id(ROOT, full)


def test_runtime_environment_uses_writable_data_without_bundled_models(tmp_path):
    env = runtime_release.runtime_environment(tmp_path, "full-rag")

    assert env["LAF_DATA_DIR"] == str(tmp_path / "data")
    assert env["LAF_FRONTEND_DIST"] == str(tmp_path / "frontend")
    assert env["LAF_COMFY_EXT_DIR"] == str(tmp_path / "comfyui-ext")
    assert "LAF_BUNDLED_RERANKER_DIR" not in env


def test_full_rag_tree_does_not_require_bundled_model_weights(tmp_path):
    target = runtime_release.load_targets(
        ROOT / "release" / "runtime-targets.json"
    )["macos-arm64-full-rag"]
    tree = tmp_path / "runtime"
    (tree / "frontend").mkdir(parents=True)
    (tree / "frontend" / "index.html").write_text("ok", encoding="utf-8")
    (tree / target.executable_name).write_text("bin", encoding="utf-8")
    assert runtime_release.validate_runtime_tree(tree, target) == []


def test_runtime_targets_do_not_pin_or_download_model_weights():
    manifest = json.loads(
        (ROOT / "release" / "runtime-targets.json").read_text(encoding="utf-8")
    )
    workflow = (ROOT / ".github" / "workflows" / "runtime-release.yml").read_text(
        encoding="utf-8"
    )

    assert "reranker" not in manifest
    assert "huggingface" not in workflow.lower()
    assert "缓存完整 RAG 权重" not in workflow


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


def test_runtime_self_check_resolves_relative_tree_before_changing_cwd(
    monkeypatch, tmp_path,
):
    target = runtime_release.load_targets(
        ROOT / "release" / "runtime-targets.json"
    )["linux-x64-standard"]
    tree = tmp_path / "runtime"
    tree.mkdir()
    (tree / target.executable_name).touch()
    seen = {}

    class Result:
        returncode = 0
        stdout = '{"status":"ok"}\n'
        stderr = ""

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["cwd"] = kwargs["cwd"]
        return Result()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runtime_release.subprocess, "run", fake_run)
    runtime_release.run_runtime_self_check(Path("runtime"), target)

    assert Path(seen["command"][0]).is_absolute()
    assert Path(seen["cwd"]).is_absolute()


def test_application_layer_keeps_backend_source_visible(tmp_path):
    root = tmp_path / "project"
    (root / "backend" / "app").mkdir(parents=True)
    (root / "backend" / "app" / "main.py").write_text("app = None", encoding="utf-8")
    (root / "comfyui-ext").mkdir()
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("ok", encoding="utf-8")
    tree = tmp_path / "application"

    runtime_release.build_application_tree(root, frontend, tree, "v0.15")

    assert (tree / "backend" / "app" / "main.py").is_file()
    assert not (tree / "backend.zip").exists()
