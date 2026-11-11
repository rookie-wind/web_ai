"""测试用假 QoderSDKClient：捕获选项、按 query 轮次投递预置消息。

不启动真实 CLI；用于验证适配层的轮次复用、单接收循环与中断语义。
"""

from __future__ import annotations

import asyncio

import qodercn_agent_sdk as q

_STOP = object()


class FakeSDKClient:
    """最小客户端：connect/query/receive_messages/interrupt/disconnect。"""

    def __init__(self, options=None):
        self.options = options
        self.turns: list[list] = []
        self.queries: list[str] = []
        self.set_model_calls: list = []
        self.interrupted = 0
        self.connected = False
        self.disconnected = False
        self.session_id = "sid-1"
        self._queue: asyncio.Queue = asyncio.Queue()
        self._in_turn = False

    async def connect(self, prompt=None):
        self.connected = True

    async def query(self, prompt, **kwargs):
        self.queries.append(prompt)
        messages = self.turns.pop(0) if self.turns else []
        # 本轮脚本未自带 ResultMessage → 视为执行中，interrupt 需自行收尾
        self._in_turn = not any(
            isinstance(m, q.ResultMessage) for m in messages
        )
        for message in messages:
            self._queue.put_nowait(message)

    async def receive_messages(self):
        while True:
            message = await self._queue.get()
            if message is _STOP:
                return
            yield message

    async def set_model(self, model: str | None = None) -> None:
        """记录模型切换调用。"""
        self.set_model_calls.append(model)

    async def interrupt(self):
        self.interrupted += 1
        if self._in_turn:
            self._in_turn = False
            self._queue.put_nowait(
                q.ResultMessage(
                    subtype="error_during_execution",
                    session_id=self.session_id,
                    is_error=True,
                    num_turns=1,
                    duration_ms=1,
                    duration_api_ms=1,
                )
            )

    async def disconnect(self):
        self.disconnected = True
        self._queue.put_nowait(_STOP)


def install(monkeypatch, turns: list[list]) -> list[FakeSDKClient]:
    """把适配层的 QoderSDKClient 换成假客户端，返回实例列表供断言。"""
    import webchat.sdk_runtime.adapter as adapter

    clients: list[FakeSDKClient] = []

    def factory(options=None):
        client = FakeSDKClient(options)
        client.turns.extend([list(turn) for turn in turns])
        clients.append(client)
        return client

    monkeypatch.setattr(adapter.q, "QoderSDKClient", factory)
    return clients
