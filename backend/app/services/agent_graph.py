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

from typing import TypedDict, Iterator

from app.services import image_gen, generation_store
from app.services import llm as _llm
from app.services.agent_contracts import RunContext


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
    _interrupted: bool
    # 下方是执行上下文（构图时注入，专家节点用）
    _ctx: RunContext


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

# 有 MCP 外部工具时，供 supervisor 额外分派的选项（查资料/读写文件/数据库等需外部工具的任务）
_SUPERVISOR_TOOL_OPTION = (
    "- tool_agent：用户请求需要外部工具才能完成（查资料/联网抓取/读写文件/查数据库/"
    "调用已接入的第三方服务），或需要「先用工具再生图」这类跨工具串联\n"
)


def _supervisor_route(text: str, ctx: dict) -> str:
    """supervisor 用（快）模型判分派。带最近对话上下文（多轮记忆），失败兜底 generate。
    ctx['has_mcp'] 为真时才把 tool_agent 作为可选分派（无 MCP 时零影响，选项都不出现）。
    ctx['chat_fn']（签名同 llm.chat）可注入以便单测分派决策，缺省用 _llm.chat（生产无变化）。"""
    has_mcp = bool(ctx.get("has_mcp"))
    chat_fn = ctx.get("chat_fn") or _llm.chat
    try:
        model = ctx.get("route_model") or ctx["chat_model"]
        system = _SUPERVISOR_SYSTEM
        if has_mcp:
            # 把 tool_agent 选项插在 answer 之前
            system = system.replace("- answer：", _SUPERVISOR_TOOL_OPTION + "- answer：")
        user = _history_text(ctx) + "本轮用户：" + text
        reply = chat_fn(ctx["chat_base"], ctx["chat_key"], model,
                        system, user, temperature=0, proxy=ctx.get("proxy", ""))
        r = (reply or "").strip().lower()
        keys = ("generate", "analyze", "inspire", "tool_agent", "answer") if has_mcp \
            else ("generate", "analyze", "inspire", "answer")
        for k in keys:
            if k in r:
                return k
    except Exception:
        pass
    return "generate"


# ── supervisor 节点：判路由，写 state.route + trace ──

# route → 对应工具开关键（自定义预设可关掉某能力，关掉则回退 answer）
_ROUTE_TOOL = {"generate": "generate_image", "img2img": "image_to_image",
               "analyze": "analyze_image", "inspire": "search_inspiration"}


def supervisor_node(state: AgentState) -> dict:
    ctx = state.get("_ctx", {})
    text = state.get("user_text", "")
    has_images = bool(state.get("images"))
    route = _rule_route(text, has_images) or _supervisor_route(text, ctx)
    # 无 MCP 却误判出 tool_agent（理论上选项都没给它，兜底）→ 回退对话
    if route == "tool_agent" and not ctx.get("has_mcp"):
        route = "answer"
    # 自定义预设关掉了该专家对应工具 → 回退对话（与单 agent 物理裁剪工具集对齐）
    cfg = ctx.get("agent_cfg")
    tool_key = _ROUTE_TOOL.get(route)
    if cfg is not None and tool_key and not _tool_on(cfg, tool_key):
        route = "answer"
    label = {"generate": "生图专家", "img2img": "图生图专家", "analyze": "反推专家",
             "inspire": "灵感专家", "tool_agent": "工具专家", "answer": "对话"}.get(route, route)
    trace = state.get("trace", []) + [f"🧭 主管分派 → {label}"]
    return {"route": route, "trace": trace}


# ── 专家节点：直接调底层服务（不复用 image_agent 闭包工具，零耦合）──

def _gen_ctx(ctx: dict):
    return (ctx["gen_base"], ctx["gen_key"], ctx["gen_model"], ctx["thread_id"],
            ctx["repo_id"], ctx["output_dir"], ctx["embed_base"], ctx["embed_key"], ctx["embed_model"])


def _styled_prompt(ctx: dict, prompt: str) -> str:
    """选了自定义风格存档时，先让对话模型按风格写法把用户原话改写成生图提示词。
    未选风格 → 原样返回（不额外调模型，省 token/延迟；与生图专家默认直连行为一致）。
    对齐单 agent：单 agent 靠大脑按风格写好提示词再生图，这里补上多 Agent 缺的这一环。"""
    tpl = (ctx.get("style_template") or "").strip()
    if not tpl:
        return prompt
    try:
        from app.services.image_prompt_style import guidance_for
        system = "你是生图提示词工程师。" + guidance_for("", ctx.get("gen_model", ""), tpl) + "\n只输出最终提示词本身，不要解释、不要引号。"
        out = _llm.chat(ctx["chat_base"], ctx["chat_key"], ctx["chat_model"],
                        system, prompt, temperature=0.5, proxy=ctx.get("proxy", ""))
        return out.strip() or prompt
    except Exception:  # noqa: BLE001
        return prompt


