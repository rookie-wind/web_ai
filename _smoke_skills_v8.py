"""技能发现面补测 v8：把 cwd 换成真实 webchat 工作区目录再判一次。

v7 已知：
- cwd=%TEMP% + sources=[]        -> 0
- cwd=%TEMP% + sources=["project"] -> 0
- cwd=仓库根  + sources=["project"] -> 1（xlpa）
- cwd=仓库根  + sources=[]        -> 0

但未覆盖生产同层路径 webchat/webchat_data/workspaces/<sid>（它位于仓库树内）。
v8 只变 cwd 深度与 skills 取值，其余固定，回答两个问题：
1) 生产工作区路径下，仅加 setting_sources=["project"] 能否发现 xlpa；
2) 若改用 skills="all"，项目级 25 个技能是否会被全量暴露（风险评估）。
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

MCP_PORT = int(os.environ.get("SMOKE_MCP_PORT", "8793"))
MCP_URL = f"http://127.0.0.1:{MCP_PORT}/mcp"
MODEL = "DeepSeek-Flash"
ASK = "不要调用任何工具。只输出一行：你可用 Skill 工具唤起的技能名（无则 NONE）。"


def setup_env() -> dict[str, str]:
    """加载凭据。"""
    load_env_file(ENV_FILE)
    load_env_file(ROOT / "mcp_server" / ".env")
    pat = os.environ.get("QODERCN_PERSONAL_ACCESS_TOKEN", "")
    tok = os.environ.get("MCP_AUTH_TOKEN", "")
    if not pat or not tok:
        raise RuntimeError("缺少 PAT / MCP_AUTH_TOKEN")
    return {"pat": pat, "tok": tok}


def make_workspace(name: str) -> Path:
    """在真实 workspaces 根下建临时会话工作区（与生产同层）。"""
    ws_root = ROOT / "webchat" / "webchat_data" / "workspaces"
    ws_root.mkdir(parents=True, exist_ok=True)
    ws = ws_root / (name + "_" + os.urandom(4).hex())
    for sub in ("xlpa-tmp", "xlpa-input", "xlpa-output"):
        (ws / sub).mkdir(parents=True)
    return ws


def build_options(creds: dict, cwd: Path, sources: list[str],
                  skills: Any) -> q.QoderAgentOptions:
    """生产同构，只变 setting_sources 与 skills。"""
    return q.QoderAgentOptions(
        auth=q.access_token_from_env(),
        cwd=str(cwd),
        tools=["Write", "Edit", "Skill"],
        allowed_tools=["Write", "Edit"],
        disallowed_tools=["Bash"],
        permission_mode="acceptEdits",
        mcp_servers={"xlpa": {"type": "http", "url": MCP_URL,
                              "headers": {"Authorization": f"Bearer {creds['tok']}"}}},
        strict_mcp_config=True,
        allowed_mcp_server_names=["xlpa"],
        setting_sources=sources,
        max_turns=3,
        model=MODEL,
        skills=skills,
        env={q.DEFAULT_ACCESS_TOKEN_ENV_VAR: creds["pat"]},
        control_request_timeout_ms=180000,
    )


async def probe(label: str, creds: dict, sources: list[str],
                skills: Any) -> dict:
    """连接一次，读发现清单 + 模型自述。"""
    ws = make_workspace("_probe8")
    out: dict[str, Any] = {"cwd": str(ws), "sources": sources,
                           "skills_arg": repr(skills)}
    client = q.QoderSDKClient(options=build_options(creds, ws, sources, skills))
    try:
        await client.connect()
        info = await client.get_server_info()
        entries = (info or {}).get("skills") or []
        out["discovered"] = [
            e.get("name") if isinstance(e, dict) else str(e) for e in entries]
        await client.query(ASK)
        texts: list[str] = []
        async for msg in client.receive_response():
            if type(msg).__name__ == "AssistantMessage":
                for block in getattr(msg, "content", None) or []:
                    if type(block).__name__ == "TextBlock":
                        texts.append(block.text)
            elif type(msg).__name__ == "ResultMessage":
                break
        out["model_says"] = " ".join(texts)[:300]
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"[:200]
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass
        shutil.rmtree(ws, ignore_errors=True)
    print(f"\n===== {label} =====", flush=True)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:1500], flush=True)
    return out


def main() -> int:
    """跑三组：生产现形 / 只加 project / project + all。"""
    creds = setup_env()
    cases = [
        ("A 生产工作区 + sources=[]（当前码）", [], ["xlpa"]),
        ("B 生产工作区 + sources=['project']", ["project"], ["xlpa"]),
        ("C 生产工作区 + project + skills='all'", ["project"], "all"),
    ]
    results = {}
    for label, sources, skills in cases:
        results[label] = asyncio.run(probe(label, creds, sources, skills))
    print("\n" + "=" * 60, flush=True)
    for label, r in results.items():
        names = r.get("discovered") or []
        print(f"[{label}] discovered={len(names)} {names[:30]}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
