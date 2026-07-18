"""comfy_launcher 纯逻辑测试：解释器发现 + 配置读写（不真正拉起进程）。"""
import sys
from pathlib import Path

from app.services import comfy_launcher


def test_find_python_无整合包退回当前解释器(tmp_path):
    # 目录里没有任何候选 python.exe → 用 sys.executable
    assert comfy_launcher.find_python(tmp_path) == sys.executable


def test_find_python_命中内置解释器(tmp_path):
    # base/python/python.exe 存在 → 优先用它
    inner = tmp_path / "python"
    inner.mkdir()
    (inner / "python.exe").write_text("", encoding="utf-8")
    assert comfy_launcher.find_python(tmp_path) == str(inner / "python.exe")


def test_find_python_命中同级整合包(tmp_path):
    # base.parent/python312/python.exe 存在（整合包常见布局）
    base = tmp_path / "ComfyUI"
    base.mkdir()
    sib = tmp_path / "python312"
    sib.mkdir()
    (sib / "python.exe").write_text("", encoding="utf-8")
    assert comfy_launcher.find_python(base) == str(sib / "python.exe")


def test_config_读写往返(tmp_path, monkeypatch):
    cfg_file = tmp_path / "comfy_config.json"
    monkeypatch.setattr(comfy_launcher, "_config_path", lambda: cfg_file)
    comfy_launcher.save_config(r"D:\ComfyUI", "http://127.0.0.1:9999")
    got = comfy_launcher.load_config()
    assert got == {"path": r"D:\ComfyUI", "url": "http://127.0.0.1:9999"}


def test_config_缺失返回默认(tmp_path, monkeypatch):
    monkeypatch.setattr(comfy_launcher, "_config_path", lambda: tmp_path / "nope.json")
    assert comfy_launcher.load_config() == {"path": "", "url": "http://127.0.0.1:8188"}


def test_config_损坏返回默认(tmp_path, monkeypatch):
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(comfy_launcher, "_config_path", lambda: bad)
    assert comfy_launcher.load_config() == {"path": "", "url": "http://127.0.0.1:8188"}


def test_start_已运行则不重复启动(monkeypatch):
    # is_up 返回 True → 直接返回「已在运行」，不 Popen
    monkeypatch.setattr(comfy_launcher.comfyui_client, "is_up", lambda url: True)
    res = comfy_launcher.start(r"D:\whatever", "http://127.0.0.1:8188")
    assert res["running"] is True and res["managed"] is False


def test_start_缺main_py抛LaunchError(tmp_path, monkeypatch):
    monkeypatch.setattr(comfy_launcher.comfyui_client, "is_up", lambda url: False)
    try:
        comfy_launcher.start(str(tmp_path), "http://127.0.0.1:8188")
        assert False, "应抛 LaunchError"
    except comfy_launcher.LaunchError as e:
        assert e.status == 400


def test_restart_按停止等待启动顺序执行(monkeypatch):
    calls = []
    monkeypatch.setattr(comfy_launcher, "stop", lambda url: calls.append(("stop", url)))
    monkeypatch.setattr(comfy_launcher.time, "sleep", lambda seconds: calls.append(("sleep", seconds)))
    monkeypatch.setattr(
        comfy_launcher,
        "start",
        lambda path, url: calls.append(("start", path, url)) or {"running": False},
    )

    result = comfy_launcher.restart("D:/ComfyUI", "http://127.0.0.1:8188")

    assert result == {"running": False}
    assert calls == [
        ("stop", "http://127.0.0.1:8188"),
        ("sleep", 1.5),
        ("start", "D:/ComfyUI", "http://127.0.0.1:8188"),
    ]
