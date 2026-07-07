"""SSE 响应封装：把「事件迭代器」包成 text/event-stream 响应。

三个流式端点（image-agent / chat / support）此前各写一遍相同的信封：
逐事件 json.dumps → 出错发 {error} → 末尾 [DONE]。现在统一走这里。

wire 格式（与前端 api/sse.ts openSSE 对齐）：每事件一行 `data: <json>\n\n`，收尾 `data: [DONE]`。
事件为 dict：{delta} / {image,image_id} / {inspiration} / {error} 等。
"""
import json
from typing import Callable, Iterable, Iterator

from fastapi.responses import StreamingResponse


def sse_response(events: Callable[[], Iterable[dict]]) -> StreamingResponse:
    """events 是「返回事件 dict 可迭代对象」的工厂（惰性，进入流式后才求值）。
    迭代中抛异常 → 发一条 {error}；无论如何末尾补 [DONE]。"""
    def gen() -> Iterator[str]:
        try:
            for ev in events():
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except Exception as e:  # 网络/鉴权/模型错误统一回传，前端展示
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
