"""会话列表"初始化中…"滞留缺陷的诊断对照环。

- 控制组（后端状态机）：初始化完成后 GET /api/sessions 的 status 必须为
  ready —— 证明后端 creating→ready 翻转正常（runtime.py 慢路）。
- 前端 seam（test_static_frontend.py）：session_ready 事件处理必须刷新
  会话列表 —— 缺失时列表行停留在创建时的 creating 快照。
"""

from __future__ import annotations

import importlib.util
import time
from pathlib import Path

_SMOKE_PATH = Path(__file__).resolve().parents[1] / "tools" / "dev_smoke_server.py"


def _load_smoke_module():
    """按文件路径加载 dev_smoke_server（含进程内桩），避免依赖包导入。"""
    spec = importlib.util.spec_from_file_location(
        "dev_smoke_server_diag", _SMOKE_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_session_status_flips_to_ready_after_init():
    """控制组：初始化（快慢两路）完成后，会话列表 status 必须翻转为 ready。"""
    mod = _load_smoke_module()
    app, _data_dir = mod.build_app()
    from fastapi.testclient import TestClient

    # with 上下文维持 portal/事件循环存活，慢路后台任务才能跑完
    with TestClient(app, base_url="http://127.0.0.1:8800") as client:
        login = client.post(
            "/api/auth/login",
            json={"username": "demo", "password": mod.SMOKE_PASSWORD},
        )
        assert login.status_code == 200
        token = login.json()["session_token"]
        headers = {"Authorization": f"Bearer {token}"}

        created = client.post(
            "/api/sessions",
            json={"account_source": "default", "pat": "", "remember": False},
            headers=headers,
        )
        assert created.status_code == 200
        sid = created.json()["session_id"]

        # 快路立即返回 creating；轮询等待慢路翻转（桩依赖全 fake，秒级完成）
        deadline = time.time() + 10
        status = None
        while time.time() < deadline:
            items = client.get(
                "/api/sessions", headers=headers
            ).json()["sessions"]
            row = next(
                (s for s in items if s["session_id"] == sid), None
            )
            assert row is not None, "会话行消失"
            status = row["status"]
            if status == "ready":
                break
            time.sleep(0.2)
        assert status == "ready", f"后端状态滞留 {status!r}，未翻转 ready"
