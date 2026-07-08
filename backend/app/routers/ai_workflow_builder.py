"""AI 搭工作流端点：同步节点知识库 + 按需求自动搭建工作流。

搭建流程（用户「必接口优先」思路，AI 在 workflow_builder 的校验闭环内迭代）：
  需求 → 检索相关节点包(node_index) → 喂精简节点清单给对话模型 →
  AI 生成 API 格式 graph → validate_graph 校验 → 有错回喂 AI 重连(最多 N 次) →
  合法则存到 workflowDir。
节点库同步是独立端点，供前端「同步节点库」按钮与首次使用调用。
"""
import json

from fastapi import APIRouter, HTTPException

from pydantic import BaseModel

from app.routers.ai_common import EmbedModelReq
from app.services import (
    node_index, workflow_builder, workflow_merge, comfyui_client, skeleton_store,
    build_session_store,
)
from app.services.comfyui_client import ComfyError

router = APIRouter()


class SyncNodesRequest(EmbedModelReq):
    comfy_url: str = "http://127.0.0.1:8188"
    full: bool = False                 # True 全量重建，False 增量


@router.post("/nodes/sync")
def sync_nodes(req: SyncNodesRequest) -> dict:
    """启动后台同步：扫描 ComfyUI 已装节点，按包逐个入库。ComfyUI 未运行报 502。
    立即返回 {total_packs}，进度经 /nodes/sync-progress 轮询。"""
    try:
        return node_index.start_sync(req.comfy_url, req.embed_cfg(), full=req.full)
    except ComfyError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)


@router.get("/nodes/sync-progress")
def sync_progress() -> dict:
    """同步进度快照：{running, done, total, current, synced, skipped, error, finished}。"""
    return node_index.sync_progress()


class NodeStatsRequest(EmbedModelReq):
    pass


@router.post("/nodes/stats")
def node_stats(req: NodeStatsRequest) -> dict:
    """节点知识库现状：包数 + 节点数。空库提示先同步。"""
    return node_index.stats(req.embed_cfg())


@router.post("/nodes/packs")
def node_packs(req: NodeStatsRequest) -> dict:
    """列出全部节点包（管理页展示，含节点数/来源）。"""
    return {"packs": node_index.list_packs(req.embed_cfg())}


class PackIdReq(EmbedModelReq):
    pack_id: str = ""


@router.post("/nodes/pack")
def node_pack(req: PackIdReq) -> dict:
    """读单个包完整内容（含用途正文，供查看/编辑）。"""
    p = node_index.get_pack(req.embed_cfg(), req.pack_id)
    if p is None:
        raise HTTPException(status_code=404, detail="节点包不存在")
    return p


class UpdatePackReq(EmbedModelReq):
    pack_id: str = ""
    content: str = ""


@router.post("/nodes/pack/update")
def update_node_pack(req: UpdatePackReq) -> dict:
    """人工修订某包的用途正文并重嵌入。"""
    ok = node_index.update_pack_content(req.embed_cfg(), req.pack_id, req.content)
    if not ok:
        raise HTTPException(status_code=404, detail="节点包不存在")
    return {"ok": True}


# —— 骨架底座：AI 搭工作流的正确起点 ——

class SkeletonListReq(BaseModel):
    workflow_dir: str = ""


@router.post("/skeletons")
def skeletons(req: SkeletonListReq) -> dict:
    """列出骨架候选：内置精简骨架 + 用户工作流文件夹里的 .json。"""
    return {"skeletons": skeleton_store.list_skeletons(req.workflow_dir)}


class SkeletonGraphReq(BaseModel):
    skeleton_id: str = ""
    workflow_dir: str = ""


@router.post("/skeleton/graph")
def skeleton_graph(req: SkeletonGraphReq) -> dict:
    """按 id 取骨架 graph（load 进画布用）。内置直接返回，文件只读不改。"""
    g = skeleton_store.get_skeleton_graph(req.skeleton_id, req.workflow_dir)
    if g is None:
        raise HTTPException(status_code=404, detail="骨架不存在")
    return {"graph": g}


class BuildRequest(EmbedModelReq):
    need: str = ""                     # 自然语言需求，如"文生图基础流"
    comfy_url: str = "http://127.0.0.1:8188"
    workflow_dir: str = ""             # 落盘目录（settings.workflowDir）
    name: str = ""                     # 工作流文件名（空则用 need 派生）
    max_retries: int = 4               # 校验失败回喂 AI 重连次数（widget 候选纠错多留 1 轮收敛）
    current_graph: dict = {}           # 当前右侧画布(API格式)，非空=在其基础上增量改
    save: bool = True                  # 是否落盘到 workflow_dir（多轮迭代中途可传 False 只回图）


