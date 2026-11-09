// SSE 客户端：EventSource 无法携带 Authorization 头，改用 fetch 流解析。
// 断线自动重连并携带 Last-Event-ID（事件游标），保证无缺口续传。

const RETRY_BASE_MS = 1000;
const RETRY_MAX_MS = 15000;

export function openEventStream(sessionId, { lastSeq = 0, onEvent, onClose } = {}) {
  let closed = false;
  let controller = null;
  let cursor = lastSeq;
  let retryMs = RETRY_BASE_MS;

  async function pump() {
    while (!closed) {
      controller = new AbortController();
      try {
        const resp = await fetch(`/api/sessions/${sessionId}/events`, {
          headers: {
            Authorization: `Bearer ${authToken()}`,
            "Last-Event-ID": String(cursor),
            Accept: "text/event-stream",
          },
          signal: controller.signal,
        });
        if (!resp.ok || !resp.body) {
          throw new Error(`SSE HTTP ${resp.status}`);
        }
        retryMs = RETRY_BASE_MS; // 连接成功即重置退避
        await readFrames(resp.body);
      } catch (err) {
        if (closed) { return; }
      }
      if (closed) { return; }
      await sleep(retryMs);
      retryMs = Math.min(retryMs * 2, RETRY_MAX_MS);
    }
  }

  // 解析 SSE 帧：以空行分隔；"id:" 行更新游标；"data:" 行为事件 JSON
  async function readFrames(body) {
    const reader = body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) { return; }
      buf += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const frame = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        handleFrame(frame);
      }
    }
  }

  function handleFrame(frame) {
    let dataLines = [];
    for (const line of frame.split("\n")) {
      if (line.startsWith("id:")) {
        const id = parseInt(line.slice(3).trim(), 10);
        if (!Number.isNaN(id)) { cursor = Math.max(cursor, id); }
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trimStart());
      }
    }
    if (!dataLines.length) { return; } // 心跳等无 data 帧
    let event = null;
    try { event = JSON.parse(dataLines.join("\n")); } catch (_) { return; }
    if (event && typeof event === "object") { onEvent(event); }
  }

  function sleep(ms) {
    return new Promise((r) => setTimeout(r, ms));
  }

  pump();
  return {
    close() {
      closed = true;
      if (controller) { controller.abort(); }
      if (onClose) { onClose(); }
    },
    cursor: () => cursor,
  };
}

// 令牌由 app.js 注入（避免循环依赖 sse -> api -> app）
let authToken = () => "";
export function bindAuth(tokenGetter) {
  authToken = tokenGetter;
}
