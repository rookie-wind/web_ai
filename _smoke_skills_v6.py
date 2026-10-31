"""会话技能面探测 v6：查 CLI 在"会话工作区"里的技能发现清单。

目的：回答"MCP/web 上有哪些 skill 可选、不选是否就是纯对话"。
做法：以生产同构配置连接（cwd=仿造会话工作区，仅 xlpa-tmp/input/output，
setting_sources=[]），调用 get_server_info() 读发现清单，并对比
skills=["xlpa"] / skills=None / skills=[] 三种取值下模型自述可用技能。

凭据从 env 文件读取，输出不落 Token。
"""

from __future__ import annotations

__all__ = ["main"]

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "webchat"))

from _ac1_probe import ENV_FILE, load_env_file  # noqa: E402

import qodercn_agent_sdk as q  # noqa: E402

MCP_PORT = int(os.environ.get("SMOKE_MCP_PORT", "8792"))
MCP_URL = f"http://127.0.0.1:{MCP_PORT}/mcp"
MODEL = "DeepSeek-Flash"
ASK = "不要调用任何工具。只用一句话列出你当前可调用（可被 Skill 工具唤起）的技能名称。"


def setup_env() -> dict[str, str]:
    """加载凭据。"""
    load_env_file(ENV_FILE)
    load_env_file(ROOT / "mcp_server" / ".env")
    pat = os.environ.get("QODERCN_PERSONAL_ACCESS_TOKEN", "")
    mcp_token = os.environ.get("MCP_AUTH_TOKEN", "")
    if not pat or not mcp_token:
        raise RuntimeError("缺少 PAT / MCP_AUTH_TOKEN")
    return {"pat": pat, "mcp_token": mcp_token}


def make_workspace() -> Path:
    """仿造 webchat 会话工作区：用真实工作区根目录（webchat_data/workspaces）。

    技能发现与 cwd 在文件树上的位置相关（CLI 可能向上追溯项目级 .qoder），
    因此必须用与生产同层的目录，不能用 %TEMP%。
    """
    ws_root = ROOT / "webchat" / "webchat_data" / "workspaces"
    ws_root.mkdir(parents=True, exist_ok=True)
    ws = ws_root / ("_probe6_" + os.urandom(4).hex())
    for sub in ("xlpa-tmp", "xlpa-input", "xlpa-output"):
        (ws / sub).mkdir(parents=True)
    return ws


def build_options(creds: dict, ws: Path, skills: Any) -> q.QoderAgentOptions:
    """生产同构 options（不含 hook/gate，本探测只关心技能发现面）。"""
    return q.QoderAgentOptions(
        auth=q.access_token_from_env(),
        cwd=str(ws),
        tools=["Write", "Edit", "Skill"],
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
        max_turns=4,
        model=MODEL,
        skills=skills,
        env={q.DEFAULT_ACCESS_TOKEN_ENV_VAR: creds["pat"]},
        control_request_timeout_ms=180000,
    )


async def probe(label: str, creds: dict, skills: Any) -> dict:
    """连接一次，读 server_info 技能清单 + 模型自述。"""
    out: dict[str, Any] = {"skills_arg": repr(skills)}
    ws = make_workspace()
    out["cwd"] = str(ws)
    client = q.QoderSDKClient(options=build_options(creds, ws, skills))
    try:
        await client.connect()
        try:
            info = await client.get_server_info()
            entries = (info or {}).get("skills") or []
            out["discovered"] = [
                {"name": e.get("name"), "source": e.get("source", "")}
                if isinstance(e, dict) else str(e) for e in entries
            ]
        except Exception as exc:  # noqa: BLE001
            out["discovered_error"] = f"{type(exc).__name__}: {exc}"[:160]
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
        import shutil

        shutil.rmtree(ws, ignore_errors=True)
    print(f"\n===== {label} (skills={out['skills_arg']}) =====", flush=True)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:1200], flush=True)
    return out


def main() -> int:
    """三种 skills 取值各探一次。"""
    creds = setup_env()
    results = {}
    for label, skills in (("prod_xlpa", ["xlpa"]), ("none", None), ("empty", [])):
        results[label] = asyncio.run(probe(label, creds, skills))
    print("\n" + "=" * 60, flush=True)
    for label, r in results.items():
        print(f"[{label}] discovered={len(r.get('discovered') or [])} 项  "
              f"arg={r['skills_arg']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