def _trim_catalog(packs: list[dict], per_pack: int = 1500, total: int = 12000) -> str:
    """把检索命中包拼成节点清单文本，但控量——防超大包(如 easy-use 上百节点全文)撑爆
    单次请求 prompt 触发上游 502/超时。每包正文截断到 per_pack 字符，总量到 total 字符封顶。
    接口表(interface_sheet)已另给真实口/类型，这里只需让 AI 知道有哪些节点可选，长描述可裁。"""
    parts: list[str] = []
    used = 0
    for p in packs:
        c = p.get("content", "") or ""
        if len(c) > per_pack:
            c = c[:per_pack] + f" …(该包内容过长已截断，共{len(p.get('content',''))}字符)"
        if used + len(c) > total:
            parts.append(f"…(还有 {len(packs) - len(parts)} 个相关包因篇幅省略)")
            break
        parts.append(c)
        used += len(c)
    return "\n\n".join(parts)


# 语义检索常捞不到的常用节点：描述短、语义离需求词远，排不进检索前 N，但很常用。
# 强制补进接口表，让 AI 总能看到真实接口，避免它凭印象编不存在的节点名。
_CONTROL_FLOW_NODES = [
    # 控制流开关
    "Any Switch (rgthree)",        # 类型无关多路开关（动态口 any_01/any_02…），最通用
    "Fast Groups Muter (rgthree)",
    "ImpactConditionalBranch",     # 布尔选 tt/ff 两路
    "ImpactSwitch",
    # 视觉反推/看图出词（治「AI 编 LlamaCPP/Qwen2VL 等本机没有的节点」——本机真实节点在这）
    "llama_cpp_model_loader", "llama_cpp_instruct_adv", "llama_cpp_parameters",  # Llama-cpp 视觉反推(本机首选,输出 STRING)
    "QwenTE_ModelLoader", "QwenTE_ImageInfer",   # Qwen 视觉反推
    "BLIPCaption", "DeepDanbooruCaption", "AILab_Florence2",  # 其它反推/打标
    "WD14Tagger|pysssss", "Florence2Run",        # 常见但不一定装（in object_info 才注入）
]


def _missing_hint(missing: list[str], alts: dict | None = None) -> list[str]:
    """把被拆掉的未装节点转成给用户的「推荐安装 + 本机平替」提示（作为 warnings 回前端）。
    alts: {缺失节点: [本机同类平替...]}，有平替就一并告知，让用户知道可换本机已装的。"""
    if not missing:
        return []
    lines = [f"以下节点本机没装，已从工作流里移除：{'、'.join(missing)}。"]
    if alts:
        for miss, sub in alts.items():
            if sub:
                lines.append(f"「{miss}」本机可用同类平替：{'、'.join(sub[:5])}（可让我改用这些重搭）")
    lines.append("若要装缺失的节点：点下方「去安装」按钮会跳到节点管理市场并自动搜索；搜不到就用它给的 Git 链接装。装完「同步节点库」再重搭。")
    return lines


def _with_control_flow(names: list[str], object_info: dict) -> list[str]:
    """在检索命中的节点名后，补入本机确实存在的常用节点（控制流 + 视觉反推，去重保序）。
    治「需求提到某能力但检索没捞到对应节点→接口表里没有→AI 凭印象编不存在的节点名」。
    只补 object_info 里真实存在的，不存在的跳过（不会误导 AI 用没装的节点）。"""
    seen = set(names)
    out = list(names)
    for n in _CONTROL_FLOW_NODES:
        if n not in seen and n in object_info:
            out.append(n)
            seen.add(n)
    return out


def _named_nodes_in_text(text: str, object_info: dict) -> list[str]:
    """从需求/方案文本里抽出被点名的、本机真实存在的节点 class_type。
    治「顾问方案点名了 Llama-cpp 等节点，但执行阶段长文本检索没召回→接口表没有→AI 省略整条链路」。
    匹配两路：①class_type 直接出现在文本里；②display_name(schema.display_name)出现在文本里。
    命中的节点应置顶注入接口表并豁免截断，确保方案点名的节点 AI 一定看得到接口。"""
    if not text:
        return []
    low = text.lower()
    hits: list[str] = []
    for ct, schema in object_info.items():
        if not isinstance(ct, str):
            continue
        disp = ""
        if isinstance(schema, dict):
            disp = str(schema.get("display_name") or "")
        # class_type 较长(≥4)才按子串匹配，避免短名误命中；display_name 完整匹配
        matched = (len(ct) >= 4 and ct.lower() in low) or (len(disp) >= 4 and disp.lower() in low)
        if matched:
            hits.append(ct)
    return hits


def _prioritize(hit_names: list[str], need: str, object_info: dict) -> list[str]:
    """把方案/需求点名的节点置顶到接口表最前（豁免 60 截断），其余保序去重。"""
    named = _named_nodes_in_text(need, object_info)
    if not named:
        return hit_names
    seen = set()
    out: list[str] = []
    for n in [*named, *hit_names]:
        if n not in seen:
            out.append(n)
            seen.add(n)
    return out



