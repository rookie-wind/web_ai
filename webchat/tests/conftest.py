"""C5 共享测试脚手架：fake 登录/mint/revoke + 账号库 + 可注入 agent 句柄。

既有测试自带脚手架（保持不动）；本文件供产物上传/下载/保留期测试复用，
避免三份重复的账号与 Settings 构造。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from webchat.api import create_app
from webchat.config import Settings
from webchat.hashing import encode_password
from webchat.runtime import SessionRuntime
from webchat.sdk_runtime import WEvent

FAST_ITERATIONS = 1000
PASSWORD = "test-password-1"
PHONE_ALICE = "13900000000"
PHONE_BOB = "13900000001"


class NoopHandle:
    """伪造 agent 句柄：仅回显文本，不产生产物。"""

    def __init__(self, config, pat_env=None, gate=None):
        self.config = config
        self.gate = gate
        self.closed = False

    async def close(self):
        self.closed = True

    async def run_turn(self, prompt, **kwargs):
        yield WEvent(type="text_delta", payload={"text": prompt})
        yield WEvent(type="turn_done", payload={})


@pytest.fixture
def client_factory(tmp_path, monkeypatch):
    """返回 make(...) -> TestClient；可注入句柄与 Settings 覆盖项。"""

    async def fake_login(phone, code, base_url, transport=None):
        return {"userId": f"u-{phone[-1]}", "phone": phone, "token": f"biz-{phone[-1]}"}

    async def fake_mint(self, username, session_id):
        return f"tok-{username}-{session_id}"

    async def fake_revoke(self, token):
        return None

    async def fake_activate(mcp_url, token, phone, code):
        # C7 2.3：会话创建默认桩掉平台授权激活（避免真实 /mcp 连接）
        return {"success": True}

    monkeypatch.setattr(SessionRuntime, "_mint", fake_mint)
    monkeypatch.setattr(SessionRuntime, "_revoke", fake_revoke)
    monkeypatch.setattr("webchat.runtime.call_login_tool", fake_activate)

    def make(*, handle_cls=NoopHandle, settings_kwargs=None):
        accounts_path = tmp_path / "accounts.json"
        accounts_path.write_text(
            json.dumps({
                "accounts": [
                    {
                        "username": "alice",
                        "password_hash": encode_password(PASSWORD, FAST_ITERATIONS),
                        "phone": PHONE_ALICE,
                        "code": "9413",
                        "enabled": True,
                    },
                    {
                        "username": "bob",
                        "password_hash": encode_password(PASSWORD, FAST_ITERATIONS),
                        "phone": PHONE_BOB,
                        "code": "9413",
                        "enabled": True,
                    },
                ]
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        permissions_path = tmp_path / "permissions.json"
        permissions_path.write_text(
            json.dumps({"superAccounts": {"userIds": [], "phones": []}}),
            encoding="utf-8",
        )
        kwargs = dict(
            session_ttl=3600,
            rate_window=60,
            rate_max_failures=1000,
            accounts_path=accounts_path,
            permissions_path=permissions_path,
            platform_base_url="https://platform.test",
            host="127.0.0.1",
            port=8800,
            mint_secret="test-mint-secret",
            mint_url="http://127.0.0.1:8765",
            max_instances=8,
            max_sessions_per_user=3,
            max_turns=25,
            workspaces_dir=tmp_path / "workspaces",
            events_dir=tmp_path / "events",
            lease_ttl=45,
            grant_ttl=300,
            gate_audit_path=tmp_path / "gate_audit.jsonl",
        )
        kwargs.update(settings_kwargs or {})
        monkeypatch.setattr("webchat.runtime.AgentHandle", handle_cls)
        return TestClient(create_app(Settings(**kwargs), platform_login_impl=fake_login))

    return make


@pytest.fixture
def login_as(client_factory):
    """返回 login(client, username) -> Authorization 头。"""

    def login(client: TestClient, username: str = "alice") -> dict:
        resp = client.post(
            "/api/auth/login",
            json={"username": username, "password": PASSWORD},
        )
        assert resp.status_code == 200, resp.text
        return {"Authorization": f"Bearer {resp.json()['session_token']}"}

    return login


@pytest.fixture
def bootstrap(login_as):
    """返回 bootstrap(client, username) -> (headers, session_id, state)。"""

    def run(client: TestClient, username: str = "alice"):
        headers = login_as(client, username)
        created = client.post("/api/sessions", headers=headers)
        assert created.status_code == 200, created.text
        session_id = created.json()["session_id"]
        leased = client.post(
            f"/api/sessions/{session_id}/lease",
            headers=headers,
            json={"holder_id": "holder-1"},
        )
        assert leased.status_code == 200, leased.text
        return headers, session_id, client.app.state.auth

    return run
