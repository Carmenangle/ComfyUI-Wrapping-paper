import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "runtime_entry", ROOT / "scripts" / "runtime_entry.py"
)
assert SPEC and SPEC.loader
runtime_entry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime_entry)


def test_full_rag_runtime_configures_dependencies_without_bundled_model(
    monkeypatch, tmp_path: Path,
):
    monkeypatch.setenv("LAF_RUNTIME_EDITION", "full-rag")
    monkeypatch.setenv("LAF_BUNDLED_RERANKER_DIR", "stale")

    runtime_entry.configure_environment(tmp_path)

    assert runtime_entry.os.environ["LAF_RUNTIME_EDITION"] == "full-rag"
    assert "LAF_BUNDLED_RERANKER_DIR" not in runtime_entry.os.environ


def test_full_rag_self_check_reports_torch_build(monkeypatch, capsys):
    class TorchVersion:
        cuda = "13.0"

    class Torch:
        __version__ = "2.13.0+cu130"
        version = TorchVersion()

    monkeypatch.setenv("LAF_RUNTIME_EDITION", "full-rag")
    monkeypatch.setattr(
        runtime_entry.importlib, "import_module",
        lambda name: Torch() if name == "torch" else object(),
    )

    runtime_entry.self_check()

    payload = json.loads(capsys.readouterr().out)
    assert payload["torch_version"] == "2.13.0+cu130"
    assert payload["torch_cuda"] == "13.0"
