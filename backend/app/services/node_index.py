"""ComfyUI 节点知识库：扫描已装节点 → 按包(python_module)归拢 → 存进 RAG。

一个 python_module(=一个 GitHub 项目/custom_nodes 目录) = 一条知识点。
内容优先取 object_info 自带 description(省 token)，供 AI 搭工作流时语义检索。
增量同步：对比当前 object_info 的包与已入库的，只处理新增/变更。
同步在后台线程跑并实时上报进度（done/total/当前包名），前端轮询 /nodes/sync-progress 显示。
"""
import threading

from app.services import comfyui_client as _cc
from app.services import rag_store as _rag
from app.services.rag_store import EmbedConfig


# 同步进度（进程内单例，同一时刻只允许一个同步任务）：
#   running 是否在跑，done/total 已处理/总包数，current 当前包名，
#   synced/skipped 结果计数，error 失败信息，finished 是否已结束。
_PROGRESS: dict = {"running": False, "done": 0, "total": 0, "current": "",
                   "synced": 0, "skipped": 0, "error": "", "finished": False}
_LOCK = threading.Lock()


def _set_progress(**kw) -> None:
    with _LOCK:
        _PROGRESS.update(kw)


def sync_progress() -> dict:
    """当前同步进度快照，供前端轮询。"""
    with _LOCK:
        return dict(_PROGRESS)


def _pack_id(python_module: str) -> str:
    """稳定包 id：去掉 custom_nodes. 前缀，内置节点归到 'core'。"""
    pm = python_module or ""
    if pm.startswith("custom_nodes."):
        return pm[len("custom_nodes."):]
    return pm or "core"


def _group_by_pack(object_info: dict) -> dict[str, dict]:
    """把 {节点名: schema} 按 python_module 归拢成 {pack_id: {title, module, nodes:[...]}}。"""
    packs: dict[str, dict] = {}
    for name, info in object_info.items():
        pm = info.get("python_module", "") or "nodes"
        pid = _pack_id(pm)
        pack = packs.setdefault(pid, {
            "title": pid, "python_module": pm, "nodes": [], "categories": set(),
        })
        pack["nodes"].append({
            "name": name,
            "display": info.get("display_name", "") or name,
            "desc": (info.get("description", "") or "").strip(),
            "category": info.get("category", "") or "",
        })
        top = (info.get("category", "") or "").split("/")[0]
        if top:
            pack["categories"].add(top)
    return packs


def _pack_content(pack: dict) -> str:
    """把一个包的所有节点汇总成一段知识点文本(name·display·desc·category)。"""
    lines = [f"节点包：{pack['title']}（来源 {pack['python_module']}）"]
    for n in pack["nodes"]:
        seg = f"- {n['name']}"
        if n["display"] and n["display"] != n["name"]:
            seg += f"（{n['display']}）"
        if n["category"]:
            seg += f" [{n['category']}]"
        if n["desc"]:
            seg += f"：{n['desc']}"
        lines.append(seg)
    return "\n".join(lines)


def start_sync(comfy_url: str, cfg: EmbedConfig, full: bool = False) -> dict:
    """启动后台同步。先同步取 object_info（未运行立刻抛 ComfyError 让前端报错），
    再开线程逐包处理并上报进度。返回 {total_packs}（总包数，前端拿去显示 x/total）。
    已有任务在跑时拒绝重复启动。"""
    with _LOCK:
        if _PROGRESS["running"]:
            return {"total_packs": _PROGRESS["total"], "already_running": True}

    object_info = _cc.fetch_object_info(comfy_url)  # 未运行会抛 ComfyError
    packs = _group_by_pack(object_info)
    total = len(packs)
    _set_progress(running=True, done=0, total=total, current="",
                  synced=0, skipped=0, error="", finished=False)

    def _run():
        try:
            _do_sync(packs, cfg, full)
            _set_progress(running=False, finished=True, current="")
        except Exception as e:  # noqa: BLE001 后台线程兜底，错误进度里报
            _set_progress(running=False, finished=True, error=str(e), current="")

    threading.Thread(target=_run, daemon=True).start()
    return {"total_packs": total, "already_running": False}


def _do_sync(packs: dict[str, dict], cfg: EmbedConfig, full: bool) -> None:
    """实际逐包入库，每包更新进度。供后台线程调用。"""
    existing = {p["id"]: p for p in _rag.list_node_packs(cfg)}
    synced = 0
    skipped = 0
    done = 0
    for pid, pack in packs.items():
        _set_progress(current=pid)
        node_names = [n["name"] for n in pack["nodes"]]
        prev = existing.get(pid)
        # 增量跳过条件：已存在且节点集合未变（数量+名字一致）
        if not full and prev and set(prev.get("node_names", [])) == set(node_names):
            skipped += 1
        else:
            _rag.index_node_pack(
                cfg, pack_id=pid, title=pack["title"], content=_pack_content(pack),
                node_names=node_names, categories=sorted(pack["categories"]),
                python_module=pack["python_module"],
            )
            synced += 1
        done += 1
        _set_progress(done=done, synced=synced, skipped=skipped)


