"""Supervisor 多 Agent 系统（LangGraph 手写 StateGraph）。

范式：一个 supervisor 节点判用户意图 → 分派给专家节点（生图/图生图/反推/灵感）→
专家执行完把结果写回 state → 回 supervisor 决定继续或结束。与现有单 agent(image_agent)并存，
走独立端点，默认不启用，用户可切换。学习 LangGraph 编排用。

延迟优化（慢中转下多 agent 更慢，这里做三层短路）：
1. 规则短路：带图直接图生图、明确指令词直接路由，不调 supervisor LLM。
2. supervisor 用快模型判分派（可配），专家用主模型执行。
3. 单专家任务直连 END，不回 supervisor 二次判断。
"""
from __future__ import annotations

from typing import Annotated, TypedDict, Iterator

from app.services import image_gen, generation_store
from app.services import llm as _llm


class AgentState(TypedDict, total=False):
    """图的共享状态。messages 累积对话；route 是 supervisor 判出的下一站；产出写各字段。"""
    messages: list                 # 对话消息（含用户输入、图片）
    route: str                     # supervisor 分派结果：generate/img2img/analyze/inspire/answer/END
    user_text: str                 # 本轮用户文本
    images: list                   # 本轮上传图片 url
    result_text: str               # 专家产出的文本回复
    image_recs: list               # 生图产出 [{id,url}]
    insp_cards: list               # 灵感卡
    trace: list                    # 节点流转轨迹（供 SSE 透出多 agent 协作过程）
    # 下方是执行上下文（构图时注入，专家节点用）
    _ctx: dict


# ── 路由：规则短路 + supervisor LLM 兜底 ──

def _rule_route(text: str, has_images: bool) -> str | None:
    """规则短路：高置信度意图直接路由，返回 None 表示交给 supervisor LLM 判。"""
    t = (text or "").strip().lower()
    if has_images:
        return "img2img"                      # 带图 → 图生图（最强信号，直接短路）
    if any(k in t for k in ["反推", "分析这张", "这张图的提示词", "describe this", "caption"]):
        return "analyze"
    if any(k in t for k in ["参考", "灵感", "流行", "款式", "inspiration", "/find"]):
        return "inspire"
    return None                               # 模糊 → supervisor LLM 判


_SUPERVISOR_SYSTEM = (
    "你是绘画多智能体系统的调度主管。根据用户这句话，判断该分派给哪个专家，只输出一个词：\n"
    "- generate：用户想根据文字描述生成新图（文生图）\n"
    "- analyze：用户想反推/分析某张图的提示词\n"
    "- inspire：用户想找参考、灵感、流行款式（需联网搜）\n"
    "- answer：普通绘画问答/闲聊，不需要生图\n"
    "只输出上述之一，不要解释、不要标点。"
)


def _supervisor_route(text: str, ctx: dict) -> str:
    """supervisor 用（快）模型判分派。失败兜底 generate。"""
    try:
        model = ctx.get("route_model") or ctx["chat_model"]
        reply = _llm.chat(ctx["chat_base"], ctx["chat_key"], model,
                          _SUPERVISOR_SYSTEM, text, temperature=0, proxy=ctx.get("proxy", ""))
        r = (reply or "").strip().lower()
        for k in ("generate", "analyze", "inspire", "answer"):
            if k in r:
                return k
    except Exception:
        pass
    return "generate"


# ── supervisor 节点：判路由，写 state.route + trace ──

def supervisor_node(state: AgentState) -> dict:
    ctx = state.get("_ctx", {})
    text = state.get("user_text", "")
    has_images = bool(state.get("images"))
    route = _rule_route(text, has_images) or _supervisor_route(text, ctx)
    label = {"generate": "生图专家", "img2img": "图生图专家", "analyze": "反推专家",
             "inspire": "灵感专家", "answer": "对话"}.get(route, route)
    trace = state.get("trace", []) + [f"🧭 主管分派 → {label}"]
    return {"route": route, "trace": trace}


# ── 专家节点：直接调底层服务（不复用 image_agent 闭包工具，零耦合）──

