from app.services import node_index


class FakeRag:
    def list_node_packs(self, cfg):
        return [
            {"id": "b", "title": "Zulu", "node_names": ["n1", "n2"], "python_module": "m.b"},
            {"id": "a", "title": "alpha", "node_names": ["n3"], "python_module": "m.a"},
        ]

    def search_node_packs(self, cfg, need, k=8):
        return [{"id": need, "k": k}]

    def get_node_pack(self, cfg, pack_id):
        return None if pack_id == "missing" else {"id": pack_id}

    def update_node_pack_content(self, cfg, pack_id, content):
        return pack_id != "missing"


def test_node_index_management_interface(monkeypatch):
    monkeypatch.setattr(node_index, "_rag", FakeRag())
    cfg = object()
    assert node_index.stats(cfg) == {"packs": 2, "nodes": 3}
    assert [item["id"] for item in node_index.list_packs(cfg)] == ["a", "b"]
    assert node_index.get_pack(cfg, "missing") is None
    assert node_index.update_pack_content(cfg, "missing", "x") is False


def test_node_index_search_interface(monkeypatch):
    monkeypatch.setattr(node_index, "_rag", FakeRag())
    assert node_index.search(object(), "need", 3) == [{"id": "need", "k": 3}]