_BUILD_SYSTEM = (
    "你是资深 ComfyUI 工作流专家。根据用户需求，用你的专业判断**一次性通盘规划并生成一个"
    "完整、专业、可直接运行的** ComfyUI API prompt 格式工作流（不是片段，是从加载模型到保存输出的整条链）。\n"
    "格式：JSON 对象 {\"节点id\": {\"class_type\": \"节点名\", \"inputs\": {...}}}。\n"
    "连线规则：inputs 里某口的值若是 [\"上游节点id\", 输出序号] 表示接线；否则是 widget 字面值。\n"
    "【专业标准·务必按最佳实践搭，别偷工减料搭最基础版】：\n"
    "- 按模型架构选正确的加载方式：SDXL/SD1.5 等一体式模型用 CheckpointLoaderSimple；"
    "而 Flux、SD3、以及 Anima/UNET 分离式模型，应走 **UNETLoader(单独加载 UNET) + DualCLIPLoader/CLIPLoader(单独加载CLIP) + VAELoader(单独加载VAE)** 的分离式架构，"
    "这是这类模型的正确用法，绝不要图省事套用 checkpoint 一体式。\n"
    "- 需求里提到的每一项能力（如反推、图生图、放大、面部修复）都要在图里真实实现对应链路，不许简化掉。"
    "图生图要有 VAEEncode 把参考图编码进 latent；反推要有对应的看图出词节点链。\n"
    "- 先把必接线口(MODEL/LATENT/CONDITIONING 等大写类型)连成骨架，再填 widget，optional 口按需求接。\n"
    "【节点名以清单为准（防止写错名字），但你的专业能力不受清单限制】：\n"
    "- 【可用节点真实接口】清单给出本机节点的**真实 class_type 和接口**，接线时口名/类型严格照它，"
    "写节点名也以清单里的真实名为准（别凭印象写 LlamaCPP/Qwen2VL 这种可能不对的名字）。\n"
    "- 若你要用的某个节点清单里没列出：先在清单里找**功能同类的替代节点**（如某种 UNET 加载器、某种反推节点）；"
    "清单里确实找不到任何能实现该能力的节点时，才省略该部分，并按你的专业判断把其余部分搭到最完整。\n"
    "- 不要因为清单没列全就退化成最简单的工作流——清单是查真实节点名用的，不是你能力的上限。\n"
    "完整性自检：\n"
    "- 整图必须有输出节点(如 SaveImage)，主链从模型加载一路连通到它，不留断链孤岛；\n"
    "- 每个节点的必接线口都要接上；用到开关/聚合节点(如 Any Switch (rgthree)，动态输入口 "
    "any_01,any_02,…)时，务必既接上游各路来源、又把输出接给下游，不能只接一头；\n"
    "只输出 JSON，不要解释、不要 markdown 代码块围栏。"
)


def _extract_json(text: str) -> dict:
    """从模型输出里抠出 JSON（容错去 ```json 围栏）。失败抛 ValueError。"""
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1] if "```" in t[3:] else t
        t = t[4:] if t.lower().startswith("json") else t
        t = t.strip("`").strip()
    s, e = t.find("{"), t.rfind("}")
    if s < 0 or e < 0:
        raise ValueError("模型未返回 JSON")
    return json.loads(t[s:e + 1])


