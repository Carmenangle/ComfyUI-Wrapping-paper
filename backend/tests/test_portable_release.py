import importlib.util
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "portable_release", ROOT / "scripts" / "portable_release.py"
)
assert SPEC and SPEC.loader
portable_release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(portable_release)


def _layer(assets: Path, name: str, root: str, files: dict[str, bytes]) -> dict:
    archive = assets / name
    with zipfile.ZipFile(archive, "w") as bundle:
        for relative, payload in files.items():
            bundle.writestr(f"{root}/{relative}", payload)
    return {
        "id": root.split("-", 1)[1],
        "archive": name,
        "size": archive.stat().st_size,
        "sha256": portable_release.sha256_file(archive),
        "assets": [{
            "name": name,
            "size": archive.stat().st_size,
            "sha256": portable_release.sha256_file(archive),
        }],
    }


def test_build_portable_bundle_contains_launcher_runtime_source_and_mingit(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "ComfyUI-Wrapping-paper.exe").write_bytes(b"launcher")
    base = _layer(
        assets, "base.zip", "base-base-a",
        {"ComfyUI-Wrapping-paper-Runtime.exe": b"runtime", "_internal/python313.dll": b"py"},
    )
    application = _layer(
        assets, "application.zip", "application-app-a",
        {"backend/app/main.py": b"app = None", "frontend/index.html": b"ok"},
    )
    manifest = {
        "schema_version": 2,
        "app_version": "v0.15",
        "target": "windows-x64-standard",
        "edition": "standard",
        "base_id": "base-a",
        "application_id": "app-a",
        "rag_id": "",
        "layers": {"base": base, "application": application},
    }
    (assets / "ComfyUI-Wrapping-paper-update-v0.15-windows-x64-standard.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    mingit = tmp_path / "mingit.zip"
    with zipfile.ZipFile(mingit, "w") as bundle:
        bundle.writestr("cmd/git.exe", b"git")
        bundle.writestr("COPYING", b"license")

    output = portable_release.build_portable(
        assets, mingit, "v0.15", tmp_path / "out", tmp_path / "work"
    )

    assert output.name == "ComfyUI-Wrapping-paper-00-USER-DOWNLOAD-Windows-x64-Standard-v0.15.zip"
    root = "ComfyUI-Wrapping-paper-v0.15-windows-x64-Standard-portable/"
    with zipfile.ZipFile(output) as bundle:
        names = set(bundle.namelist())
        state = json.loads(bundle.read(root + "data/runtime/current.json"))
    assert root + "ComfyUI-Wrapping-paper.exe" in names
    assert root + "dependencies/git/cmd/git.exe" in names
    assert root + "data/runtime/base/base-a/_internal/python313.dll" in names
    assert root + "data/runtime/apps/app-a/backend/app/main.py" in names
    assert state["application_id"] == "app-a"


def test_full_rag_portable_bundle_contains_rag_layer(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "ComfyUI-Wrapping-paper.exe").write_bytes(b"launcher")
    base = _layer(assets, "base.zip", "base-base-a", {"ComfyUI-Wrapping-paper-Runtime.exe": b"runtime"})
    application = _layer(assets, "application.zip", "application-app-a", {"backend/app/main.py": b"app = None"})
    rag = _layer(assets, "rag.zip", "rag-rag-a", {"site-packages/torch/__init__.py": b""})
    manifest = {
        "schema_version": 2,
        "app_version": "v0.15",
        "target": "windows-x64-full-rag",
        "edition": "full-rag",
        "base_id": "base-a",
        "application_id": "app-a",
        "rag_id": "rag-a",
        "layers": {"base": base, "application": application, "rag": rag},
    }
    (assets / "ComfyUI-Wrapping-paper-update-v0.15-windows-x64-full-rag.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    mingit = tmp_path / "mingit.zip"
    with zipfile.ZipFile(mingit, "w") as bundle:
        bundle.writestr("cmd/git.exe", b"git")

    output = portable_release.build_portable(
        assets, mingit, "v0.15", tmp_path / "out", tmp_path / "work",
        "windows-x64-full-rag",
    )

    assert output.name == "ComfyUI-Wrapping-paper-00-USER-DOWNLOAD-Windows-x64-Full-RAG-v0.15.zip"
    root = "ComfyUI-Wrapping-paper-v0.15-windows-x64-Full-RAG-portable/"
    with zipfile.ZipFile(output) as bundle:
        names = set(bundle.namelist())
        state = json.loads(bundle.read(root + "data/runtime/current.json"))
    assert root + "data/runtime/rag/rag-a/site-packages/torch/__init__.py" in names
    assert state["edition"] == "full-rag"
    assert state["rag_id"] == "rag-a"