def _gen_ctx(ctx: dict):
    return (ctx["gen_base"], ctx["gen_key"], ctx["gen_model"], ctx["thread_id"],
            ctx["repo_id"], ctx["output_dir"], ctx["embed_base"], ctx["embed_key"], ctx["embed_model"])


def generate_node(state: AgentState) -> dict:
    ctx = state["_ctx"]
    prompt = state.get("user_text", "")
    gb, gk, gm, tid, rid, od, eb, ek, em = _gen_ctx(ctx)
    trace = state.get("trace", []) + ["🎨 生图专家执行中…"]
    try:
        url = image_gen.generate(gb, gk, gm, prompt, size=ctx.get("size", "1024x1024"))
        rec = generation_store.persist_image(tid, rid, prompt, url, od, eb, ek, em)
        return {"result_text": f"已生成图片。提示词：{prompt}", "image_recs": [rec], "trace": trace}
    except Exception as e:  # noqa: BLE001
        return {"result_text": f"生图失败：{e}", "trace": trace}


def img2img_node(state: AgentState) -> dict:
    ctx = state["_ctx"]
    prompt = state.get("user_text", "")
    imgs = state.get("images", [])
    gb, gk, gm, tid, rid, od, eb, ek, em = _gen_ctx(ctx)
    trace = state.get("trace", []) + ["🖼️ 图生图专家执行中…"]
    if not imgs:
        return {"result_text": "未找到参考图，无法图生图。", "trace": trace}
    try:
        url = image_gen.generate_with_images(gb, gk, gm, prompt, imgs, size=ctx.get("size", "1024x1024"))
        rec = generation_store.persist_image(tid, rid, prompt, url, od, eb, ek, em)
        return {"result_text": f"已基于 {len(imgs)} 张参考图生成。提示词：{prompt}", "image_recs": [rec], "trace": trace}
    except Exception as e:  # noqa: BLE001
        return {"result_text": f"图生图失败：{e}", "trace": trace}


def analyze_node(state: AgentState) -> dict:
    ctx = state["_ctx"]
    imgs = state.get("images", [])
    trace = state.get("trace", []) + ["🔍 反推专家执行中…"]
    if not imgs:
        return {"result_text": "请先上传要反推的图片。", "trace": trace}
    try:
        from langchain_core.messages import SystemMessage, HumanMessage
        model = _llm.build_model(ctx["chat_base"], ctx["chat_key"], ctx["chat_model"], proxy=ctx.get("proxy", ""))
        resp = model.invoke([
            SystemMessage(content="如实完整描述这张图用于再次生成：主体/人物/服饰/动作/背景/光影/构图/画风/画质。只输出提示词本身。"),
            HumanMessage(content=[{"type": "image_url", "image_url": {"url": imgs[0]}}]),
        ])
        return {"result_text": _llm.flatten_content(resp.content) or "反推无结果。", "trace": trace}
    except Exception as e:  # noqa: BLE001
        return {"result_text": f"反推失败：{e}", "trace": trace}


def inspire_node(state: AgentState) -> dict:
    ctx = state["_ctx"]
    query = state.get("user_text", "")
    trace = state.get("trace", []) + ["💡 灵感专家执行中…"]
    try:
        from app.services import inspiration as _insp
        data = _insp.search_and_refine(query, ctx["chat_base"], ctx["chat_key"], ctx["chat_model"], proxy=ctx.get("proxy", ""))
        if not data.get("prompt"):
            return {"result_text": "未能从搜索结果提炼出提示词。", "trace": trace}
        card = generation_store.persist_inspiration(ctx["thread_id"], data["query"], data["prompt"], data["tags"], data["sources"])
        return {"result_text": f"已生成灵感卡：{data['prompt'][:80]}…", "insp_cards": [card], "trace": trace}
    except Exception as e:  # noqa: BLE001
        return {"result_text": f"找灵感失败：{e}", "trace": trace}