@router.post("/build")
def build(req: BuildRequest) -> dict:
    """按需求自动搭工作流：检索节点→AI 生成→校验重试→落盘。返回 {ok, path, graph, errors}。"""
    from app.routers.ai_common import chat

    if not req.need.strip():
        raise HTTPException(status_code=400, detail="需求为空")

    # 1. 检索相关节点包（先查询重写抽关键词增强召回，再 Hybrid 检索；整图一次生成 k=12）
    cfg = req.embed_cfg()
    # 不做查询重写（省一次模型往返=省延迟）：控制流/反推节点已由 _with_control_flow 兜底注入，
    # 重写的边际价值低于它的耗时。直接用原需求检索。
    packs = node_index.search(cfg, req.need, k=10)
    if not packs:
        raise HTTPException(status_code=400, detail=(
            f"节点知识库检索为空。收到的嵌入配置 base_url={cfg.base_url!r} model={cfg.embed_model!r}"
            f"（若 base_url 为空说明前端没传嵌入模型配置，请刷新页面/检查设置→嵌入模型）"))
    node_catalog = _trim_catalog(packs)

    # 2. 取全量 object_info 供校验（含每个节点真实 schema）
    try:
        object_info = comfyui_client.fetch_object_info(req.comfy_url)
    except ComfyError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)

    # 接口速查表：命中包里节点的真实口名/类型，AI 据此接线不臆造（见 build_module 同段说明）
    hit_names: list[str] = []
    for p in packs:
        hit_names.extend(p.get("node_names", []))
    hit_names = _with_control_flow(hit_names, object_info)  # 强制补入 Any Switch 等控制流节点
    named = _named_nodes_in_text(req.need, object_info)     # 方案点名的真实节点
    hit_names = _prioritize(hit_names, req.need, object_info)
    sheet = workflow_builder.interface_sheet(hit_names, object_info, priority=set(named))

    # 3. AI 生成 → 校验 → 有错回喂重连
    #    有 current_graph 时，让 AI 在现有画布基础上按新需求增量修改并输出完整新图。
    convo = (
        f"需求：{req.need}\n\n【可用节点清单（文字说明）】\n{node_catalog}"
        + "\n\n【节点真实接口（务必据此接线，口名/类型不得臆造）】\n"
        + "说明：in[] 里 * 是需接线的口(带类型)、? 是可选、= 是填字面值的 widget；out[] 是输出序号:类型。\n"
        + sheet
    )
    if req.current_graph:
        convo += (
            "\n\n【当前画布工作流(API格式)】\n" + json.dumps(req.current_graph, ensure_ascii=False)
            + "\n\n请在上面这个当前画布的基础上，按新需求做增量修改（保留无关部分，只改需要变的），"
            "输出修改后的**完整** JSON。"
        )
    import time as _t
    _deadline = _t.time() + 200  # 总预算 200s（< 前端 240s 超时），到点停止重试返回现有结果
    last_errors: list[str] = []
    graph: dict = {}
    for attempt in range(max(1, req.max_retries)):
        if _t.time() > _deadline:
            break
        reply = chat(req.base_url, req.api_key, req.model, _BUILD_SYSTEM, convo, temperature=0.2, proxy=req.proxy)
        try:
            graph = _extract_json(reply)
        except (ValueError, json.JSONDecodeError) as e:
            last_errors = [f"输出解析失败：{e}"]
            convo += f"\n\n上次输出无法解析为 JSON（{e}），请只输出合法 JSON。"
            continue
        # 用了没装的节点：还有重试就回喂让 AI 换真实节点；没重试了就拆掉+提示安装
        _missing = [nid for nid, n in graph.items()
                    if isinstance(n, dict) and n.get("class_type", "") not in object_info]
        if _missing and attempt < max(1, req.max_retries) - 1:
            types = sorted({graph[i].get("class_type", "") for i in _missing})
            last_errors = [f"用了本机没装的节点：{'、'.join(types)}"]
            convo += ("\n\n上次用了本机没装的节点(" + "、".join(types) +
                      ")，请只用【节点真实接口】里列出的节点重搭；确实没有对应能力的节点就省略那部分。")
            continue
        graph, missing = workflow_builder.split_missing_nodes(graph, object_info)
        workflow_builder.fill_combo_defaults(graph, object_info)  # 先规整 combo 近似值再校验
        errors = workflow_builder.validate_graph(graph, object_info)
        if not errors:
            # 结构审核（悬空/开关单边接/孤岛）——整图模式没"下一轮"，故审核问题也回喂自修
            warnings = workflow_builder.audit_graph(graph, object_info)
            if warnings and attempt < max(1, req.max_retries) - 1:
                last_errors = warnings
                convo += ("\n\n上次工作流能通过类型校验，但结构审核发现下列问题，请修正后重新输出完整 JSON"
                          "（重点：开关节点两头都接、别留悬空节点、主链要连到输出节点）：\n" + "\n".join(warnings))
                continue
            # combo 已在校验前规整过，这里直接落盘
            path = ""
            if req.save:
                path = workflow_builder.save_workflow(graph, req.name or req.need[:20], req.workflow_dir)
            return {"ok": True, "path": path, "graph": graph, "errors": [], "warnings": warnings + _missing_hint(missing)}
        last_errors = errors
        convo += "\n\n上次工作流有以下错误，请修正后重新输出完整 JSON：\n" + "\n".join(errors)

    return {"ok": False, "path": "", "graph": graph, "errors": last_errors}


class SaveRequest(EmbedModelReq):
    graph: dict = {}                   # 手改后的画布(API格式)，直接落盘不经 AI
    workflow_dir: str = ""
    name: str = ""


@router.post("/build/save")
def save(req: SaveRequest) -> dict:
    """把前端手改后的画布 graph 直接落盘，复用 save_workflow，不经 AI。返回 {ok, path}。"""
    if not req.graph:
        raise HTTPException(status_code=400, detail="画布为空")
    try:
        path = workflow_builder.save_workflow(req.graph, req.name, req.workflow_dir)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "path": path}


class ModuleRequest(EmbedModelReq):
    need: str = ""                     # 本模块需求，如"加图生图分支"
    comfy_url: str = "http://127.0.0.1:8188"
    current_graph: dict = {}           # 当前冻结图（AI 不许改，只在其上加模块）
    max_retries: int = 2               # 增量模式重试：慢中转下每轮 opus 都慢，4 次易累计爆 240s→降 2(首次+1次纠错，配 slim 通常够)


