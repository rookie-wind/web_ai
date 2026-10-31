"""技能可唤起性实测 v10：在 U1 配置下真的调用 Skill 工具。

v9 已证：
- workspace/.qoder/skills/xlpa + sources=['project'] -> 发现 xlpa（U1）
- 同配置但 sources=[] -> 发现 0（U2）
- cwd=仓库根 + skills='all' -> 36 项（U3，暴露面过大，不可用作方案）

v10 回答最后一环：发现后的技能能否真的被 Skill 工具唤起并注入内容，
同时记录 gate 视角（PreToolUse 收到的工具名）与 MCP 是否仍连通。
"""

from __future__ import annotations

__all__ = ["main"]

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "webchat"))

from _ac1_probe import ENV_FILE, load_env_file  # noqa: E402

import qodercn_agent_sdk as q  # noqa: E402
from webchat.grants import WriteGate  # noqa: E402

MCP_URL = (f"http://127.0.0.1:"
           f"{int(os.environ.get('SMOKE_MCP_PORT', '8793'))}/mcp")
MODEL = "DeepSeek-Flash"
SRC_SKILL = ROOT / ".qoder" / "skills" / "xlpa"
ASK = ("第一步：调用 Skill 工具唤起名为 xlpa 的技能；"
       "第二步：用一句话复述该技能正文里出现的第一个任务步骤标题。"
       "不要调用其它工具。")


class _NullGrants:
    """空票据存储：本测试不触发平台写入。"""

    def check(self, session_id: str, target: str) -> bool:
        return False


def setup_env() -> dict[str, str]:
    """加载凭据。"""
    load_env_file(ENV_FILE)
    load_env_file(ROOT / "mcp_server" / ".env")
    pat = os.environ.get("QODERCN_PERSONAL_ACCESS_TOKEN", "")
    tok = os.environ.get("MCP_AUTH_TOKEN", "")
    if not pat or not tok:
        raise RuntimeError("缺少 PAT / MCP_AUTH_TOKEN")
    return {"pat": pat, "tok": tok}


def make_ws() -> Path:
    """会话工作区 + 物化 xlpa 技能包。"""
    ws = (ROOT / "webchat" / "webchat_data" / "workspaces"
          / ("_probe10_" + os.urandom(4).hex()))
    for sub in ("xlpa-tmp", "xlpa-input", "xlpa-output"):
        (ws / sub).mkdir(parents=True)
    dst = ws / ".qoder" / "skills" / "xlpa"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SRC_SKILL, dst)
    return ws


async def run(label: str, creds: dict, sources: list[str]) -> dict:
    """跑一次真实 Skill 唤起。"""
    state: dict[str, Any] = {"hook": [], "calls": [], "results": [],
                             "text": [], "mcp": None}
    ws = make_ws()
    gate = WriteGate("smoke-v10", _NullGrants(), server_name="xlpa",
                     workspace_dir=ws)

    async def pre_tool_use(*args: Any, **kwargs: Any) -> Any:
        payload = args[0] if args else (kwargs or {})
        name = payload.get("tool_name", "") if isinstance(payload, dict) else ""
        decision, reason = gate.decide(name, payload.get("tool_input") or {})
        state["hook"].append({"tool": name, "allow": decision,
                              "why": reason[:60]})
        return q.SyncHookJSONOutput(
            hookSpecificOutput=q.PreToolUseHookSpecificOutput(
                hookEventName="PreToolUse",
                permissionDecision="allow" if decision else "deny",
                permissionDecisionReason=reason,
            )
        )

    options = q.QoderAgentOptions(
        auth=q.access_token_from_env(),
        cwd=str(ws),
        tools=["Write", "Edit", "Skill"],
        allowed_tools=["Write", "Edit"],
        disallowed_tools=["Bash"],
        permission_mode="acceptEdits",
        mcp_servers={"xlpa": {"type": "http", "url": MCP_URL,
                              "headers": {"Authorization": f"Bearer {creds['tok']}"}}},
        strict_mcp_config=True,
        allowed_mcp_server_names=["xlpa"],
        setting_sources=sources,
        include_partial_messages=True,
        max_turns=6,
        model=MODEL,
        skills=["xlpa"],
        env={q.DEFAULT_ACCESS_TOKEN_ENV_VAR: creds["pat"]},
        control_request_timeout_ms=180000,
        hooks={"PreToolUse": [q.HookMatcher(matcher=None,
                                            hooks=[pre_tool_use])]},
    )
    client = q.QoderSDKClient(options=options)
    try:
        await client.connect()
        info = await client.get_server_info()
        state["discovered"] = [
            e.get("name") if isinstance(e, dict) else str(e)
            for e in ((info or {}).get("skills") or [])]
        await client.query(ASK)
        async for msg in client.receive_messages():
            mtype = type(msg).__name__
            if mtype == "StreamEvent":
                raw = getattr(msg, "event", None) or {}
                if raw.get("type") == "content_block_start":
                    blk = raw.get("content_block") or {}
                    if blk.get("type") == "tool_use":
                        state["calls"].append(
                            {"name": blk.get("name"),
                             "input": str(blk.get("input"))[:120]})
            elif mtype == "UserMessage":
                for blk in getattr(msg, "content", None) or []:
                    if isinstance(blk, dict) and "tool_use_id" in blk:
                        state["results"].append(
                            {"is_error": bool(blk.get("is_error")),
                             "head": str(blk.get("content"))[:200]})
            elif mtype == "AssistantMessage":
                for blk in getattr(msg, "content", None) or []:
                    if type(blk).__name__ == "TextBlock" and blk.text:
                        state["text"].append(blk.text)
            elif mtype == "ResultMessage":
                state["result"] = {"subtype": msg.subtype,
                                  "is_error": msg.is_error}
                break
        status = await client.get_mcp_status()
        state["mcp"] = [{"n": s.get("name"), "st": s.get("status"),
                         "tools": len(s.get("tools") or [])}
                        for s in status.get("mcpServers", [])]
    except Exception as exc:  # noqa: BLE001
        state["error"] = f"{type(exc).__name__}: {exc}"[:200]
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass
        shutil.rmtree(ws, ignore_errors=True)

    print(f"\n===== {label} (sources={sources}) =====", flush=True)
    print(json.dumps({k: v for k, v in state.items() if k != "text"},
                     ensure_ascii=False, indent=1)[:1800], flush=True)
    print(f"[{label}] model_text={' '.join(state['text'])[:300]!r}", flush=True)
    return state


def main() -> int:
    """对照跑：开启 project 发现 vs 生产现形。"""
    creds = setup_env()
    with_proj = asyncio.run(run("V10-开启project", creds, ["project"]))
    prod_like = asyncio.run(run("V10-生产现形", creds, []))
    print("\n" + "=" * 60, flush=True)
    for nm, st in (("开启 project", with_proj), ("生产现形", prod_like)):
        calls = [c["name"] for c in st.get("calls", [])]
        errs = sum(1 for r in st.get("results", []) if r["is_error"])
        print(f"[{nm}] Skill调用={'Skill' in calls}  "
              f"discovered={st.get('discovered')}  "
              f"结果错误数={errs}  mcp={st.get('mcp')}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
