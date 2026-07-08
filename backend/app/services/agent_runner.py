"""图像智能体后台执行器：把生成与 HTTP 连接解耦。

问题：StreamingResponse 的生成器绑定在请求连接上，客户端切仓库/刷新/关页面
导致连接断开时，生成器在下次 yield 处被取消，后台生成半途而废、内容丢失。

方案：agent 跑在独立后台线程，事件投递到一个无界队列。SSE 端只是“旁听”这个
队列——读得到就实时显示，读不到（客户端断开）也不影响后台线程跑完。线程在
完成时把最终文本落盘进 chat_snapshot（生图已在工具内即时落盘），重开从快照回显。
"""
import queue
import threading
from typing import Iterator

from app.services import chat_memory, generation_store, image_agent

# 各 thread 进行中任务计数：前端切走/刷新后据此轮询快照，等后台落盘再显示。
_running: dict[str, int] = {}
# 各 thread 的取消信号：置位 → worker 协作式停止并落「打断态」。
_cancel: dict[str, threading.Event] = {}
_lock = threading.Lock()


def is_running(thread_id: str) -> bool:
    with _lock:
        return _running.get(thread_id, 0) > 0


def cancel(thread_id: str) -> bool:
    """请求打断该 thread 的后台生成。返回是否确有在跑的任务。"""
    with _lock:
        ev = _cancel.get(thread_id)
        running = _running.get(thread_id, 0) > 0
    if ev is not None:
        ev.set()
    return running


def _inc(thread_id: str) -> "threading.Event":
    with _lock:
        _running[thread_id] = _running.get(thread_id, 0) + 1
        ev = threading.Event()
        _cancel[thread_id] = ev  # 新任务覆盖旧信号（同 thread 串行执行，不并发）
        return ev


def _dec(thread_id: str) -> None:
    with _lock:
        n = _running.get(thread_id, 0) - 1
        if n > 0:
            _running[thread_id] = n
        else:
            _running.pop(thread_id, None)
            _cancel.pop(thread_id, None)


def run_stream(thread_id: str, message: str, images: list[str] | None,
               chat_base: str, chat_key: str, chat_model: str,
               gen_base: str, gen_key: str, gen_model: str,
               size: str, output_dir: str, repo_id: str,
               embed_base: str, embed_key: str, embed_model: str,
               message_id: str = "", proxy_url: str = "", style: str = "",
               style_template: str = "", agent_id: str = "") -> "queue.Queue":
    """启动后台线程跑 agent，返回事件队列（None 为结束哨兵）。

    线程独立于调用方：即便 SSE 连接断开、无人读队列，线程仍跑完并把最终文本
    落盘（队列无界，put 不阻塞）。生图在工具内已即时落盘，故连接断开也不丢。
    message_id = 前端 botId，用于把最终文本按 id upsert 进快照，前后端去重一致。
    被 cancel() 打断时：落「打断态」半成品文本，并把半成品补进 checkpoint 供下一轮续写=合并。
    """
    q: "queue.Queue" = queue.Queue()
    final_text: list[str] = []
    cancel_event = _inc(thread_id)
    interrupted = {"v": False}

    def worker():
        try:
            for ev in image_agent.stream_agent(
                thread_id, message, images,
                chat_base, chat_key, chat_model,
                gen_base, gen_key, gen_model,
                size, output_dir, repo_id,
                embed_base, embed_key, embed_model,
                cancel_event=cancel_event, proxy_url=proxy_url, style=style,
                style_template=style_template, agent_id=agent_id,
            ):
                if ev.get("interrupted"):
                    interrupted["v"] = True
                if ev.get("delta"):
                    final_text.append(ev["delta"])
                q.put(ev)
        except Exception as e:  # 兜底，避免线程静默死掉
            q.put({"error": str(e)})
        finally:
            text = "".join(final_text).strip()
            if interrupted["v"]:
                # 打断态：半成品文本落盘（带标记）+ 补进 checkpoint 供下一轮续写合并
                generation_store.persist_text(thread_id, message_id, text, interrupted=True)
                try:
                    chat_memory.mark_interrupted(thread_id, message, images, text)
                except Exception:
                    pass
            else:
                generation_store.persist_text(thread_id, message_id, text)
            _dec(thread_id)
            q.put(None)  # 结束哨兵

    threading.Thread(target=worker, daemon=True).start()
    return q


def drain(q: "queue.Queue") -> Iterator[dict]:
    """从队列取事件直到结束哨兵。供 SSE 端旁听。"""
    while True:
        ev = q.get()
        if ev is None:
            return
        yield ev