def _slim_graph_for_prompt(base: dict) -> dict:
    """把当前图瘦身成「给 AI 看的表示」：保留 id/class_type/所有连线，省掉 widget 标量值。
    治增量模式每轮塞完整图→节点多就 prompt 爆炸/超时。连线拓扑完整保留(中间插入/拆边重连靠它)，
    只把与接线无关的 widget 字面值(seed/steps/cfg/text/ckpt_name 等)替换为占位，长文本截断。
    ⚠只影响发给模型的表示，实际合并用前端另传的完整图，不受影响。"""
    slim: dict = {}
    for nid, node in (base or {}).items():
        if not isinstance(node, dict):
            slim[nid] = node
            continue
        new_inputs = {}
        for k, v in (node.get("inputs") or {}).items():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], (str, int)) and isinstance(v[1], int):
                new_inputs[k] = v                       # 连线 [id, 序号]：原样保留（拓扑关键）
            elif isinstance(v, str) and len(v) > 24:
                new_inputs[k] = v[:24] + "…"             # 长文本(提示词等)截断
            else:
                new_inputs[k] = "…"                       # 其它 widget 标量：占位，接线无关
        slim[nid] = {"class_type": node.get("class_type"), "inputs": new_inputs}
    return slim


_MODULE_SYSTEM = (
    "你是 ComfyUI 工作流的分模块搭建器。给你【当前工作流(API格式，已搭好、冻结不可改)】和一段新需求，"
    "你只输出【本次要新增的模块节点】和它们如何接到当前工作流上，绝不重复或修改已有节点。\n"
    "输出 JSON 对象，两个字段：\n"
    '  "nodes": {"模块内临时id": {"class_type":"节点名", "inputs": {...}}}  —— 只放新增节点；\n'
    "           模块内部互连用这些临时id写 [\"临时id\", 输出序号]；接当前图的口先留空，用 anchors 表达。\n"
    '  "anchors": [ ... ]  —— 跨界连线，每项二选一方向：\n'
    '     正向(新节点某输入口 接 现有节点输出): {"module_node":"临时id","module_input":"口名","base_node":"现有id","base_output":序号}\n'
    '     反向(现有节点某输入口 改接 新节点输出): {"base_node":"现有id","base_input":"口名","module_node":"临时id","module_output":序号}\n'
    "只用【可用节点清单】里出现的节点，绝不虚构。\n"
    "控制流开关（二选一/多选一，用于「文生图还是图生图」「本地还是云端反推」这类切换）：\n"
    "- 用类型无关的开关节点（优先 Any Switch (rgthree)，它对任意类型通用——图/latent/文本/音频/视频都行）；\n"
    "- 【关键·Any Switch (rgthree) 的输入口是动态的】它在接口表里显示 in[] 没有输入口，但实际"
    "接受名为 any_01、any_02、any_03… 的输入口（按顺序编号）。你必须把要切换的**各路来源分别接到 "
    "any_01 / any_02 …**，否则开关没有上游、下游拿不到数据（这是最常见的错误！）；\n"
    "- 完整接法举例（UNET/Checkpoint 二选一给采样器）：把 UNETLoader 的 MODEL 输出接到 Any Switch 的 "
    "any_01，把 CheckpointLoaderSimple 的 MODEL 输出接到 any_02，再把 Any Switch 的输出(序号0)接到 "
    "KSampler 的 model 口。**三条线缺一不可**：两个加载器→开关(any_01/any_02)、开关→采样器。\n"
    "- 用 anchors 表达跨界连线时，module_input 就写 \"any_01\"、\"any_02\" 这样的口名；\n"
    "- 需要按开关信号选路时可配 ImpactConditionalBranch（布尔选 tt/ff 两路）。\n"
    "自检：你新增的每个开关/聚合节点，都必须既有上游(输入口接了来源)又有下游(输出被人用)，不能只接一头。\n"
    "只输出 JSON，不要解释、不要 markdown 围栏。"
)


