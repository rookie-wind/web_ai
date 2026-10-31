"""WebSearch + MCP 共存可行性冒烟 v3（方案 B 第 1 步，不改生产代码）。

已确认事实：
- v1: tools=["WebSearch"] 时模型确有 WebSearch tool_use；无 hook 应答权限→自动拒绝。
- v2: PreToolUse hook 能拦到并放行内置 WebSearch（gate 豁免路径成立）；
  但 MCP server status=disconnected，模型看不到任何 MCP 工具。

v3 用同一 prompt 跑多个工具面变体，定位 MCP 工具消失的触发条件：
- variant A: tools=["WebSearch"]                （v1/v2 配置）
- variant B: tools=["WebSearch", "WebFetch"]
- variant C: tools="default"                     （全部内置，危险工具靠 hook 拒绝）
- variant D: tools=None + disallowed_tools 关危险内置（贴近未来生产形态）

每个变体记录：MCP 状态、hook 所见全部工具名、模型实际 tool_use 序列、
工具结果 is_error、最终文本。凭据从 env 文件读取，不落盘。
"""

from __future__ import annotations

__all__ = ["main"]

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from _ac1_probe import ENV_FILE, load_env_file  # noqa: E402

import qodercn_agent_sdk as q  # noqa: E402

MCP_URL = "http://127.0.0.1:8772/mcp"
MODEL = "DeepSeek-Flash"
PROMPT = (
    "第一步：调用内置 WebSearch 工具搜索“Modbus TCP 协议默认端口号”，一句话汇报。"
    "第二步：调用 MCP 工具 list_mcp_tools，一句话汇报 MCP 连接是否正常。"
)

DANGEROUS_BUILTINS = [
    "Bash", "Write", "Edit", "Read", "Glob", "Grep",
    "NotebookEdit", "TodoWrite", "WebFetch",
]


def make_hook(state: dict, allow_builtin: bool):
    """构造 PreToolUse hook：记录全部工具调用，内置工具按参数决定放行。"""

    async def pre_tool_use(*args: Any, **kwargs: Any) -> Any:
        payload = args[0] if args else (kwargs or {})
        name = payload.get("tool_name", "") if isinstance(payload, dict) else ""
        state["hook_tools"].append(name)
        allow = allow_builtin or name.startswith("mcp__")
        if not allow and name in ("WebSearch",):
            allow = True  # WebSearch 一律放行（本冒烟要验证的就是这条路）
        return q.SyncHookJSONOutput(
            hookSpecificOutput=q.PreToolUseHookSpecificOutput(
                hookEventName="PreToolUse",
                permissionDecision="allow" if allow else "deny",
                permissionDecisionReason="smoke-v3",
            )
        )

    return pre_tool_use


def setup_env() -> dict[str, str]:
    """加载本地凭据文件，返回所需环境变量值。"""
    load_env_file(ENV_FILE)
    load_env_file(ROOT / "mcp_server" / ".env")
    pat = os.environ.get("QODERCN_PERSONAL_ACCESS_TOKEN", "")
    mcp_token = os.environ.get("MCP_AUTH_TOKEN", "")
    if not pat or not mcp_token:
        raise RuntimeError("缺少 QODERCN_PERSONAL_ACCESS_TOKEN / MCP_AUTH_TOKEN")
    return {"pat": pat, "mcp_token": mcp_token}


def collect(msg: Any, state: dict) -> bool:
    """把一条 SDK 消息并入 state；收到 ResultMessage 返回 True。"""
    mtype = type(msg).__name__
    if mtype == "StreamEvent":
        raw = getattr(msg, "event", None) or {}
        if raw.get("type") == "content_block_start":
            block = raw.get("content_block") or {}
            if block.get("type") == "tool_use":
                name = block.get("name")
                state["stream_tools"].append(name)
                print(f"  [stream tool_use] {name}", flush=True)
    elif mtype == "AssistantMessage":
        for block in getattr(msg, "content", None) or []:
            if type(block).__name__ == "ToolUseBlock":
                state["tool_calls"].append(
                    {"tool": block.name, "input": str(block.input)[:120]})
                print(f"  [tool_use] {block.name}", flush=True)
            elif type(block).__name__ == "TextBlock" and block.text:
                state["text"].append(block.text)
    elif mtype == "UserMessage":
        for block in getattr(msg, "content", None) or []:
            if isinstance(block, dict) and "tool_use_id" in block:
                state["results"].append({
                    "is_error": bool(block.get("is_error")),
                    "content": str(block.get("content"))[:160],
                })
    elif mtype == "ResultMessage":
        state["result"] = {"subtype": msg.subtype, "is_error": msg.is_error,
                           "turns": msg.num_turns}
        return True
    return False


