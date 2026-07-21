import importlib.util
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
