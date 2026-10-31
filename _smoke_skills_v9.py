"""技能发现根因验证 v9：项目技能是按 cwd 本级查 .qoder/skills 还是向上追溯。

前序实测（同 SDK / 同 MCP / 同模型）：
- v7：cwd=仓库根 + sources=['project']  -> 发现 xlpa
- v7：cwd=%TEMP%  + sources=['project']  -> 0
- v8：cwd=webchat_data/workspaces/<sid> + sources=['project'] -> 0
- v8：同上 + skills='all' -> 5（imagegen、sites:*，均为全局技能，无项目技能）

v8 的 cwd 位于仓库树内却仍发现不到项目技能，故"向上追溯"假设不成立。
v9 验证落地路径：把技能包放入会话工作区自身，是否即可被发现。
组：
- U1 workspace/.qoder/skills/xlpa + sources=['project'] + skills=['xlpa']
- U2 同 U1 但 sources=[]（验证 project 是否仍为必要条件）
- U3 workspace 不放技能 + cwd=仓库根 + skills='all'（量化全量暴露面）
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

MCP_URL = (f"http://127.0.0.1:"
           f"{int(os.environ.get('SMOKE_MCP_PORT', '8793'))}/mcp")
MODEL = "DeepSeek-Flash"
ASK = ("不要调用任何工具。只输出一行：你可用 Skill 工具唤起的技能名"
       "（无则 NONE）。")
SRC_SKILL = ROOT / ".qoder" / "skills" / "xlpa"


def setup_env() -> dict[str, str]:
    """加载凭据。"""
    load_env_file(ENV_FILE)
    load_env_file(ROOT / "mcp_server" / ".env")
    pat = os.environ.get("QODERCN_PERSONAL_ACCESS_TOKEN", "")
    tok = os.environ.get("MCP_AUTH_TOKEN", "")
    if not pat or not tok:
        raise RuntimeError("缺少 PAT / MCP_AUTH_TOKEN")
    return {"pat": pat, "tok": tok}


def make_ws(name: str, *, with_skill: bool) -> Path:
    """建会话工作区；with_skill 时把 xlpa 技能包复制进 workspace/.qoder/skills。"""
    ws = (ROOT / "webchat" / "webchat_data" / "workspaces"
          / (name + "_" + os.urandom(4).hex()))
    for sub in ("xlpa-tmp", "xlpa-input", "xlpa-output"):
        (ws / sub).mkdir(parents=True)
    if with_skill:
        dst = ws / ".qoder" / "skills" / "xlpa"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(SRC_SKILL, dst)
    return ws


def build_options(creds: dict, cwd: Path, sources: list[str],
                  skills: Any) -> q.QoderAgentOptions:
    """生产同构，只变 setting_sources / skills / cwd 内容。"""
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


async def probe(label: str, creds: dict, cwd: Path, sources: list[str],
                skills: Any) -> dict:
    """连接一次，读发现清单 + 模型自述。"""
    out: dict[str, Any] = {"cwd": str(cwd), "sources": sources,
                           "skills_arg": repr(skills)}
    client = q.QoderSDKClient(options=build_options(creds, cwd, sources, skills))
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
        out["model_says"] = " ".join(texts)[:400]
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"[:200]
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass
    print(f"\n===== {label} =====", flush=True)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:1600], flush=True)
    return out


def main() -> int:
    """跑三组。"""
    creds = setup_env()
    made: list[Path] = []
    results = {}
    try:
        ws_u1 = make_ws("_probe9_u1", with_skill=True)
        ws_u2 = make_ws("_probe9_u2", with_skill=True)
        made += [ws_u1, ws_u2]
        cases = [
            ("U1 workspace 内置技能包 + sources=['project']", ws_u1,
             ["project"], ["xlpa"]),
            ("U2 workspace 内置技能包 + sources=[]", ws_u2, [], ["xlpa"]),
            ("U3 cwd=仓库根 + skills='all'（暴露面量化）", ROOT,
             ["project"], "all"),
        ]
        for label, cwd, sources, skills in cases:
            results[label] = asyncio.run(
                probe(label, creds, cwd, sources, skills))
    finally:
        for ws in made:
            shutil.rmtree(ws, ignore_errors=True)

    print("\n" + "=" * 60, flush=True)
    for label, r in results.items():
        names = r.get("discovered") or []
        print(f"[{label}] discovered={len(names)} xlpa={'xlpa' in names} "
              f"{names[:35]}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