@router.post("/build/module")
def build_module(req: ModuleRequest) -> dict:
    """分模块增量搭建：AI 只出新模块+锚点 → 后端 ID 安全合并进当前图 → 校验整图 → 重试。
    不落盘，返回 {ok, graph, errors}（graph 为合并后完整图，前端写回画布）。"""
    from app.routers.ai_common import chat

    if not req.need.strip():
        raise HTTPException(status_code=400, detail="需求为空")

    cfg = req.embed_cfg()
    # 不做查询重写（省一次模型往返=省延迟）：控制流/反推节点已由 _with_control_flow 兜底注入，
    # 重写的边际价值低于它的耗时。直接用原需求检索。
    packs = node_index.search(cfg, req.need, k=10)
    if not packs:
        raise HTTPException(status_code=400, detail=(
            f"节点知识库检索为空。收到的嵌入配置 base_url={cfg.base_url!r} model={cfg.embed_model!r}"
            f"（若 base_url 为空说明前端没传嵌入模型配置，请刷新页面/检查设置→嵌入模型）"))
    # 增量模式不用冗长文字 catalog（下方只发接口表），省 token

    try:
        object_info = comfyui_client.fetch_object_info(req.comfy_url)
    except ComfyError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)

    # 接口速查表：检索命中包里节点的**真实输入/输出口+类型**。没有它 AI 只能猜口名/类型，
    # 会选错开关节点、把 BOOLEAN 接进 IMAGE 口（这正是搭建失败的主因）。
    hit_names: list[str] = []
    for p in packs:
        hit_names.extend(p.get("node_names", []))
    hit_names = _with_control_flow(hit_names, object_info)  # 强制补入 Any Switch 等控制流节点
    sheet = workflow_builder.interface_sheet(hit_names, object_info, max_nodes=40)  # 增量加一个模块，40 个够

    base = req.current_graph or {}
    # 增量模式 prompt 瘦身：①不塞冗长文字 catalog（接口表已给真实口/类型）②当前图只发结构+连线，
    # widget 标量值省略为 …（接线无关）。治"节点多就 prompt 爆炸→502/超时"。合并用前端另传的完整图。
    convo = (
        f"新需求：{req.need}\n\n【当前工作流(结构+连线，冻结；widget 值已省略为 …，你只需接线不用管它们)】\n"
        + json.dumps(_slim_graph_for_prompt(base), ensure_ascii=False)
        + f"\n\n【可用节点及真实接口（务必据此接线，口名/类型不得臆造）】\n"
        + "说明：in[] 里 * 是需接线的口(带类型)、? 是可选、= 是填字面值的 widget；out[] 是输出序号:类型。\n"
        + sheet
    )
    import time as _t
    _deadline = _t.time() + 200  # 总预算 200s（< 前端 240s 超时），到点停止再重试，返回现有结果
    last_errors: list[str] = []
    merged: dict = base
    for attempt in range(max(1, req.max_retries)):
        if _t.time() > _deadline:
            break  # 超预算：不再调模型，跳出返回已有 merged（下方按 last_errors 报）
        reply = chat(req.base_url, req.api_key, req.model, _MODULE_SYSTEM, convo, temperature=0.2, proxy=req.proxy)
        try:
            out = _extract_json(reply)
        except (ValueError, json.JSONDecodeError) as e:
            last_errors = [f"输出解析失败：{e}"]
            convo += f"\n\n上次输出无法解析为 JSON（{e}），请只输出含 nodes/anchors 的合法 JSON。"
            continue
        module_nodes = out.get("nodes", {}) or {}
        anchors = out.get("anchors", []) or []
        if not module_nodes:
            last_errors = ["未输出任何新增节点"]
            convo += "\n\n上次没有输出 nodes，请给出本模块要新增的节点。"
            continue
        merged = workflow_merge.merge_module(base, module_nodes, anchors)["graph"]
        workflow_builder.fill_combo_defaults(merged, object_info)  # 先规整 combo 近似值再校验
        errors = workflow_builder.validate_graph(merged, object_info)
        if not errors:
            # 硬错误过了，再跑结构审核（悬空/开关单边接/孤岛）——这些"能跑但不合意图"的缺陷
            audit = workflow_builder.audit_graph(merged, object_info)
            # 有审核问题且还有重试额度 → 回喂 AI 自修（附具体问题），修好再返回
            if audit and attempt < max(1, req.max_retries) - 1:
                last_errors = audit
                convo += ("\n\n合并后整图能通过类型校验，但结构审核发现下列问题，请修正你的 nodes/anchors "
                          "后重新输出（重点：开关节点要两头都接、别留悬空节点）：\n" + "\n".join(audit))
                continue
            # combo 已在校验前规整过；audit 作为 warnings 一并回前端（末轮仍有问题也照常写入，如实告知）
            return {"ok": True, "graph": merged, "errors": [], "warnings": audit}
        last_errors = errors
        convo += "\n\n合并后整图有以下错误，请修正你的 nodes/anchors 后重新输出：\n" + "\n".join(errors)

    return {"ok": False, "graph": merged, "errors": last_errors}


class DirectRequest(EmbedModelReq):
    need: str = ""
    comfy_url: str = "http://127.0.0.1:8188"
    current_graph: dict = {}           # 当前画布，非空=在其基础上改并输出完整新图


