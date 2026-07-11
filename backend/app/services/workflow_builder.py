"""AI 搭工作流的地基：从 object_info 提取节点接口约束、校验 AI 生成的图、落盘。

核心思路（用户的「必接口优先」）：
- required 里类型为大写「连接类型」(MODEL/LATENT/CONDITIONING...)的口 = 必须接线的骨架；
- required 里基础类型(INT/FLOAT/STRING/combo 列表) = widget 填值，非连线；
- optional 的口 = 可接可不接（如采样器不接 latent 走文生图、接了走图生图）。
先把必接的骨架连对，再在其上叠可选节点。

graph 用 ComfyUI API prompt 格式：{node_id: {class_type, inputs:{口名: 值 或 [上游id, 输出序号]}}}。
落盘存 UI 格式给工作流系统 scan，但校验/试跑在 API 格式上做。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from uuid import uuid4

from app.config import BUILD_TIME_BUDGET_SEC
from app.services import node_index, workflow_merge, comfyui_client
from app.services.comfyui_client import ComfyError
from app.services.pathnames import safe_seg

# 基础值类型（widget 填值，非连线）；其余大写标识符视为需连线的「连接类型」。
_PRIMITIVE = {"INT", "FLOAT", "STRING", "BOOLEAN"}


def _is_link_type(t) -> bool:
    """判断一个输入类型是否需要连线：大写连接类型(MODEL/LATENT...)才需要。
    combo 选项是 list、基础类型在 _PRIMITIVE 里，都属 widget 值不需连线。"""
    if isinstance(t, list):
        return False  # combo 下拉，widget
    if not isinstance(t, str):
        return False
    return t not in _PRIMITIVE


def node_interface(schema: dict) -> dict:
    """从单节点 object_info schema 提取接口约束，供 AI 与校验用。

    返回 {
      required_links: [{name, type}],   # 必须接线的输入口
      required_widgets: [{name, type}], # 必填 widget 值
      optional_links: [{name, type}],   # 可接可不接的输入口
      outputs: [type, ...],             # 输出类型（供下游匹配）
    }
    """
    inp = schema.get("input", {}) or {}
    req = inp.get("required", {}) or {}
    opt = inp.get("optional", {}) or {}
    req_links, req_widgets = [], []
    for name, spec in req.items():
        t = spec[0] if isinstance(spec, list) and spec else spec
        if _is_link_type(t):
            req_links.append({"name": name, "type": t if isinstance(t, str) else "COMBO"})
        else:
            # combo 口(spec[0] 是候选 list)带上 options 供校验/纠错；基础类型 options=None
            opts = t if isinstance(t, list) else None
            # spec[1] 常是 {"default": ..., ...}，取出默认值供自动补齐（AI 没填的必填 widget）
            meta = spec[1] if isinstance(spec, list) and len(spec) > 1 and isinstance(spec[1], dict) else {}
            req_widgets.append({
                "name": name,
                "type": "COMBO" if opts is not None else (t if isinstance(t, str) else "COMBO"),
                "options": opts,
                "default": meta.get("default"),
            })
    opt_links = []
    for name, spec in opt.items():
        t = spec[0] if isinstance(spec, list) and spec else spec
        if _is_link_type(t):
            opt_links.append({"name": name, "type": t})
    return {
        "required_links": req_links,
        "required_widgets": req_widgets,
        "optional_links": opt_links,
        "outputs": list(schema.get("output", []) or []),
    }


def validate_graph(graph: dict, object_info: dict) -> list[str]:
    """用 schema 校验 API 格式 graph，返回错误列表（空=合法）。

    查：①节点 class_type 存在；②连线引用的上游节点存在、输出序号有效；
    ③连线两端类型匹配；④必填连线口都接了；⑤无自环。不改 graph，只报错。
    错误文本写清节点 id 与口名，供 AI 据此重连。
    """
    errors: list[str] = []
    if not isinstance(graph, dict) or not graph:
        return ["graph 为空或格式非法（应为 {node_id: {class_type, inputs}} 字典）"]

    for nid, node in graph.items():
        if not isinstance(node, dict):
            errors.append(f"节点 {nid} 不是对象")
            continue
        ct = node.get("class_type", "")
        schema = object_info.get(ct)
        if not schema:
            errors.append(f"节点 {nid} 的 class_type「{ct}」不存在（未安装或拼写错）")
            continue
        iface = node_interface(schema)
        inputs = node.get("inputs", {}) or {}
        # 必填连线口检查 + 类型匹配
        for link in iface["required_links"]:
            name = link["name"]
            if name not in inputs:
                errors.append(f"节点 {nid}({ct}) 缺必填输入口「{name}」(需接 {link['type']})")
                continue
            _check_link(nid, ct, name, link["type"], inputs[name], graph, object_info, errors)
        # 已填的可选连线口也校验类型
        opt_map = {l["name"]: l["type"] for l in iface["optional_links"]}
        for name, val in inputs.items():
            if isinstance(val, list) and name in opt_map:
                _check_link(nid, ct, name, opt_map[name], val, graph, object_info, errors)
        # 必填 widget 校验：缺失 / combo 值不在候选内（错误里带真实候选供 AI 纠正）
        for w in iface["required_widgets"]:
            _check_widget(nid, ct, w, inputs, errors)
    # 可达性不再算硬错误：见 reachability_warnings。断链孤岛只当警告，允许"先加一路、
    # 下轮再接回主链"的增量搭建中间态照样写入画布。
    return errors


def reachability_warnings(graph: dict, object_info: dict) -> list[str]:
    """终点可达性作为**警告**（不阻断）：有孤岛节点/无输出节点时提醒，但工作流仍可写入画布。
    仅在硬错误(validate_graph)为空时才有意义调用（否则孤岛多是接线错的副产物）。"""
    return _check_reachable(graph, object_info)


def split_missing_nodes(graph: dict, object_info: dict) -> tuple[dict, list[str]]:
    """把用了「本机没装(class_type 不在 object_info)」的节点从图里拆掉，返回 (清理后的图, 缺失节点类型列表)。

    治「AI 编了不存在的节点(如 Qwen2VLLoader)→整个工作流被判死」：不因个别幻觉节点毙掉全图，
    而是把它们摘掉、断开引用它们的连线，其余能搭的照常保留；缺失的类型归入「推荐安装」告诉用户。
    连线处理：任何节点若某输入口连的是被删节点，就移除该口（口留空，后续可手接/校验会提示）。
    """
    if not isinstance(graph, dict):
        return graph, []
    missing_ids = {nid for nid, n in graph.items()
                   if isinstance(n, dict) and n.get("class_type", "") not in object_info}
    if not missing_ids:
        return graph, []
    missing_types = sorted({graph[nid].get("class_type", "") for nid in missing_ids})
    clean: dict = {}
    for nid, node in graph.items():
        if nid in missing_ids:
            continue  # 删掉缺失节点本身
        inputs = node.get("inputs", {}) or {}
        new_inputs = {}
        for name, val in inputs.items():
            # 断开指向被删节点的连线
            if isinstance(val, list) and len(val) == 2 and str(val[0]) in missing_ids:
                continue
            new_inputs[name] = val
        clean[nid] = {**node, "inputs": new_inputs}
    return clean, missing_types


def audit_graph(graph: dict, object_info: dict) -> list[str]:
    """审核（非阻断，供回喂 AI 自修 + 报告给用户）：确定性扫出「能跑但不合意图」的接线缺陷。
    与 validate_graph（硬错误：类型/存在性）互补，audit 查的是**结构完整性**：
      ①悬空输出：某节点有输出口，但没有任何其它节点用它（除输出节点本身），且它也不是输出节点；
      ②开关/聚合节点单边接：Any Switch 这类节点，输入口一个没接(没上游) 或 输出没被用(没下游)；
      ③可达性问题（复用 _check_reachable：孤岛/无输出节点）。
    返回问题描述列表（空=结构完整）。"""
    issues: list[str] = []
    if not isinstance(graph, dict) or not graph:
        return issues

    # 建"谁被谁用"：downstream_used[上游id] = 被引用次数
    used_out: dict[str, int] = {nid: 0 for nid in graph}
    for nid, node in graph.items():
        for val in (node.get("inputs", {}) or {}).values():
            if isinstance(val, list) and len(val) == 2:
                up = str(val[0])
                if up in used_out:
                    used_out[up] += 1

    for nid, node in graph.items():
        ct = node.get("class_type", "")
        schema = object_info.get(ct)
        if not schema:
            continue
        is_output_node = bool(schema.get("output_node"))
        iface = node_interface(schema)
        inputs = node.get("inputs", {}) or {}
        n_links_in = sum(1 for v in inputs.values() if isinstance(v, list) and len(v) == 2)
        has_out = len(iface["outputs"]) > 0

        # ② 开关/聚合节点单边接（名字含 switch，或输入口全是通配 *）
        is_switch = "switch" in ct.lower() or all(
            l.get("type") == "*" for l in (iface["required_links"] + iface["optional_links"])
        ) and (iface["required_links"] or iface["optional_links"])
        if is_switch:
            if n_links_in == 0:
                issues.append(f"节点 {nid}({ct}) 是开关/聚合节点，但没有接任何上游来源（输入口空着）——请把要切换的各路接到它的输入口(如 any_01,any_02)")
            if has_out and used_out.get(nid, 0) == 0 and not is_output_node:
                issues.append(f"节点 {nid}({ct}) 是开关/聚合节点，但它的输出没有接给任何下游——请把它的输出接到需要的口")
            continue

        # ① 普通节点悬空输出：有输出、没被用、又不是输出节点 = 白搭
        if has_out and not is_output_node and used_out.get(nid, 0) == 0:
            issues.append(f"节点 {nid}({ct}) 的输出没有接给任何下游（悬空），要么接上要么删掉")

    # ③ 可达性
    issues.extend(_check_reachable(graph, object_info))
    return issues


def _check_reachable(graph: dict, object_info: dict) -> list[str]:
    """终点可达性：①至少有一个输出节点(output_node，如 SaveImage)；②每个节点都能沿连线抵达某输出节点。
    否则是断链孤岛/没有出图终点的死图（各节点单看合法，整图跑不出结果）。"""
    errs: list[str] = []
    # 输出节点集合（schema.output_node=True，如 SaveImage/PreviewImage）
    sinks = {nid for nid, node in graph.items()
             if object_info.get(node.get("class_type", ""), {}).get("output_node")}
    if not sinks:
        return ["整图没有任何输出节点（如 SaveImage），工作流跑不出结果"]
    # 反向邻接：被谁作为上游引用 → 建 下游->上游 的反查，从 sinks 逆向 BFS 标记可达
    upstream: dict[str, set[str]] = {nid: set() for nid in graph}
    for nid, node in graph.items():
        for val in (node.get("inputs", {}) or {}).values():
            if isinstance(val, list) and len(val) == 2:
                up = str(val[0])
                if up in graph:
                    upstream[nid].add(up)
    reachable = set(sinks)
    stack = list(sinks)
    while stack:
        cur = stack.pop()
        for up in upstream.get(cur, ()):
            if up not in reachable:
                reachable.add(up)
                stack.append(up)
    dead = [nid for nid in graph if nid not in reachable]
    if dead:
        errs.append(f"节点 {'、'.join(sorted(dead))} 未连到任何输出节点（断链孤岛，不会参与出图）")
    return errs


_MAX_OPTS = 30  # 候选列表最多列多少个（防单条错误撑爆 token）


def _fmt_options(options: list) -> str:
    """把 combo 候选格式化成简短提示：前 _MAX_OPTS 个 + 总数。"""
    vals = [str(x) for x in options]
    shown = vals[:_MAX_OPTS]
    tail = f" …(共{len(vals)}个)" if len(vals) > _MAX_OPTS else ""
    return "、".join(shown) + tail


def _check_widget(nid, ct, w, inputs, errors):
    """校验一个必填 widget：在场 + （combo 时）值在候选内。基础类型只查在场，不查具体值。

    重要：combo 口的**空值占位**(''/None，如骨架里的 unet_name/ckpt_name/image)一律放过——
    这类"选本机哪个模型/图"是环境相关的，交给用户在画布下拉里选，不该阻断结构校验；
    尤其增量模式冻结骨架时 AI 根本改不了这些口，若拦截会造成校验永远失败的死锁。
    仍拦截的是：combo 填了**不存在的非空值**(AI 幻觉)、以及口被误当连线填了 [id, slot]。
    """
    name = w["name"]
    options = w.get("options")
    val = inputs.get(name)
    # 误当连线填了 [id, slot]：这是结构错误，拦
    if isinstance(val, list):
        hint = f"，可选：{_fmt_options(options)}" if options else ""
        errors.append(f"节点 {nid}({ct}) 的 widget「{name}」被误当连线填了，应填字面值{hint}")
        return
    # combo 空占位（未填 / '' / None）：放过，待用户在画布选真实模型/图
    is_empty = name not in inputs or val is None or (isinstance(val, str) and val.strip() == "")
    if options is not None:
        if is_empty:
            return  # 空占位不拦
        if val not in options:
            errors.append(
                f"节点 {nid}({ct}) 的「{name}」填了「{val}」，不是合法值，可选：{_fmt_options(options)}")
        return
    # 基础类型(INT/FLOAT/STRING/BOOLEAN)必填：只查在场，不查具体值
    if name not in inputs:
        errors.append(f"节点 {nid}({ct}) 缺必填 widget「{name}」")


def _coerce_one(val, opts):
    """把一个 combo 值规整到合法候选。返回 (新值, 是否改动)。
    规则(依次)：①已合法→不动；②空→第一个标量候选；③大小写不敏感相等→改成候选原值；
    ④值是某候选的前缀/子串，或某候选是值的子串→取最短匹配(如 png→PNG、baked→Baked VAE、
    anima→waiANIPONYXL…不匹配则不动)；⑤都不中→保持原值(交给校验报错，AI/用户再改)。"""
    scalars = [o for o in opts if isinstance(o, (str, int, float, bool))]
    if not scalars:
        return val, False
    if val in opts:
        return val, False
    is_empty = val is None or (isinstance(val, str) and val.strip() == "")
    if is_empty:
        return scalars[0], True
    if not isinstance(val, str):
        return val, False
    low = val.strip().lower()
    # ③ 大小写不敏感相等
    for o in scalars:
        if isinstance(o, str) and o.lower() == low:
            return o, True
    # ④ 子串/前缀匹配，取最短候选（最贴近）
    cand = [o for o in scalars if isinstance(o, str) and (low in o.lower() or o.lower().startswith(low))]
    if cand:
        return min(cand, key=len), True
    # ⑤ token 匹配：候选常是「中文 (english)」格式(如 空格 (space))，AI 可能填描述性词
    #    (如 全部合并为空格)。拆出候选的核心 token，只要输入包含某候选的任一 token 就匹配。
    #    (如"全部合并为空格"含"空格"→匹配"空格 (space)"；"自动修复"不含"两者/both"→不匹配，正确留报错)
    import re as _re
    best = None
    for o in scalars:
        if not isinstance(o, str):
            continue
        toks = [t for t in _re.split(r"[()（）\s]+", o.lower()) if len(t) >= 2]
        if any(t in low for t in toks):
            if best is None or len(o) < len(best):
                best = o
    if best is not None:
        return best, True
    # ⑥ 兜底：都匹配不上(如"启用"对不上否/空格/逗号，"default"/"anima"对不上真实文件名)——
    #    为了"先能生成"，强制回落到第一个候选（通常是关闭/默认项或第一个真实模型），
    #    让工作流至少合法可生成；模型名等用户在画布再改。返回 forced=True 供上层出提示。
    return scalars[0], True


def fill_combo_defaults(graph: dict, object_info: dict) -> int:
    """规整 combo widget 值到合法候选：空占位→补默认；近似值(大小写/子串,如 png→PNG、
    baked→Baked VAE)→自动纠正。让"差一点点"的填值不至于毙掉整个工作流。
    注意：必须在 validate_graph **之前**调用（否则近似值先被判死）。已合法/无法匹配的不动。
    返回改动数。原地改 graph。"""
    changed = 0
    for nid, node in graph.items():
        if not isinstance(node, dict):
            continue
        schema = object_info.get(node.get("class_type", ""))
        if not schema:
            continue
        inputs = node.setdefault("inputs", {})
        def _dft(w):
            d = w.get("default")
            if d is not None:
                return d
            return {"BOOLEAN": False, "INT": 0, "FLOAT": 0.0, "STRING": ""}.get(w.get("type"), "")
        for w in node_interface(schema)["required_widgets"]:
            name = w["name"]
            val = inputs.get(name) if name in inputs else None
            opts = w.get("options")
            # widget 口被误当连线([id,slot])：widget 不能接线，拆掉连线改填默认（治 CLIPTextEncode.text、
            # PromptCleaningMaid.string 被接反推输出的报错——先能生成，用户/后续再手接）。
            if isinstance(val, list):
                inputs[name] = _coerce_one("", opts)[0] if opts else _dft(w)
                changed += 1
                continue
            if opts:
                new, did = _coerce_one(val, opts)  # combo：空补默认/近似纠正/兜底第一候选
                if did:
                    inputs[name] = new
                    changed += 1
                continue
            # 非 combo 必填 widget：AI 没填就用节点默认补齐
            if name not in inputs or val is None:
                inputs[name] = _dft(w)
                changed += 1
    return changed


def interface_sheet(node_names: list[str], object_info: dict, max_nodes: int = 60,
                    priority: set | None = None) -> str:
    """把一批节点的**真实输入/输出接口**拼成精简速查表，喂给 AI 搭工作流。

    这是接线正确性的关键：只有节点名+文字描述时，AI 不知道某节点的口叫什么、输出什么类型，
    只能猜（表现为选错开关节点、把 BOOLEAN 接进 IMAGE 口）。给出真实接口后 AI 才能连对。
    每节点一行：  节点名: in 口名(类型)/widget名(类型)... => out 输出0,输出1...
    连线口标 *、widget 标 =；控量到 max_nodes 个节点，超出省略。
    priority：方案点名的节点集，永远输出、不受 max_nodes 截断（治「点名节点排末尾被截掉」）。
    """
    priority = priority or set()
    lines: list[str] = []
    seen = 0
    for name in node_names:
        schema = object_info.get(name)
        if not schema:
            continue
        if seen >= max_nodes and name not in priority:  # 点名节点豁免截断
            continue
        iface = node_interface(schema)
        ins = []
        for l in iface["required_links"]:
            ins.append(f"*{l['name']}({l['type']})")          # 必接线口
        for l in iface["optional_links"]:
            ins.append(f"*{l['name']}({l['type']})?")          # 可选接线口
        for w in iface["required_widgets"]:
            ins.append(f"={w['name']}({w['type']})")           # 必填 widget
        outs = ", ".join(f"{i}:{t}" for i, t in enumerate(iface["outputs"]))
        line = f"{name}: in[{' '.join(ins)}] => out[{outs}]"
        # 动态输入口节点补注：rgthree Any Switch 等在 schema 里 in[] 是空的（输入口前端运行时动态加），
        # 不加说明 AI 会以为它没输入口→开关悬空。明确告知真实动态口名。
        if not ins and "switch" in name.lower():
            line += "  ← 动态输入口 any_01,any_02,…（把各路来源接这些口，别以为它没输入）"
        lines.append(line)
        seen += 1
    return "\n".join(lines)


def _check_link(nid, ct, port, want_type, val, graph, object_info, errors):
    """校验一条连线：val 应为 [上游id, 输出序号]，且上游存在、序号有效、输出类型匹配。"""
    if not (isinstance(val, list) and len(val) == 2):
        return  # 不是连线（widget 值），跳过
    up_id, out_idx = str(val[0]), val[1]
    if up_id == str(nid):
        errors.append(f"节点 {nid}({ct}) 口「{port}」连到了自己（自环）")
        return
    up = graph.get(up_id)
    if not up:
        errors.append(f"节点 {nid}({ct}) 口「{port}」引用的上游节点 {up_id} 不存在")
        return
    up_schema = object_info.get(up.get("class_type", ""))
    if not up_schema:
        return  # 上游 class_type 非法已在主循环报过
    up_outputs = list(up_schema.get("output", []) or [])
    if not isinstance(out_idx, int) or out_idx < 0 or out_idx >= len(up_outputs):
        errors.append(f"节点 {nid}({ct}) 口「{port}」的上游输出序号 {out_idx} 越界（{up_id} 有 {len(up_outputs)} 个输出）")
        return
    got = up_outputs[out_idx]
    # 通配类型放行：rgthree Any Switch 等"类型无关"节点的口/输出是 "*"，本就匹配任意类型
    # （这正是它们能合并多模态的意义）。want 端或 got 端是 * 都不算不匹配。
    if want_type == "COMBO" or want_type == "*" or got == "*":
        return
    if got != want_type:
        errors.append(f"节点 {nid}({ct}) 口「{port}」需 {want_type}，但上游 {up_id} 输出的是 {got}（类型不匹配）")


def save_workflow(graph: dict, name: str, workflow_dir: str) -> str:
    """把 AI 生成的 API 格式 graph 存成 .json 到 workflowDir，返回落盘路径。

    存 API prompt 格式（ComfyUI 可直接「加载」执行，本工具 workflows.parse 也能读）。
    文件名去非法字符 + 加短 uuid 防撞。workflow_dir 缺失/写失败抛 ValueError。
    """
    if not workflow_dir:
        raise ValueError("未配置工作流默认读取路径（设置 → 路径 → 工作流默认读取路径）")
    base = Path(workflow_dir)
    base.mkdir(parents=True, exist_ok=True)
    stem = safe_seg((name or "ai_workflow").strip()) or "ai_workflow"
    fname = f"{stem}_{uuid4().hex[:8]}.json"
    dest = base / fname
    dest.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(dest)


# ======================================================================
# 搭建编排：检索节点 → 拼 prompt → 调模型 → 校验 → 回喂重试。
# 从路由层下沉（ARCHITECTURE：路由薄、不写循环/业务逻辑）。LLM 调用由调用方
# 注入 chat_fn（签名同 ai_common.chat），故本服务不 import routers，无循环依赖。
# ======================================================================

_EMPTY_INDEX_MSG = (
    "节点知识库检索为空。收到的嵌入配置 base_url={base_url!r} model={embed_model!r}"
    "（若 base_url 为空说明前端没传嵌入模型配置，请刷新页面/检查设置→嵌入模型）"
)


def _search_or_raise(cfg, need: str, k: int):
    """检索相关节点包；空则抛 ValueError（路由映射 400）。收口三处重复的空判文案。"""
    packs = node_index.search(cfg, need, k=k)
    if not packs:
        raise ValueError(_EMPTY_INDEX_MSG.format(base_url=cfg.base_url, embed_model=cfg.embed_model))
    return packs


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


def build_graph(chat_fn, *, base_url: str, api_key: str, model: str, proxy: str,
                cfg, need: str, comfy_url: str, workflow_dir: str, name: str,
                max_retries: int, current_graph: dict, save: bool) -> dict:
    """按需求自动搭工作流：检索节点→AI 生成→校验重试→落盘。返回 {ok, path, graph, errors[, warnings]}。
    need 为空 / 检索空 抛 ValueError（路由映射 400）；ComfyUI 不可达抛 ComfyError（路由映射其 status）。"""
    if not need.strip():
        raise ValueError("需求为空")

    # 1. 检索相关节点包（不做查询重写省一次往返；控制流/反推节点由 _with_control_flow 兜底注入）
    packs = _search_or_raise(cfg, need, k=10)
    node_catalog = _trim_catalog(packs)

    # 2. 取全量 object_info 供校验（含每个节点真实 schema）
    object_info = comfyui_client.fetch_object_info(comfy_url)

    # 接口速查表：命中包里节点的真实口名/类型，AI 据此接线不臆造
    hit_names: list[str] = []
    for p in packs:
        hit_names.extend(p.get("node_names", []))
    hit_names = _with_control_flow(hit_names, object_info)  # 强制补入 Any Switch 等控制流节点
    named = _named_nodes_in_text(need, object_info)         # 方案点名的真实节点
    hit_names = _prioritize(hit_names, need, object_info)
    sheet = interface_sheet(hit_names, object_info, priority=set(named))

    # 3. AI 生成 → 校验 → 有错回喂重连（有 current_graph 时在其基础上增量改，输出完整新图）
    convo = (
        f"需求：{need}\n\n【可用节点清单（文字说明）】\n{node_catalog}"
        + "\n\n【节点真实接口（务必据此接线，口名/类型不得臆造）】\n"
        + "说明：in[] 里 * 是需接线的口(带类型)、? 是可选、= 是填字面值的 widget；out[] 是输出序号:类型。\n"
        + sheet
    )
    if current_graph:
        convo += (
            "\n\n【当前画布工作流(API格式)】\n" + json.dumps(current_graph, ensure_ascii=False)
            + "\n\n请在上面这个当前画布的基础上，按新需求做增量修改（保留无关部分，只改需要变的），"
            "输出修改后的**完整** JSON。"
        )
    _deadline = time.time() + BUILD_TIME_BUDGET_SEC  # 总预算（< 前端 240s 超时），到点停止重试返回现有结果
    last_errors: list[str] = []
    graph: dict = {}
    for attempt in range(max(1, max_retries)):
        if time.time() > _deadline:
            break
        reply = chat_fn(base_url, api_key, model, _BUILD_SYSTEM, convo, temperature=0.2, proxy=proxy)
        try:
            graph = _extract_json(reply)
        except (ValueError, json.JSONDecodeError) as e:
            last_errors = [f"输出解析失败：{e}"]
            convo += f"\n\n上次输出无法解析为 JSON（{e}），请只输出合法 JSON。"
            continue
        # 用了没装的节点：还有重试就回喂让 AI 换真实节点；没重试了就拆掉+提示安装
        _missing = [nid for nid, n in graph.items()
                    if isinstance(n, dict) and n.get("class_type", "") not in object_info]
        if _missing and attempt < max(1, max_retries) - 1:
            types = sorted({graph[i].get("class_type", "") for i in _missing})
            last_errors = [f"用了本机没装的节点：{'、'.join(types)}"]
            convo += ("\n\n上次用了本机没装的节点(" + "、".join(types) +
                      ")，请只用【节点真实接口】里列出的节点重搭；确实没有对应能力的节点就省略那部分。")
            continue
        graph, missing = split_missing_nodes(graph, object_info)
        fill_combo_defaults(graph, object_info)  # 先规整 combo 近似值再校验
        errors = validate_graph(graph, object_info)
        if not errors:
            # 结构审核（悬空/开关单边接/孤岛）——整图模式没"下一轮"，故审核问题也回喂自修
            warnings = audit_graph(graph, object_info)
            if warnings and attempt < max(1, max_retries) - 1:
                last_errors = warnings
                convo += ("\n\n上次工作流能通过类型校验，但结构审核发现下列问题，请修正后重新输出完整 JSON"
                          "（重点：开关节点两头都接、别留悬空节点、主链要连到输出节点）：\n" + "\n".join(warnings))
                continue
            # combo 已在校验前规整过，这里直接落盘
            path = ""
            if save:
                path = save_workflow(graph, name or need[:20], workflow_dir)
            return {"ok": True, "path": path, "graph": graph, "errors": [], "warnings": warnings + _missing_hint(missing)}
        last_errors = errors
        convo += "\n\n上次工作流有以下错误，请修正后重新输出完整 JSON：\n" + "\n".join(errors)

    return {"ok": False, "path": "", "graph": graph, "errors": last_errors}


def build_module(chat_fn, *, base_url: str, api_key: str, model: str, proxy: str,
                 cfg, need: str, comfy_url: str, current_graph: dict, max_retries: int) -> dict:
    """分模块增量搭建：AI 只出新模块+锚点 → 后端 ID 安全合并进当前图 → 校验整图 → 重试。
    不落盘，返回 {ok, graph, errors[, warnings]}（graph 为合并后完整图，前端写回画布）。"""
    if not need.strip():
        raise ValueError("需求为空")

    # 不用冗长文字 catalog（下方只发接口表），省 token；控制流节点由 _with_control_flow 兜底
    packs = _search_or_raise(cfg, need, k=10)

    object_info = comfyui_client.fetch_object_info(comfy_url)

    # 接口速查表：检索命中包里节点的**真实输入/输出口+类型**。没有它 AI 只能猜口名/类型，
    # 会选错开关节点、把 BOOLEAN 接进 IMAGE 口（这正是搭建失败的主因）。
    hit_names: list[str] = []
    for p in packs:
        hit_names.extend(p.get("node_names", []))
    hit_names = _with_control_flow(hit_names, object_info)  # 强制补入 Any Switch 等控制流节点
    sheet = interface_sheet(hit_names, object_info, max_nodes=40)  # 增量加一个模块，40 个够

    base = current_graph or {}
    # 增量模式 prompt 瘦身：①不塞冗长文字 catalog（接口表已给真实口/类型）②当前图只发结构+连线，
    # widget 标量值省略为 …（接线无关）。治"节点多就 prompt 爆炸→502/超时"。合并用前端另传的完整图。
    convo = (
        f"新需求：{need}\n\n【当前工作流(结构+连线，冻结；widget 值已省略为 …，你只需接线不用管它们)】\n"
        + json.dumps(_slim_graph_for_prompt(base), ensure_ascii=False)
        + "\n\n【可用节点及真实接口（务必据此接线，口名/类型不得臆造）】\n"
        + "说明：in[] 里 * 是需接线的口(带类型)、? 是可选、= 是填字面值的 widget；out[] 是输出序号:类型。\n"
        + sheet
    )
    _deadline = time.time() + BUILD_TIME_BUDGET_SEC  # 总预算（< 前端 240s 超时），到点停止再重试，返回现有结果
    last_errors: list[str] = []
    merged: dict = base
    for attempt in range(max(1, max_retries)):
        if time.time() > _deadline:
            break  # 超预算：不再调模型，跳出返回已有 merged（下方按 last_errors 报）
        reply = chat_fn(base_url, api_key, model, _MODULE_SYSTEM, convo, temperature=0.2, proxy=proxy)
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
        fill_combo_defaults(merged, object_info)  # 先规整 combo 近似值再校验
        errors = validate_graph(merged, object_info)
        if not errors:
            # 硬错误过了，再跑结构审核（悬空/开关单边接/孤岛）——这些"能跑但不合意图"的缺陷
            audit = audit_graph(merged, object_info)
            # 有审核问题且还有重试额度 → 回喂 AI 自修（附具体问题），修好再返回
            if audit and attempt < max(1, max_retries) - 1:
                last_errors = audit
                convo += ("\n\n合并后整图能通过类型校验，但结构审核发现下列问题，请修正你的 nodes/anchors "
                          "后重新输出（重点：开关节点要两头都接、别留悬空节点）：\n" + "\n".join(audit))
                continue
            # combo 已在校验前规整过；audit 作为 warnings 一并回前端（末轮仍有问题也照常写入，如实告知）
            return {"ok": True, "graph": merged, "errors": [], "warnings": audit}
        last_errors = errors
        convo += "\n\n合并后整图有以下错误，请修正你的 nodes/anchors 后重新输出：\n" + "\n".join(errors)

    return {"ok": False, "graph": merged, "errors": last_errors}


def build_direct(chat_fn, *, base_url: str, api_key: str, model: str, proxy: str,
                 cfg, need: str, comfy_url: str, current_graph: dict) -> dict:
    """精简直连模式：信任强模型(Opus 等)一次到位。**只调 1 次模型**输出完整图，
    不查询重写、不 audit 自修、不整图回喂重试——避免多次串行调用在慢中转上超时。
    校验只做一遍：不通过则如实报错(附错误)，由用户看后自己改或重发，不来回折腾。
    返回 {ok, graph, errors, warnings, missing_nodes, alternatives}。"""
    if not need.strip():
        raise ValueError("需求为空")

    packs = _search_or_raise(cfg, need, k=12)  # 不做查询重写，省一次模型调用

    object_info = comfyui_client.fetch_object_info(comfy_url)

    hit_names: list[str] = []
    for p in packs:
        hit_names.extend(p.get("node_names", []))
    hit_names = _with_control_flow(hit_names, object_info)
    named = _named_nodes_in_text(need, object_info)  # 方案点名的真实节点
    hit_names = _prioritize(hit_names, need, object_info)  # 置顶
    sheet = interface_sheet(hit_names, object_info, priority=set(named))

    convo = (
        f"需求：{need}\n\n【可用节点及真实接口（务必据此接线，口名/类型不得臆造）】\n"
        + "说明：in[] 里 * 是需接线的口(带类型)、? 是可选、= 是填字面值的 widget；out[] 是输出序号:类型。\n"
        + sheet
    )
    if current_graph:
        convo += (
            "\n\n【当前画布(API格式)】\n" + json.dumps(current_graph, ensure_ascii=False)
            + "\n\n请在当前画布基础上按需求做增量修改，输出修改后的**完整** JSON（保留无关部分）。"
        )
    # 精简直连：最多 2 次模型调用(初次 + 1 次纠错回喂)。后端能确定性修的(combo近似值/缺widget/
    # widget误接线/幻觉节点)先自动修掉不占模型；修完仍有真结构错(如缺必填连线口)才回喂 AI 一次。
    # 这样既消化掉增量那种"错误在循环里改掉"的好处，又不学它多轮回喂拖到超时(顶多 2 次)。
    graph: dict = {}
    missing: list[str] = []
    last_errors: list[str] = []
    for attempt in range(2):
        reply = chat_fn(base_url, api_key, model, _BUILD_SYSTEM, convo, temperature=0.2, proxy=proxy)
        try:
            graph = _extract_json(reply)
        except (ValueError, json.JSONDecodeError) as e:
            last_errors = [f"模型输出无法解析为 JSON：{e}"]
            if attempt == 0:
                convo += f"\n\n上次输出无法解析为 JSON（{e}），请只输出合法 JSON。"
                continue
            return {"ok": False, "graph": {}, "errors": last_errors, "warnings": []}
        # 后端自动修：拆幻觉节点 + 规整 combo/补默认/拆错接的 widget 连线
        graph, missing = split_missing_nodes(graph, object_info)
        fill_combo_defaults(graph, object_info)
        errors = validate_graph(graph, object_info)
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
    warnings = audit_graph(graph, object_info) + _missing_hint(missing, alts)
    return {"ok": True, "graph": graph, "errors": [], "warnings": warnings, "missing_nodes": missing,
            "alternatives": alts}


def build_plan(chat_fn, *, base_url: str, api_key: str, model: str, proxy: str,
               cfg, need: str, comfy_url: str, current_graph: dict) -> dict:
    """顾问模式：只产出给人看的中文方案文本，不生成/不改画布。返回 {plan}。
    need 为空 / 检索空 抛 ValueError（路由映射 400）。"""
    if not need.strip():
        raise ValueError("需求为空")

    q = node_index.rewrite_query(need, chat_fn, base_url, api_key, model, proxy)
    packs = node_index.search(cfg, q, k=12)
    if not packs:
        raise ValueError("节点知识库为空或无匹配，请先「同步节点库」")
    node_catalog = _trim_catalog(packs)

    # 顾问方案也要基于**本机真实节点名**，否则会凭训练印象编不存在的节点(如把反推写成 LlamaCPP，
    # 实际本机是 Florence2/BLIP/DeepDanbooru)。给出真实节点清单，并强约束正式方案只用它们。
    real_names: list[str] = []
    try:
        object_info = comfyui_client.fetch_object_info(comfy_url)
        for p in packs:
            real_names.extend(p.get("node_names", []))
        real_names = _with_control_flow(real_names, object_info)
    except ComfyError:
        object_info = {}
    sheet = interface_sheet(real_names, object_info) if object_info else ""

    convo = f"用户需求：{need}\n\n【可用节点清单（文字说明）】\n{node_catalog}"
    if sheet:
        convo += ("\n\n【本机真实节点（正式方案里点名的节点必须来自这里，别凭印象编节点名）】\n" + sheet)
    if current_graph:
        convo += (
            "\n\n【当前画布(API格式)】\n" + json.dumps(current_graph, ensure_ascii=False)
            + "\n\n请说明会在当前画布基础上做哪些增量改动。"
        )
    plan = chat_fn(base_url, api_key, model, _PLAN_SYSTEM, convo, temperature=0.4, proxy=proxy)
    return {"plan": plan}


