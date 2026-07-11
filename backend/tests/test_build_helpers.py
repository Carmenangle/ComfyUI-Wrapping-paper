"""搭工作流纯 helper 测试：脱离 live ComfyUI/模型验证从路由下沉到服务层的纯逻辑。
覆盖 JSON 抽取容错、节点清单控量、控制流兜底注入、点名节点抽取、prompt 瘦身。"""
from app.services import workflow_builder as wb


def test_extract_json_去围栏():
    assert wb._extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert wb._extract_json('前言{"a": 1}后语') == {"a": 1}


def test_extract_json_无json抛错():
    import pytest
    with pytest.raises(ValueError):
        wb._extract_json("没有大括号")


def test_trim_catalog_超长截断():
    packs = [{"content": "x" * 5000}]
    out = wb._trim_catalog(packs, per_pack=100, total=12000)
    assert "已截断" in out and len(out) < 5000


def test_trim_catalog_总量封顶省略():
    packs = [{"content": "a" * 80}, {"content": "b" * 80}, {"content": "c" * 80}]
    out = wb._trim_catalog(packs, per_pack=200, total=100)
    assert "因篇幅省略" in out


def test_with_control_flow_只补本机存在的():
    oi = {"Any Switch (rgthree)": {}, "KSampler": {}}
    out = wb._with_control_flow(["KSampler"], oi)
    assert "Any Switch (rgthree)" in out          # 存在→补
    assert "ImpactSwitch" not in out              # 不在 object_info→跳过
    assert out.count("KSampler") == 1             # 去重保序


def test_named_nodes_in_text_抽点名节点():
    oi = {"KSampler": {}, "VAEDecode": {"display_name": "VAE 解码"}}
    hits = wb._named_nodes_in_text("请用 KSampler 采样再 VAE 解码", oi)
    assert "KSampler" in hits and "VAEDecode" in hits


def test_slim_graph_保连线省widget():
    base = {"1": {"class_type": "KSampler",
                  "inputs": {"model": ["2", 0], "seed": 12345, "text": "a" * 50}}}
    slim = wb._slim_graph_for_prompt(base)
    assert slim["1"]["inputs"]["model"] == ["2", 0]   # 连线原样留
    assert slim["1"]["inputs"]["seed"] == "…"          # 标量占位
    assert slim["1"]["inputs"]["text"].endswith("…")   # 长文本截断
