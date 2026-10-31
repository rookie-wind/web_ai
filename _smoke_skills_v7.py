"""技能发现面矩阵探测 v7：定位 xlpa 技能在何种配置下才被发现。

背景：v6 在真实会话工作区路径 + setting_sources=[] 下，get_server_info()
返回的技能清单为空，模型自述"无可调用技能"。需隔离两个变量：
- cwd 是否位于仓库内（项目级 .qoder/skills 是否可达）；
- setting_sources 是否包含 "project"（是否加载项目设置）。

判据：每个组合打印 discovered 技能名清单，并标注 'xlpa' 是否在其中。
"""

from __future__ import annotations

__all__ = ["main"]

import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "webchat"))

from _ac1_probe import ENV_FILE, load_env_file  # noqa: E402

import qodercn_agent_sdk as q  # noqa: E402

MCP_URL = f"http://127.0.0.1:{int(os.environ.get('SMOKE_MCP_PORT', '8792'))}/mcp"
MODEL = "DeepSeek-Flash"
ASK = "不要调用工具。只输出一行：你可用 Skill 工具唤起的技能名（无则回答 NONE）。"


def setup_env() -> dict[str, str]:
    """加载凭据。"""
    load_env_file(ENV_FILE)
    load_env_file(ROOT / "mcp_server" / ".env")
    pat = os.environ.get("QODERCN_PERSONAL_ACCESS_TOKEN", "")
    tok = os.environ.get("MCP_AUTH_TOKEN", "")
    if not pat or not tok:
        raise RuntimeError("缺少 PAT / MCP_AUTH_TOKEN")
    return {"pat": pat, "tok": tok}


def build_options(creds: dict, cwd: Path, sources: list[str]) -> q.QoderAgentOptions:
    """最小配置：只变 cwd 与 setting_sources，其余固定。"""
    return q.QoderAgentOptions(
        auth=q.access_token_from_env(),
        cwd=str(cwd),
        tools=["Skill"],
        setting_sources=sources,
        max_turns=3,
        model=MODEL,
        skills=["xlpa"],
        env={q.DEFAULT_ACCESS_TOKEN_ENV_VAR: creds["pat"]},
        mcp_servers={"xlpa": {"type": "http", "url": MCP_URL,
                              "headers": {"Authorization": f"Bearer {creds['tok']}"}}},
        strict_mcp_config=True,
        control_request_timeout_ms=180000,
    )


async def probe(label: str, creds: dict, cwd: Path,
                sources: list[str]) -> dict:
    """连接一次读发现清单，并让模型自述。"""
    out: dict[str, Any] = {"cwd": str(cwd), "sources": sources}
    client = q.QoderSDKClient(options=build_options(creds, cwd, sources))
    try:
        await client.connect()
        info = await client.get_server_info()
        entries = (info or {}).get("skills") or []
        names = []
        for e in entries:
            names.append(e.get("name") if isinstance(e, dict) else str(e))
        out["discovered"] = names
        await client.query(ASK)
        texts: list[str] = []
        async for msg in client.receive_response():
            if type(msg).__name__ == "AssistantMessage":
                for block in getattr(msg, "content", None) or []:
                    if type(block).__name__ == "TextBlock":
                        texts.append(block.text)
            elif type(msg).__name__ == "ResultMessage":
                break
        out["model_says"] = " ".join(texts)[:200]
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"[:200]
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass
    print(f"\n===== {label} =====", flush=True)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:900], flush=True)
    return out


def main() -> int:
    """跑四组组合。"""
    creds = setup_env()
    tmp_ws = Path(tempfile.mkdtemp(prefix="ws7_"))
    cases = [
        ("1 会话工作区 + setting_sources=[]（生产现形）", tmp_ws, []),
        ("2 会话工作区 + setting_sources=['project']", tmp_ws, ["project"]),
        ("3 仓库根 + setting_sources=['project']", ROOT, ["project"]),
        ("4 仓库根 + setting_sources=[]", ROOT, []),
    ]
    results = {}
    try:
        for label, cwd, sources in cases:
            results[label] = asyncio.run(probe(label, creds, cwd, sources))
    finally:
        shutil.rmtree(tmp_ws, ignore_errors=True)

    print("\n" + "=" * 60, flush=True)
    for label, r in results.items():
        names = r.get("discovered") or []
        print(f"[{label}] discovered={len(names)} xlpa_in_inventory={'xlpa' in names}",
              flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