def answer_node(state: AgentState) -> dict:
    ctx = state["_ctx"]
    text = state.get("user_text", "")
    trace = state.get("trace", []) + ["💬 对话中…"]
    try:
        reply = _llm.chat(ctx["chat_base"], ctx["chat_key"], ctx["chat_model"],
                         "你是绘画助手，简洁中文回答用户问题。", text, temperature=0.5, proxy=ctx.get("proxy", ""))
        return {"result_text": reply or "（无回复）", "trace": trace}
    except Exception as e:  # noqa: BLE001
        return {"result_text": f"回答失败：{e}", "trace": trace}


# ── 组装 StateGraph：supervisor 判路由 → 条件边分派专家 → 专家 END（单专家直连不回交，省往返）──

def _build_graph():
    from langgraph.graph import StateGraph, END
    g = StateGraph(AgentState)
    g.add_node("supervisor", supervisor_node)
    g.add_node("generate", generate_node)
    g.add_node("img2img", img2img_node)
    g.add_node("analyze", analyze_node)
    g.add_node("inspire", inspire_node)
    g.add_node("answer", answer_node)
    g.set_entry_point("supervisor")
    # 条件边：按 supervisor 判出的 route 跳到对应专家
    g.add_conditional_edges("supervisor", lambda s: s.get("route", "answer"),
                            {"generate": "generate", "img2img": "img2img", "analyze": "analyze",
                             "inspire": "inspire", "answer": "answer"})
    # 单专家任务：干完直接 END，不回 supervisor 二次判断（慢中转下省一次往返）
    for n in ("generate", "img2img", "analyze", "inspire", "answer"):
        g.add_edge(n, END)
    return g.compile()


_GRAPH = None


def _graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = _build_graph()
    return _GRAPH


def stream_multi_agent(thread_id: str, message: str, images: list[str] | None,
                       chat_base: str, chat_key: str, chat_model: str,
                       gen_base: str, gen_key: str, gen_model: str,
                       size: str = "1024x1024", output_dir: str = "", repo_id: str = "",
                       embed_base: str = "", embed_key: str = "", embed_model: str = "embedding-3",
                       proxy_url: str = "", route_model: str = "") -> Iterator[dict]:
    """运行 supervisor 多 agent 图，逐节点产出事件 dict（供 SSE 透出协作过程）：
    {"trace": "🧭 主管分派 → 生图专家"} 流转轨迹；{"image": url}；{"insp": card}；{"delta": text}；末尾 {"done": True}。
    """
    ctx = {
        "chat_base": chat_base, "chat_key": chat_key, "chat_model": chat_model,
        "route_model": route_model, "gen_base": gen_base, "gen_key": gen_key, "gen_model": gen_model,
        "thread_id": thread_id, "repo_id": repo_id or thread_id, "output_dir": output_dir,
        "embed_base": embed_base, "embed_key": embed_key, "embed_model": embed_model,
        "size": size, "proxy": proxy_url,
    }
    from langchain_core.messages import HumanMessage
    content: list = [{"type": "text", "text": message}]
    for u in (images or []):
        content.append({"type": "image_url", "image_url": {"url": u}})
    init: AgentState = {
        "messages": [HumanMessage(content=content)], "user_text": message,
        "images": images or [], "trace": [], "_ctx": ctx,
    }
    seen_trace = 0
    emitted_imgs: set = set()
    emitted_cards: set = set()
    try:
        for chunk in _graph().stream(init, {"configurable": {"thread_id": thread_id}}):
            for _node, upd in chunk.items():
                if not isinstance(upd, dict):
                    continue
                for line in (upd.get("trace") or [])[seen_trace:]:
                    yield {"trace": line}
                seen_trace = len(upd.get("trace") or []) if upd.get("trace") else seen_trace
                for rec in upd.get("image_recs") or []:
                    if rec.get("id") not in emitted_imgs:
                        emitted_imgs.add(rec.get("id"))
                        yield {"image": rec.get("url"), "id": rec.get("id")}
                for card in upd.get("insp_cards") or []:
                    cid = card.get("id")
                    if cid not in emitted_cards:
                        emitted_cards.add(cid)
                        yield {"insp": card}
                if upd.get("result_text"):
                    yield {"delta": upd["result_text"]}
    except Exception as e:  # noqa: BLE001
        yield {"error": str(e)}
    yield {"done": True}


