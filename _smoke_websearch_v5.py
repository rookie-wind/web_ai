"""WebSearch 可行性重探 v5：以当前生产 adapter 形态为基线做 A/B 对照。

基线来源（回读于当前代码，非历史结论）：
- adapter._build_options: tools=["Write","Edit","Skill"]、
  allowed_tools=["Write","Edit"]、permission_mode="acceptEdits"、
  disallowed_tools=["Bash"]、skills=["xlpa"]、strict_mcp_config、
  同时挂 PreToolUse hook 与 can_use_tool；
- WriteGate.decide: 非 mcp__ 面仅放行 Skill 与受限内置写入，其余 deny。

变体：
- P：生产原样（不应出现 WebSearch，MCP 应连通）——回归基线
- W：tools 追加 "WebSearch"，can_use_tool 对 WebSearch 放行——目标形态
- N：skills=None（模拟"不选技能＝纯对话"）——观察技能面

凭据从 _ac_local.env / mcp_server/.env 注入；输出不落 Token。
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
sys.path.insert(0, str(ROOT / "webchat"))

from _ac1_probe import ENV_FILE, load_env_file  # noqa: E402

import qodercn_agent_sdk as q  # noqa: E402
from webchat.grants import BUILTIN_WRITE_TOOL_NAMES, WriteGate  # noqa: E402

# 默认走 _ac1 配对端口，可用 SMOKE_MCP_PORT 指向专用实例
MCP_PORT = int(os.environ.get("SMOKE_MCP_PORT", "8772"))
MCP_URL = f"http://127.0.0.1:{MCP_PORT}/mcp"
MODEL = "DeepSeek-Flash"
PROMPT = (
    "请依次完成三件事，每件用一句话汇报：\n"
    "1) 调用内置 WebSearch 工具搜索“Modbus TCP 协议默认端口号”；\n"
    "2) 调用 MCP 工具 list_mcp_tools 确认 MCP 连接；\n"
    "3) 若可用，调用 Skill 工具列出你可用的技能名。"
)


def setup_env() -> dict[str, str]:
    """加载本地凭据，返回值字典。"""
    load_env_file(ENV_FILE)
    load_env_file(ROOT / "mcp_server" / ".env")
    pat = os.environ.get("QODERCN_PERSONAL_ACCESS_TOKEN", "")
    mcp_token = os.environ.get("MCP_AUTH_TOKEN", "")
    if not pat or not mcp_token:
        raise RuntimeError("缺少 PAT / MCP_AUTH_TOKEN")
    return {"pat": pat, "mcp_token": mcp_token}


def build_options(creds: dict, workspace: Path, *, tools: list[str],
                  skills: list[str] | None, allow_web: bool,
                  state: dict) -> q.QoderAgentOptions:
    """按生产 adapter 同构装配 options，gate 用真实 WriteGate。"""
    gate = WriteGate("smoke-v5", _NullGrants(), server_name="xlpa",
                     workspace_dir=workspace)

    async def pre_tool_use(*args: Any, **kwargs: Any) -> Any:
        payload = args[0] if args else (kwargs or {})
        name = payload.get("tool_name", "") if isinstance(payload, dict) else ""
        state["hook"].append(name)
        if name == "WebSearch":
            decision, reason = allow_web, "smoke v5 websearch"
        else:
            decision, reason = gate.decide(
                name, payload.get("tool_input") or {})
        return q.SyncHookJSONOutput(
            hookSpecificOutput=q.PreToolUseHookSpecificOutput(
                hookEventName="PreToolUse",
                permissionDecision="allow" if decision else "deny",
                permissionDecisionReason=reason,
            )
        )

    async def can_use_tool(tool_name: str, tool_input: dict,
                           context: Any) -> Any:
        state["perm"].append(tool_name)
        if tool_name.startswith("mcp__"):
            return q.PermissionResultAllow()
        bare = tool_name.split("__")[-1]
        if bare == "WebSearch" and allow_web:
            return q.PermissionResultAllow()
        if bare in BUILTIN_WRITE_TOOL_NAMES:
            ok, reason = gate.check_builtin_write(tool_input)
            return (q.PermissionResultAllow() if ok
                    else q.PermissionResultDeny(message=reason))
        return q.PermissionResultDeny(message="smoke v5: not permitted")

    env = {q.DEFAULT_ACCESS_TOKEN_ENV_VAR: creds["pat"]}
    return q.QoderAgentOptions(
        auth=q.access_token_from_env(),
        cwd=str(workspace),
        tools=tools,
        allowed_tools=["Write", "Edit"],
        disallowed_tools=["Bash"],
        permission_mode="acceptEdits",
        mcp_servers={
            "xlpa": {"type": "http", "url": MCP_URL,
                     "headers": {"Authorization": f"Bearer {creds['mcp_token']}"}}
        },
        strict_mcp_config=True,
        allowed_mcp_server_names=["xlpa"],
        setting_sources=[],
        include_partial_messages=True,
        max_turns=8,
        model=MODEL,
        skills=skills,
        env=env,
        control_request_timeout_ms=180000,
        hooks={"PreToolUse": [q.HookMatcher(matcher=None,
                                            hooks=[pre_tool_use])]},
        can_use_tool=can_use_tool,
    )


class _NullGrants:
    """冒烟用空票据存储：check 恒 False（本测试不触发平台写入）。"""

    def check(self, session_id: str, target: str) -> bool:
        return False


def collect(msg: Any, state: dict) -> bool:
    """汇总一条 SDK 消息，收到 ResultMessage 返回 True。"""
    mtype = type(msg).__name__
    if mtype == "StreamEvent":
        raw = getattr(msg, "event", None) or {}
        if raw.get("type") == "content_block_start":
            block = raw.get("content_block") or {}
            if block.get("type") == "tool_use":
                state["calls"].append(block.get("name"))
                print(f"  [call] {block.get('name')}", flush=True)
    elif mtype == "UserMessage":
        for block in getattr(msg, "content", None) or []:
            if isinstance(block, dict) and "tool_use_id" in block:
                state["results"].append({
                    "is_error": bool(block.get("is_error")),
                    "head": str(block.get("content"))[:120]})
    elif mtype == "AssistantMessage":
        for block in getattr(msg, "content", None) or []:
            if type(block).__name__ == "TextBlock" and block.text:
                state["text"].append(block.text)
    elif mtype == "ResultMessage":
        state["result"] = {"subtype": msg.subtype, "is_error": msg.is_error,
                           "turns": msg.num_turns}
        return True
    return False


async def run_variant(name: str, creds: dict, *, tools: list[str],
                      skills: list[str] | None, allow_web: bool) -> dict:
    """跑一个变体。"""
    state: dict = {"hook": [], "perm": [], "calls": [], "results": [],
                   "text": [], "mcp": None}
    workspace = Path(tempfile.mkdtemp(prefix=f"ws5_{name}_"))
    (workspace / "xlpa-output").mkdir()
    options = build_options(creds, workspace, tools=tools, skills=skills,
                            allow_web=allow_web, state=state)
    print(f"\n===== variant {name} | tools={tools} skills={skills} =====",
          flush=True)
    client = q.QoderSDKClient(options=options)
    try:
        await client.connect()
        await client.query(PROMPT)
        async for msg in client.receive_messages():
            if collect(msg, state):
                break
        try:
            status = await client.get_mcp_status()
            state["mcp"] = [{"n": s.get("name"), "st": s.get("status"),
                             "tools": len(s.get("tools") or [])}
                            for s in status.get("mcpServers", [])]
        except Exception as exc:  # noqa: BLE001
            state["mcp"] = f"status failed: {type(exc).__name__}"
    except Exception as exc:  # noqa: BLE001
        state["error"] = f"{type(exc).__name__}: {exc}"[:200]
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass
    print(f"[{name}] calls={state['calls']}", flush=True)
    print(f"[{name}] hook={state['hook']} perm={state['perm']}", flush=True)
    print(f"[{name}] mcp={state['mcp']}", flush=True)
    print(f"[{name}] errs={state['error'] if 'error' in state else '无'}",
          flush=True)
    print(f"[{name}] text={' '.join(state['text'])[:260]!r}", flush=True)
    state["text"] = " ".join(state["text"])
    return state


VARIANTS = [
    ("P", ["Write", "Edit", "Skill"], ["xlpa"], False),
    ("W", ["Write", "Edit", "Skill", "WebSearch"], ["xlpa"], True),
    ("N", ["Write", "Edit", "Skill"], None, False),
]


def main() -> int:
    """顺序跑三变体并输出对照结论。"""
    creds = setup_env()
    summary = {}
    for name, tools, skills, allow_web in VARIANTS:
        summary[name] = asyncio.run(run_variant(
            name, creds, tools=tools, skills=skills, allow_web=allow_web))

    print("\n" + "=" * 60, flush=True)
    for name, st in summary.items():
        calls = st.get("calls") or []
        print(f"[verdict {name}] WebSearch被调用={'WebSearch' in calls}  "
              f"MCP调用={any(str(c).startswith('mcp__') for c in calls)}  "
              f"Skill调用={'Skill' in calls}  "
              f"工具结果错误数={sum(1 for r in st.get('results', []) if r['is_error'])}",
              flush=True)
    detail = {k: {"calls": v.get("calls"), "mcp": v.get("mcp"),
                  "results": v.get("results"), "error": v.get("error")}
              for k, v in summary.items()}
    print(json.dumps(detail, ensure_ascii=False, indent=1)[:2500], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
