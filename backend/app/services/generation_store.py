"""生成记录持久化：一次生成的落盘策略集中在此。

此前「留存图→入库→写快照」三件套内联在 image_agent 的 generate_image 工具里，
而灵感卡的快照写入又是另一套形状，落盘逻辑散在多处、两套 id 约定（thread_id / repo_id）。
本模块把它们收成两个深接口：调用方给「产出物」，由本模块决定存到哪、按什么 id 去重。

- persist_image：云图留存到本地 → 入 RAG 库 → 追加进对话快照。返回 {id, url}。
- persist_inspiration：灵感卡 upsert 进对话快照。返回 card dict。
- persist_text：把一段最终/半成品文本 upsert 进快照（供后台线程收尾/打断复用）。

单个持久化环节失败不阻断主流程（生图/找灵感已成功），各自 try/except 吞掉。
"""
import uuid

from app.services import chat_snapshot, rag_store
from app.services.image_utils import save_remote_image


def persist_image(thread_id: str, repo_id: str, prompt: str, image_url: str,
                  output_dir: str, embed_base: str, embed_key: str,
                  embed_model: str) -> dict:
    """生图产出落盘：下载留存云图→本地地址，入库（RAG），追加带图消息进快照。
    返回 {"id", "url"}，id 前后端共用于去重（随 SSE image_id 回传）。"""
    shown = save_remote_image(image_url, output_dir, repo_id)
    mid = str(uuid.uuid4())
    # 入库(RAG)：embedding 偶发瞬时失败(ollama 并发/超时)会让「磁盘有图但资产库不显示」——
    # 批量出图时几张挤一起调 embedding，个别失败最典型。故重试 3 次 + 失败打日志(别再静默吞)。
    cfg = rag_store.EmbedConfig(embed_base, embed_key, embed_model)
    for attempt in range(3):
        try:
            rag_store.index_generation(repo_id, cfg, prompt, image_url=shown)
            break
        except Exception as e:  # noqa: BLE001
            import logging, time as _t
            logging.getLogger("uvicorn.error").warning(
                "index_generation 失败(第%d次) repo=%s img=%s: %s", attempt + 1, repo_id, shown, e)
            if attempt < 2:
                _t.sleep(0.8 * (attempt + 1))  # 退避重试
    try:
        chat_snapshot.append_image(thread_id, mid, shown)
    except Exception:
        pass  # 落盘失败不影响出图
    return {"id": mid, "url": shown}


def persist_inspiration(thread_id: str, query: str, prompt: str,
                        tags: list[str], sources: list[dict]) -> dict:
    """灵感卡落盘：upsert 一条带 inspiration 的 assistant 消息进快照。返回 card dict。"""
    card = {"id": str(uuid.uuid4()), "query": query, "prompt": prompt,
            "tags": tags, "sources": sources}
    try:
        chat_snapshot.upsert(thread_id, {
            "id": card["id"], "role": "assistant", "text": "",
            "inspiration": {"query": query, "prompt": prompt,
                            "tags": tags, "sources": sources},
        })
    except Exception:
        pass
    return card


def persist_text(thread_id: str, message_id: str, text: str,
                 interrupted: bool = False) -> None:
    """把最终/半成品文本按 message_id upsert 进快照（后台线程收尾/打断用）。"""
    if not (text or "").strip() or not message_id:
        return
    try:
        if interrupted:
            chat_snapshot.upsert(thread_id, {
                "id": message_id, "role": "assistant", "text": text, "interrupted": True,
            })
        else:
            chat_snapshot.append_text(thread_id, message_id, text)
    except Exception:
        pass
