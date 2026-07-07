const API_BASE = "http://127.0.0.1:8010/api";

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    // 透出后端 detail（FastAPI 错误体 {detail: ...}），否则只能看到状态码
    let detail = "";
    try {
      const data = await response.json();
      detail = typeof data?.detail === "string" ? data.detail : JSON.stringify(data?.detail ?? data);
    } catch {
      try { detail = await response.text(); } catch { /* ignore */ }
    }
    throw new Error(detail || `API request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function apiGet<T>(path: string): Promise<T> {
  return parseResponse<T>(await fetch(`${API_BASE}${path}`));
}

export async function apiPost<T>(path: string, body: unknown, timeoutMs?: number): Promise<T> {
  // 可选超时：传 timeoutMs 时用 AbortController 限时，超时抛可读错误（避免前端永久“思考中…”死等）
  let signal: AbortSignal | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;
  if (timeoutMs && timeoutMs > 0) {
    const ac = new AbortController();
    signal = ac.signal;
    timer = setTimeout(() => ac.abort(), timeoutMs);
  }
  try {
    return await parseResponse<T>(
      await fetch(`${API_BASE}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal,
      }),
    );
  } catch (e) {
    if ((e as Error)?.name === "AbortError") {
      throw new Error(`请求超时（超过 ${Math.round((timeoutMs || 0) / 1000)} 秒）。可能是模型/中转较慢或需求太复杂，建议把需求拆小、分几轮发，或稍后重试。`);
    }
    throw e;
  } finally {
    if (timer) clearTimeout(timer);
  }
}

export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  return parseResponse<T>(
    await fetch(`${API_BASE}${path}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}

export async function apiDelete<T>(path: string): Promise<T> {
  return parseResponse<T>(await fetch(`${API_BASE}${path}`, { method: "DELETE" }));
}