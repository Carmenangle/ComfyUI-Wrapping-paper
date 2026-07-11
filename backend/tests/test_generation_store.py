from app.services import generation_store


def _args(**overrides):
    values = dict(
        thread_id="thread", repo_id="repo", prompt_id="prompt", prompt="text",
        images=[{"filename": "a.png", "subfolder": "", "type": "output"}],
        output_dir="out", comfyui_url="http://comfy", embed_base="", embed_key="",
        embed_model="embed",
    )
    values.update(overrides)
    return values


def test_workflow_batch_uses_stable_identity(monkeypatch):
    generation_store._MEMORY_DONE.clear()
    monkeypatch.setattr(generation_store.image_store, "save_local", lambda *a, **k: "C:/out/a.png")
    monkeypatch.setattr(generation_store, "_index_with_retry", lambda *a, **k: True)
    monkeypatch.setattr(generation_store.chat_memory, "append_message", lambda *a, **k: None)
    saved = []
    monkeypatch.setattr(generation_store.chat_snapshot, "upsert", lambda thread, msg: saved.append(msg))

    first = generation_store.finalize_workflow_batch(**_args())
    second = generation_store.finalize_workflow_batch(**_args())

    assert first["messages"] == second["messages"]
    assert first["images"][0]["message_id"] == second["images"][0]["message_id"]
    assert saved[0]["id"] == saved[1]["id"]


def test_workflow_batch_home_has_no_durable_side_effects(monkeypatch):
    monkeypatch.setattr(generation_store.image_store, "save_local", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr(generation_store, "_index_with_retry", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr(generation_store.chat_snapshot, "upsert", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr(generation_store.chat_memory, "append_message", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))

    result = generation_store.finalize_workflow_batch(**_args(repo_id="home"))

    assert result["durable"] is False
    assert result["messages"][0]["image"].startswith("http://127.0.0.1:8010/api/comfyui/view?")


def test_workflow_batch_keeps_online_image_when_save_fails(monkeypatch):
    generation_store._MEMORY_DONE.clear()
    monkeypatch.setattr(generation_store.image_store, "save_local", lambda *a, **k: (_ for _ in ()).throw(RuntimeError()))
    monkeypatch.setattr(generation_store, "_index_with_retry", lambda *a, **k: True)
    monkeypatch.setattr(generation_store.chat_snapshot, "upsert", lambda *a, **k: None)
    monkeypatch.setattr(generation_store.chat_memory, "append_message", lambda *a, **k: None)

    result = generation_store.finalize_workflow_batch(**_args())

    assert result["images"][0]["errors"] == ["persist"]
    assert result["messages"][0]["image"].startswith("http://127.0.0.1:8010/api/comfyui/view?")