async def run_variant(name: str, creds: dict[str, str],
                      tools: Any, disallowed: list[str]) -> dict:
    """跑一个工具面变体，返回事件汇总。"""
    state: dict = {"hook_tools": [], "tool_calls": [], "results": [],
                   "text": [], "mcp_status": None, "stream_tools": []}
    hook = make_hook(state, allow_builtin=(name != "C"))
    options = q.QoderAgentOptions(
        auth=q.access_token_from_env(),
        cwd=tempfile.mkdtemp(prefix="ws_smoke_"),
        tools=tools,
        disallowed_tools=disallowed,
        mcp_servers={
            "xlpa": {
                "type": "http",
                "url": MCP_URL,
                "headers": {"Authorization": f"Bearer {creds['mcp_token']}"},
            }
        },
        strict_mcp_config=True,
        allowed_mcp_server_names=["xlpa"],
        # 与生产 adapter 一致：开启 partial 流式，同时获得工具事件可见性
        include_partial_messages=True,
        permission_mode="default",
        setting_sources=[],
        max_turns=8,
        model=MODEL,
        skills=None,
        env={q.DEFAULT_ACCESS_TOKEN_ENV_VAR: creds["pat"]},
        control_request_timeout_ms=180000,
        hooks={"PreToolUse": [q.HookMatcher(matcher=None, hooks=[hook])]},
    )
    print(f"\n===== variant {name} =====", flush=True)
    client = q.QoderSDKClient(options=options)
    try:
        await client.connect()
        await client.query(PROMPT)
        async for msg in client.receive_messages():
            if collect(msg, state):
                break
        # 首条消息后 MCP 应已完成握手，此时查状态最可信
        # 状态输出必须脱敏：config.headers 内含 Bearer Token，不得进入控制台/日志
        try:
            status = await client.get_mcp_status()
            state["mcp_status"] = [
                {"name": s.get("name"), "status": s.get("status"),
                 "tools_n": len(s.get("tools") or [])}
                for s in status.get("mcpServers", [])
            ]
        except Exception as exc:  # noqa: BLE001
            state["mcp_status"] = f"query failed: {type(exc).__name__}"
    except Exception as exc:  # noqa: BLE001 - 变体失败如实记录
        state["error"] = f"{type(exc).__name__}: {exc}"[:200]
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass
    print(f"[{name}] hook={state['hook_tools']}", flush=True)
    print(f"[{name}] stream_calls={state['stream_tools']}", flush=True)
    print(f"[{name}] calls={[c['tool'] for c in state['tool_calls']]}", flush=True)
    print(f"[{name}] mcp={state['mcp_status']}", flush=True)
    print(f"[{name}] text={''.join(state['text'])[:200]!r}", flush=True)
    state["text"] = "".join(state["text"])[:400]
    return state


VARIANTS: list[tuple[str, Any, list[str]]] = [
    ("E", [], []),  # 基线：生产同款配置（内置工具全关），验证 MCP 是否本来就能连
    ("A", ["WebSearch"], []),
]


def main() -> int:
    """依次跑全部变体，输出对比结论。"""
    creds = setup_env()
    summary: dict[str, dict] = {}
    for name, tools, disallowed in VARIANTS:
        summary[name] = asyncio.run(
            run_variant(name, creds, tools, disallowed))

    print("\n" + "=" * 56, flush=True)
    print(json.dumps(summary, ensure_ascii=False, indent=1)[:3500], flush=True)
    for name, st in summary.items():
        calls = ([c["tool"] for c in st.get("tool_calls", [])]
                 + list(st.get("stream_tools") or []))
        print(f"[verdict {name}] WebSearch={'WebSearch' in calls}  "
              f"MCP工具={any(str(c).startswith('mcp__') for c in calls)}  "
              f"err={st.get('error', '')}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