def search(cfg: EmbedConfig, need: str, k: int = 8) -> list[dict]:
    """按需求语义检索相关节点包，供搭工作流选节点。返回包列表(含节点清单)。"""
    return _rag.search_node_packs(cfg, need, k=k)


def suggest_alternatives(cfg: EmbedConfig, missing_names: list[str],
                         object_info_keys: set, k: int = 6) -> dict[str, list[str]]:
    """为「本机没装的节点」检索本机已装的同类平替（纯检索，不调对话模型，不会卡）。

    做法：用缺失节点名(拆词做 query)检索知识库→在命中包的 node_names 里挑**本机确实存在**
    (在 object_info_keys 里)的同类节点作为平替候选。返回 {缺失节点名: [平替1, 平替2, ...]}。
    治「AI 想用某能力但编了本机没有的节点」——给它本机真实的同类替代，而不是硬编白名单。"""
    import re
    out: dict[str, list[str]] = {}
    for miss in missing_names:
        # 缺失名拆成词做 query（llama_cpp_instruct → "llama cpp instruct"）
        q = " ".join(re.split(r"[_\-.|\s]+", miss))
        try:
            packs = _rag.search_node_packs(cfg, q, k=k)
        except Exception:
            packs = []
        alts: list[str] = []
        for p in packs:
            for n in p.get("node_names", []):
                if n in object_info_keys and n != miss and n not in alts:
                    alts.append(n)
        out[miss] = alts[:8]  # 每个缺失节点最多给 8 个平替，控量
    return out


_REWRITE_SYSTEM = (
    "你是 ComfyUI 检索助手。用户给一段搭工作流的需求，你只输出一行**空格分隔的检索关键词**，"
    "用于从节点库里召回相关节点包。要点：\n"
    "- 抽出用户点名的具体节点名（如 Any Switch、rgthree、KSampler、UNETLoader、VAEEncode）——原样保留英文名；\n"
    "- 抽出关键能力词（如 模型切换 图生图 反推 采样 放大 controlnet 视频）；\n"
    "- 中英都要（英文名利于精确匹配，中文词利于语义）；不要解释、不要标点，只输出关键词行。"
)


def rewrite_query(need: str, chat_fn, base_url: str, api_key: str, model: str, proxy: str = "") -> str:
    """查询重写：让对话模型从需求里抽关键节点名/能力词，拼到原 query 后增强检索召回。
    失败(模型不可用等)则返回原 need，不阻断。chat_fn 传 ai_common.chat 以复用其错误处理与代理。"""
    if not (base_url and model):
        return need
    try:
        # retries=1 快速失败：重写只是锦上添花（控制流节点已由 _with_control_flow 兜底注入），
        # 慢模型下别让它带退避重试拖时间——失败就直接用原 need，把时间预算留给主生成。
        kw = chat_fn(base_url, api_key, model, _REWRITE_SYSTEM, need, temperature=0.0, proxy=proxy, retries=1)
        kw = (kw or "").strip().replace("\n", " ")
        # 原需求 + 抽出的关键词，一起喂检索（BM25 关键词命中 + 向量语义双保险）
        return f"{need} {kw}" if kw else need
    except Exception:
        return need


def stats(cfg: EmbedConfig) -> dict:
    """知识库现状：包数 + 节点总数。"""
    packs = _rag.list_node_packs(cfg)
    return {
        "packs": len(packs),
        "nodes": sum(len(p.get("node_names", [])) for p in packs),
    }


def list_packs(cfg: EmbedConfig) -> list[dict]:
    """列出全部节点包（id/标题/节点数/来源），供管理页展示。按标题排序。"""
    packs = _rag.list_node_packs(cfg)
    packs.sort(key=lambda p: p.get("title", "").lower())
    return [{
        "id": p["id"], "title": p["title"],
        "node_count": len(p.get("node_names", [])),
        "python_module": p.get("python_module", ""),
    } for p in packs]


def get_pack(cfg: EmbedConfig, pack_id: str) -> dict | None:
    """读单个包完整内容（含用途正文 content），供查看/编辑。"""
    return _rag.get_node_pack(cfg, pack_id)


def update_pack_content(cfg: EmbedConfig, pack_id: str, content: str) -> bool:
    """人工改某包的用途正文并重嵌入。包不存在返回 False。"""
    return _rag.update_node_pack_content(cfg, pack_id, content)

