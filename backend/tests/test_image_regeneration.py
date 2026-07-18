from app.routers import ai_agent
from app.services import generation_store, image_gen


def test_regenerate_image_reuploads_all_bound_references(monkeypatch):
    calls = []
    snapshot = {
        "kind": "ai-image",
        "prompt": "固定提示词",
        "images": ["http://local/ref-1.png", "data:image/png;base64,AAA"],
        "size": "1536x1024",
        "quality": "medium",
        "model": {"baseUrl": "https://images.example", "modelName": "image-v2"},
    }

    def fake_generate(base_url, api_key, model, prompt, images, *, size, quality):
        calls.append((base_url, api_key, model, prompt, images, size, quality))
        return "generated.png"

    monkeypatch.setattr(image_gen, "generate_with_images", fake_generate)
    monkeypatch.setattr(
        generation_store,
        "persist_image",
        lambda *args: {"id": "result-1", "url": "saved.png", "regeneration": args[-1]},
    )
    req = ai_agent.RegenerateImageRequest(
        thread_id="thread-1",
        repo_id="repo-1",
        prompt=snapshot["prompt"],
        images=snapshot["images"],
        gen_base_url=snapshot["model"]["baseUrl"],
        gen_api_key="secret",
        gen_model=snapshot["model"]["modelName"],
        size=snapshot["size"],
        image_quality=snapshot["quality"],
    )

    result = ai_agent.regenerate_image(req)

    assert calls == [(
        "https://images.example", "secret", "image-v2", "固定提示词",
        ["http://local/ref-1.png", "data:image/png;base64,AAA"],
        "1536x1024", "medium",
    )]
    assert result["regeneration"] == snapshot