def generate_node(state: AgentState) -> dict:
    ctx = state["_ctx"]
    prompt = _styled_prompt(ctx, state.get("user_text", ""))
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
    prompt = _styled_prompt(ctx, state.get("user_text", ""))
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
        # 选了自定义风格存档时附加写法指引（与单 agent analyze_image 的 style_hint 对齐）
        style_hint = ""
        if (ctx.get("style_template") or "").strip():
            try:
                from app.services.image_prompt_style import guidance_for
                style_hint = "\n" + guidance_for("", ctx.get("gen_model", ""), ctx["style_template"])
            except Exception:  # noqa: BLE001
                pass
        resp = model.invoke([
            SystemMessage(content="如实完整描述这张图用于再次生成：主体/人物/服饰/动作/背景/光影/构图/画风/画质。"
                          + style_hint + "\n只输出提示词本身。"),
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


def tool_agent_node(state: AgentState) -> dict:
    """通用工具专家：直接跑单 agent 的完整 ReAct 大脑(内置生图/反推/灵感 + MCP 工具 + 自主串联)。
    吸收单 agent 唯一独占的 MCP 能力，是淘汰单 agent 的承接节点。走 image_agent.stream_agent，
    其 checkpointer 已自动记本轮对话进 chat_memory → 本节点被走时置 _used_tool_agent，末尾跳过 _persist_turn 防双写。"""
    from app.services import image_agent
    ctx = state["_ctx"]
    text = state.get("user_text", "")
    imgs = state.get("images", [])
    gb, gk, gm, tid, rid, od, eb, ek, em = _gen_ctx(ctx)
    trace = state.get("trace", []) + ["🛠️ 工具专家执行中…"]
    result_text: list[str] = []
    image_recs: list[dict] = []
    insp_cards: list[dict] = []
    interrupted = False
    try:
        for ev in image_agent.stream_agent(
            tid, text, imgs or None, ctx["chat_base"], ctx["chat_key"], ctx["chat_model"],
            gb, gk, gm, ctx.get("size", "1024x1024"), od, rid, eb, ek, em,
            cancel_event=ctx.get("cancel_event"), proxy_url=ctx.get("proxy", ""),
            style_template=ctx.get("style_template", ""), agent_id=ctx.get("agent_id", ""),
            memory_mode="external_turn",
        ):
            if ev.get("interrupted"):
                interrupted = True
            if ev.get("delta"):
                result_text.append(ev["delta"])
            if ev.get("image"):
                image_recs.append({"id": ev.get("image_id"), "url": ev["image"]})
            if ev.get("inspiration"):
                insp_cards.append(ev["inspiration"])
            if ev.get("error"):
                result_text.append(f"（工具专家出错：{ev['error']}）")
    except Exception as e:  # noqa: BLE001
        result_text.append(f"工具专家执行失败：{e}")
    return {"result_text": "".join(result_text).strip(), "image_recs": image_recs,
            "insp_cards": insp_cards, "trace": trace, "_interrupted": interrupted}


def answer_node(state: AgentState) -> dict:
    ctx = state["_ctx"]
    text = state.get("user_text", "")
    trace = state.get("trace", []) + ["💬 对话中…"]
    try:
        system = _agent_system(ctx, "你是绘画助手，简洁中文回答用户问题。")
        user = _history_text(ctx) + text
        reply = _llm.chat(ctx["chat_base"], ctx["chat_key"], ctx["chat_model"],
                         system, user, temperature=_temperature(ctx, 0.5), proxy=ctx.get("proxy", ""))
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
    g.add_node("tool_agent", tool_agent_node)
    g.add_node("answer", answer_node)
    g.set_entry_point("supervisor")
    # 条件边：按 supervisor 判出的 route 跳到对应专家
    g.add_conditional_edges("supervisor", lambda s: s.get("route", "answer"),
                            {"generate": "generate", "img2img": "img2img", "analyze": "analyze",
                             "inspire": "inspire", "tool_agent": "tool_agent", "answer": "answer"})
    # 单专家任务：干完直接 END，不回 supervisor 二次判断（慢中转下省一次往返）
    for n in ("generate", "img2img", "analyze", "inspire", "tool_agent", "answer"):
        g.add_edge(n, END)
    return g.compile()


_GRAPH = None


def _graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = _build_graph()
    return _GRAPH


def _resolve_agent_cfg(agent_id: str) -> dict | None:
    """读自定义 Agent 预设：空 agent_id / 查不到 → None（走内置默认，与单 agent 一致）。"""
    if not (agent_id or "").strip():
        return None
    try:
        from app.services import agent_store
        return agent_store.get_agent(agent_id)
    except Exception:  # noqa: BLE001
        return None


def _resolve_skills(agent_cfg: dict | None) -> list[str]:
    """技能提示词片段：有预设按其 skillIds（空=不用），无预设用全部已启用（与单 agent 一致）。"""
    try:
        from app.services import skills_store
        if agent_cfg is not None:
            return skills_store.fragments_by_ids(agent_cfg.get("skillIds") or [])
        return skills_store.enabled_prompt_fragments()
    except Exception:  # noqa: BLE001
        return []


def _tool_on(agent_cfg: dict | None, key: str) -> bool:
    """工具开关：无预设全开（原行为）；有预设按其 tools 配置，缺省 True。"""
    if agent_cfg is None:
        return True
    return ((agent_cfg.get("tools") or {}).get(key, True))


def _has_mcp(agent_cfg: dict | None) -> bool:
    """本轮是否有可用 MCP 外部工具：有预设看其 mcpServerIds 非空；无预设看全局已启用服务器。
    为真才在 supervisor 里放出 tool_agent 分派（无 MCP 时该 route 不激活，与原多 Agent 行为一致）。"""
    try:
        if agent_cfg is not None:
            return bool(agent_cfg.get("mcpServerIds"))
        from app.services import mcp_store
        return bool(mcp_store.enabled_servers())
    except Exception:  # noqa: BLE001
        return False


def _recent_history(thread_id: str, turns: int = 6) -> list[dict]:
    """取最近几轮纯文本历史（多轮记忆）：与单 agent 同库(chat_memory)，回填 supervisor/answer 上下文。"""
    try:
        from app.services import chat_memory
        hist = chat_memory.get_history(thread_id)
        return [{"role": h["role"], "content": h["content"]} for h in hist[-turns:] if h.get("content")]
    except Exception:  # noqa: BLE001
        return []


def _history_text(ctx: dict) -> str:
    """把历史拼成一段可读上下文，供 supervisor/answer 的单轮 prompt 前置。"""
    hist = ctx.get("history") or []
    if not hist:
        return ""
    lines = [("用户" if h["role"] == "user" else "助手") + "：" + h["content"] for h in hist]
    return "【最近对话】\n" + "\n".join(lines) + "\n\n"


def _agent_system(ctx: dict, base: str) -> str:
    """按预设/风格/技能拼 system_prompt（与单 agent _build 对齐）：
    自定义预设的 systemPrompt 完全替换人设，memory 作长期记忆，风格模板+技能追加。"""
    cfg = ctx.get("agent_cfg")
    sp = (cfg.get("systemPrompt").strip() if cfg and (cfg.get("systemPrompt") or "").strip() else base)
    if cfg and (cfg.get("memory") or "").strip():
        sp += "\n\n【长期记忆（关于用户/偏好）】\n" + cfg["memory"].strip()
    st = (ctx.get("style_template") or "").strip()
    if st:
        try:
            from app.services.image_prompt_style import guidance_for
            sp += "\n\n【生图提示词写法】" + guidance_for("", ctx.get("gen_model", ""), st)
        except Exception:  # noqa: BLE001
            pass
    frags = ctx.get("skill_frags") or []
    if frags:
        sp += "\n\n【用户自定义技能】\n" + "\n".join(f"- {f}" for f in frags)
    return sp


def _temperature(ctx: dict, default: float) -> float:
    cfg = ctx.get("agent_cfg")
    if cfg and isinstance(cfg.get("temperature"), (int, float)):
        return cfg["temperature"]
    return default


def stream_multi_agent(context: RunContext) -> Iterator[dict]:
    """运行 supervisor 多 Agent 图；HTTP/SSE wire 由 runner/router 适配。"""
    context.agent_cfg = _resolve_agent_cfg(context.agent_id)
    context.has_mcp = _has_mcp(context.agent_cfg)
    context.history = _recent_history(context.thread_id)
    context.skill_frags = _resolve_skills(context.agent_cfg)
    ctx = context
    message = context.message
    images = context.images
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
    final_text: list[str] = []
    interrupted = False
    try:
        for chunk in _graph().stream(init, {"configurable": {"thread_id": context.thread_id}}):
            # 协作式取消：节点间检查（LangGraph 不支持节点内打断，故粒度到节点边界）
            if context.cancel_event.is_set():
                interrupted = True
                yield {"interrupted": True}
                break
            for _node, upd in chunk.items():
                if not isinstance(upd, dict):
                    continue
                if upd.get("_interrupted"):
                    interrupted = True  # noqa: F841  语义标记，保留可读性
                    yield {"interrupted": True}
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
                    final_text.append(upd["result_text"])
                    yield {"delta": upd["result_text"]}
    except Exception as e:  # noqa: BLE001
        yield {"error": str(e)}
    yield {"done": True}
