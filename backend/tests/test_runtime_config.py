from pathlib import Path

from app.services import rag_backend


def test_embed_config_uses_bundled_reranker_only_when_user_path_is_empty(
    monkeypatch, tmp_path: Path
):
    bundled = tmp_path / "bundled"
    monkeypatch.setenv("LAF_BUNDLED_RERANKER_DIR", str(bundled))

    assert rag_backend.EmbedConfig().reranker_dir == str(bundled)
    assert rag_backend.EmbedConfig(reranker_dir="D:/custom").reranker_dir == "D:/custom"