@router.post("/build/direct")
def build_direct(req: DirectRequest) -> dict:
    """精简直连模式：信任强模型(Opus 等)一次到位。**只调 1 次模型**输出完整图，
    不查询重写、不 audit 自修、不整图回喂重试——避免多次串行调用在慢中转上超时。
    校验只做一遍：不通过则如实报错(附错误)，由用户看后自己改或重发，不来回折腾。
    返回 {ok, graph, errors, warnings}。"""
    from app.routers.ai_common import chat

    if not req.need.strip():
        raise HTTPException(status_code=400, detail="需求为空")

    cfg = req.embed_cfg()
    packs = node_index.search(cfg, req.need, k=12)  # 不做查询重写，省一次模型调用
    if not packs:
        raise HTTPException(status_code=400, detail=(
            f"节点知识库检索为空。收到的嵌入配置 base_url={cfg.base_url!r} model={cfg.embed_model!r}"
            f"（若 base_url 为空说明前端没传嵌入模型配置，请刷新页面/检查设置→嵌入模型）"))

    try:
        object_info = comfyui_client.fetch_object_info(req.comfy_url)
    except ComfyError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)

    hit_names: list[str] = []
    for p in packs:
        hit_names.extend(p.get("node_names", []))
    hit_names = _with_control_flow(hit_names, object_info)
    named = _named_nodes_in_text(req.need, object_info)  # 方案点名的真实节点
    hit_names = _prioritize(hit_names, req.need, object_info)  # 置顶
    sheet = workflow_builder.interface_sheet(hit_names, object_info, priority=set(named))

    convo = (
        f"需求：{req.need}\n\n【可用节点及真实接口（务必据此接线，口名/类型不得臆造）】\n"
        + "说明：in[] 里 * 是需接线的口(带类型)、? 是可选、= 是填字面值的 widget；out[] 是输出序号:类型。\n"
        + sheet
    )
    if req.current_graph:
        convo += (
            "\n\n【当前画布(API格式)】\n" + json.dumps(req.current_graph, ensure_ascii=False)
            + "\n\n请在当前画布基础上按需求做增量修改，输出修改后的**完整** JSON（保留无关部分）。"
        )
    # 精简直连：最多 2 次模型调用(初次 + 1 次纠错回喂)。后端能确定性修的(combo近似值/缺widget/
    # widget误接线/幻觉节点)先自动修掉不占模型；修完仍有真结构错(如缺必填连线口)才回喂 AI 一次。
    # 这样既消化掉增量那种"错误在循环里改掉"的好处，又不学它多轮回喂拖到超时(顶多 2 次)。
    graph: dict = {}
    missing: list[str] = []
    last_errors: list[str] = []
    for attempt in range(2):
        reply = chat(req.base_url, req.api_key, req.model, _BUILD_SYSTEM, convo, temperature=0.2, proxy=req.proxy)
        try:
            graph = _extract_json(reply)
        except (ValueError, json.JSONDecodeError) as e:
            last_errors = [f"模型输出无法解析为 JSON：{e}"]
            if attempt == 0:
                convo += f"\n\n上次输出无法解析为 JSON（{e}），请只输出合法 JSON。"
                continue
            return {"ok": False, "graph": {}, "errors": last_errors, "warnings": []}
        # 后端自动修：拆幻觉节点 + 规整 combo/补默认/拆错接的 widget 连线
        graph, missing = workflow_builder.split_missing_nodes(graph, object_info)
        workflow_builder.fill_combo_defaults(graph, object_info)
        errors = workflow_builder.validate_graph(graph, object_info)
        if not errors:
            break
        last_errors = errors
        if attempt == 0:
            convo += ("\n\n上次工作流经自动修正后仍有下列错误，请修正后重新输出完整 JSON"
                      "（重点：必接线的口要接上、别把 widget 当连线）：\n" + "\n".join(errors))
            continue
        # 第 2 次仍错：如实返回，不再拖时间
        alts = node_index.suggest_alternatives(cfg, missing, set(object_info)) if missing else {}
        return {"ok": False, "graph": graph, "errors": last_errors,
                "warnings": _missing_hint(missing, alts), "missing_nodes": missing,
                "alternatives": alts}

    alts = node_index.suggest_alternatives(cfg, missing, set(object_info)) if missing else {}
    warnings = workflow_builder.audit_graph(graph, object_info) + _missing_hint(missing, alts)
    return {"ok": True, "graph": graph, "errors": [], "warnings": warnings, "missing_nodes": missing,
            "alternatives": alts}


class PlanRequest(EmbedModelReq):
    need: str = ""
    comfy_url: str = "http://127.0.0.1:8188"
    current_graph: dict = {}           # 当前画布，非空=在其基础上讨论增量改动


