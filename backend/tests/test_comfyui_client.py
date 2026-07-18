import json

from app.services import comfyui_client


class _FakeResp:
    def __init__(self, payload: dict):
        self._data = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._data


_HIST = {
    "pid": {
        "status": {"completed": True},
        "outputs": {
            "10": {"images": [{"filename": "mid.png", "subfolder": "", "type": "output"}]},
            "20": {
                "images": [{"filename": "final.png", "subfolder": "", "type": "output"}],
                "gifs": [{"filename": "anim.gif", "subfolder": "", "type": "output"}],
            },
        },
    }
}


def _patch(monkeypatch):
    monkeypatch.setattr(comfyui_client, "urlopen", lambda *a, **k: _FakeResp(_HIST))


def test_fetch_result_no_filter_returns_all(monkeypatch):
    _patch(monkeypatch)
    r = comfyui_client.fetch_result("http://127.0.0.1:8188", "pid")
    assert {i["filename"] for i in r["images"]} == {"mid.png", "final.png"}
    assert [v["filename"] for v in r["videos"]] == ["anim.gif"]


def test_fetch_result_filter_keeps_only_primary_node(monkeypatch):
    _patch(monkeypatch)
    r = comfyui_client.fetch_result("http://127.0.0.1:8188", "pid", ["20"])
    assert [i["filename"] for i in r["images"]] == ["final.png"]
    assert [v["filename"] for v in r["videos"]] == ["anim.gif"]


def test_gif_in_images_reclassified_as_video(monkeypatch):
    hist = {"pid": {"status": {"completed": True}, "outputs": {
        "1": {"images": [{"filename": "clip.gif", "subfolder": "", "type": "output"}]},
    }}}
    monkeypatch.setattr(comfyui_client, "urlopen", lambda *a, **k: _FakeResp(hist))
    r = comfyui_client.fetch_result("http://127.0.0.1:8188", "pid")
    assert r["images"] == []
    assert [v["filename"] for v in r["videos"]] == ["clip.gif"]
