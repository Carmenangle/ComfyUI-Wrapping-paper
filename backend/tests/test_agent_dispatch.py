"""Supervisor 分派决策的单元测试：只测「这句话该派给哪个专家」的控制流，
不跑 langgraph 整图、不碰真 LLM。注入假 chat_fn 喂固定分派词，覆盖：
规则短路(带图/关键词) → LLM 兜底 → MCP 门控 → 预设关工具回退 → 异常兜底 generate。"""
from app.services import agent_graph as ag


def _ctx(**over) -> dict:
    """造 supervisor 用的最小 ctx（dict 即可，节点只 .get 取值）。"""
    base = {"chat_base": "b", "chat_key": "k", "chat_model": "m"}
    base.update(over)
    return base


def _route(text, *, images=None, ctx=None) -> str:
    """跑一次 supervisor_node，返回它判出的 route。"""
    state = {"user_text": text, "images": images or [], "_ctx": ctx or _ctx()}
    return ag.supervisor_node(state)["route"]


# ── 规则短路：不调 LLM 就能定 ──

def test_带图直接图生图():
    # chat_fn 若被调用就炸，证明带图是纯规则短路、不碰 LLM
    def boom(*a, **k):
        raise AssertionError("带图不应调用 supervisor LLM")
    assert _route("随便画", images=["x.png"], ctx=_ctx(chat_fn=boom)) == "img2img"


def test_反推关键词短路():
    assert _route("反推这张图的提示词", ctx=_ctx(chat_fn=lambda *a, **k: "answer")) == "analyze"


def test_灵感关键词短路():
    assert _route("找点参考灵感", ctx=_ctx(chat_fn=lambda *a, **k: "answer")) == "inspire"


# ── 模糊输入 → 注入的假 LLM 定夺 ──

def test_模糊输入走LLM分派():
    assert _route("帮我弄个赛博朋克城市", ctx=_ctx(chat_fn=lambda *a, **k: "generate")) == "generate"


def test_LLM返回answer被采纳():
    assert _route("今天天气如何", ctx=_ctx(chat_fn=lambda *a, **k: "answer")) == "answer"


def test_LLM异常兜底generate():
    def boom(*a, **k):
        raise RuntimeError("上游炸了")
    assert _route("这句话很模糊", ctx=_ctx(chat_fn=boom)) == "generate"


# ── MCP 门控：无 MCP 时 tool_agent 不生效 ──

def test_无MCP时toolagent不在候选内兜底generate():
    # 无 MCP → 候选词不含 tool_agent，LLM 硬吐 tool_agent 匹配不上 → 落到默认 generate
    assert _route("查点资料", ctx=_ctx(chat_fn=lambda *a, **k: "tool_agent")) == "generate"


def test_有MCP时toolagent生效():
    ctx = _ctx(chat_fn=lambda *a, **k: "tool_agent", has_mcp=True)
    assert _route("查资料再生图", ctx=ctx) == "tool_agent"


# ── 预设工具开关：关掉专家对应工具 → 回退 answer ──

def test_预设关掉生图工具回退answer():
    ctx = _ctx(chat_fn=lambda *a, **k: "generate",
               agent_cfg={"tools": {"generate_image": False}})
    assert _route("画只猫", ctx=ctx) == "answer"


def test_预设未关工具正常分派():
    ctx = _ctx(chat_fn=lambda *a, **k: "generate",
               agent_cfg={"tools": {"generate_image": True}})
    assert _route("画只猫", ctx=ctx) == "generate"