_PLAN_SYSTEM = (
    "你是面向新手的 ComfyUI 工作流顾问。用户不熟悉节点，你要用**大白话**讲清楚方案，供他判断后决定是否执行。\n"
    "根据用户需求（和当前画布，若有）+ 给定的可用节点，输出一段**给人看的中文方案**，包含：\n"
    "1. 这个工作流是做什么的（一句话目标）；\n"
    "2. 分几步、每步大意（如：加载模型 → 写提示词 → 采样出图 → 保存），用简单序号列出；\n"
    "   —— 按模型架构给专业方案：SDXL/SD1.5 一体式用 Checkpoint 加载；Flux/SD3/Anima 等分离式模型"
    "应走 UNET 加载器 + 单独 CLIP + 单独 VAE 的分离式架构，别图省事套 checkpoint 一体式。"
    "需求提到的每项能力(反推/图生图/放大等)都要在方案里有对应步骤，别简化成最基础版。\n"
    "3. 会用到哪些关键节点，各自作用（用节点显示名+一句话，别堆术语）——正式方案里点名的节点"
    "**必须来自给定的【本机真实节点】清单**，绝不凭印象编节点名(如不要写 LlamaCPP 这种本机没有的)；\n"
    "4. 若在现有画布上改，说清改动了什么、为什么这么接。\n"
    "5. 【推荐可装节点】如果用户想要的能力，给定的『可用节点清单』里没有合适节点，可推荐"
    "常见主流节点包（如放大 Ultimate SD Upscale、反推 WD14 Tagger、控制 ControlNet Aux、"
    "多功能 Impact-Pack/KJNodes/rgthree 等），说明它能补什么能力。\n"
    "   —— 但必须**单列一节**、标题写『可选：需先安装的节点』，并明确提示："
    "『这些是本机还没装的，包名/可用性我可能记错，请到「节点管理」搜索确认后安装、再「同步节点库」，装好我才能用它们搭。』\n"
    "   —— 绝不把没装的节点混进上面的正式方案步骤里（那些只能用已装节点搭）。\n"
    "要求：口语化、简短、不输出 JSON、不输出节点连线细节。结尾一句『确认后我就照这个方案（只用你已装的节点）搭好写入画布。』"
)


@router.post("/build/plan")
def build_plan(req: PlanRequest) -> dict:
    """顾问模式：只产出给人看的中文方案文本，不生成/不改画布。用户看后点『同意执行』再走 build/module。"""
    from app.routers.ai_common import chat

    if not req.need.strip():
        raise HTTPException(status_code=400, detail="需求为空")

    q = node_index.rewrite_query(req.need, chat, req.base_url, req.api_key, req.model, req.proxy)
    packs = node_index.search(req.embed_cfg(), q, k=12)
    if not packs:
        raise HTTPException(status_code=400, detail="节点知识库为空或无匹配，请先「同步节点库」")
    node_catalog = _trim_catalog(packs)

    # 顾问方案也要基于**本机真实节点名**，否则会凭训练印象编不存在的节点(如把反推写成 LlamaCPP，
    # 实际本机是 Florence2/BLIP/DeepDanbooru)。给出真实节点清单，并强约束正式方案只用它们。
    real_names: list[str] = []
    try:
        object_info = comfyui_client.fetch_object_info(req.comfy_url)
        for p in packs:
            real_names.extend(p.get("node_names", []))
        real_names = _with_control_flow(real_names, object_info)
    except ComfyError:
        object_info = {}
    sheet = workflow_builder.interface_sheet(real_names, object_info) if object_info else ""

    convo = f"用户需求：{req.need}\n\n【可用节点清单（文字说明）】\n{node_catalog}"
    if sheet:
        convo += ("\n\n【本机真实节点（正式方案里点名的节点必须来自这里，别凭印象编节点名）】\n" + sheet)
    if req.current_graph:
        convo += (
            "\n\n【当前画布(API格式)】\n" + json.dumps(req.current_graph, ensure_ascii=False)
            + "\n\n请说明会在当前画布基础上做哪些增量改动。"
        )
    plan = chat(req.base_url, req.api_key, req.model, _PLAN_SYSTEM, convo, temperature=0.4, proxy=req.proxy)
    return {"plan": plan}


# —— 搭建会话：进度保存 + 多开 ——

@router.get("/build/sessions")
def build_sessions() -> dict:
    """列出全部搭建会话元信息（供会话选择器）。"""
    return {"sessions": build_session_store.list_sessions()}


@router.get("/build/session")
def build_session_get(id: str = "") -> dict:
    """读取单个会话完整内容（msgs + graph），供恢复进度。"""
    s = build_session_store.get_session(id)
    if s is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return s


class SaveSessionReq(BaseModel):
    id: str = ""                       # 空=新建
    name: str = ""
    msgs: list = []
    graph: dict = {}
    skeleton_id: str = ""


@router.post("/build/session/save")
def build_session_save(req: SaveSessionReq) -> dict:
    """保存/覆盖搭建会话（对话 + 当前画布图）。返回会话元信息（含 id）。"""
    return build_session_store.save_session(req.id, req.name, req.msgs, req.graph, req.skeleton_id)


class DeleteSessionReq(BaseModel):
    id: str = ""


@router.post("/build/session/delete")
def build_session_delete(req: DeleteSessionReq) -> dict:
    """删除搭建会话。"""
    ok = build_session_store.delete_session(req.id)
    if not ok:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"ok": True}

