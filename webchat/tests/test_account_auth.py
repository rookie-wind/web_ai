"""webchat 账号准入全场景测试（平台 API 一律 fake，不依赖外网）。"""

from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

from webchat.accounts import AccountsStore
from webchat.api import create_app
from webchat.config import Settings, load_settings
from webchat.hashing import encode_password, verify_password
from webchat.platform_auth import PlatformLoginError

# 低迭代哈希加速测试（生产默认 480000）
FAST_ITERATIONS = 1000
PASSWORD = "test-password-1"
PHONE = "13900000000"
SUPER_PHONE = "13912986342"
USER_ID = "1001"

PLATFORM_OK = {
    "userId": USER_ID,
    "phone": PHONE,
    "token": "biz-token-1",
}
PLATFORM_SUPER_OK = {
    "userId": "9001",
    "phone": SUPER_PHONE,
    "token": "biz-token-super",
}


def _write_accounts(tmp_path, entries: list[dict]) -> str:
    """写账号库临时文件，返回路径。"""
    path = tmp_path / "webchat_accounts.json"
    path.write_text(
        json.dumps({"accounts": entries}, ensure_ascii=False), encoding="utf-8"
    )
    return str(path)


def _write_permissions(tmp_path, phones: list[str], user_ids: list[str]) -> str:
    """写 permissions.json 临时文件，返回路径。"""
    path = tmp_path / "permissions.json"
    path.write_text(
        json.dumps(
            {"superAccounts": {"userIds": user_ids, "phones": phones}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return str(path)


def _make_settings(
    tmp_path,
    accounts_path,
    permissions_path,
    *,
    ttl: int = 3600,
    rate_max_failures: int = 1000,
) -> Settings:
    """构造测试 Settings（含运行时段默认值）。"""
    return Settings(
        session_ttl=ttl,
        rate_window=60,
        rate_max_failures=rate_max_failures,
        accounts_path=accounts_path,
        permissions_path=permissions_path,
        platform_base_url="https://platform.test",
        host="127.0.0.1",
        port=8800,
        mint_secret="test-mint-secret",
        mint_url="http://127.0.0.1:8765",
        max_instances=4,
        max_sessions_per_user=2,
        max_turns=25,
        workspaces_dir=tmp_path / "workspaces",
        events_dir=tmp_path / "events",
        lease_ttl=45,
        grant_ttl=300,
        gate_audit_path=tmp_path / "gate_audit.jsonl",
    )


def _make_client(
    tmp_path,
    *,
    accounts: list[dict] | None = None,
    super_phones: list[str] | None = None,
    super_ids: list[str] | None = None,
    platform_result: dict | None = None,
    platform_error: PlatformLoginError | None = None,
    ttl: int = 3600,
    rate_max_failures: int = 1000,
) -> TestClient:
    """构造 TestClient：账号库 + 权限文件 + fake 平台登录。"""
    accounts_path = _write_accounts(tmp_path, accounts or [])
    permissions_path = _write_permissions(tmp_path, super_phones or [], super_ids or [])
    settings = _make_settings(
        tmp_path, accounts_path, permissions_path,
        ttl=ttl, rate_max_failures=rate_max_failures,
    )

    async def fake_login(phone, code, base_url, transport=None):
        if platform_error is not None:
            raise platform_error
        return platform_result or PLATFORM_OK

    return TestClient(create_app(settings, platform_login_impl=fake_login))


def _account(password: str = PASSWORD, enabled: bool = True, **overrides) -> dict:
    """构造账号条目（默认启用、低迭代哈希）。"""
    entry = {
        "username": "alice",
        "password_hash": encode_password(password, FAST_ITERATIONS),
        "phone": PHONE,
        "code": "9413",
        "enabled": enabled,
    }
    entry.update(overrides)
    return entry


# ── 哈希 ──


def test_hash_roundtrip_and_rejects_wrong_password() -> None:
    """哈希往返校验：正确通过、错误拒绝、不同盐产生不同哈希。"""
    encoded = encode_password(PASSWORD, FAST_ITERATIONS)
    assert encoded.startswith("pbkdf2_sha256$")
    assert verify_password(PASSWORD, encoded)
    assert not verify_password("wrong", encoded)
    assert encode_password(PASSWORD, FAST_ITERATIONS) != encoded


def test_verify_rejects_malformed() -> None:
    """非法格式与非法迭代返回 False 而非抛异常。"""
    assert not verify_password(PASSWORD, "md5$1000$abc$def")
    assert not verify_password(PASSWORD, "pbkdf2_sha256$0$abc$def")
    assert not verify_password(PASSWORD, "not-a-hash")


# ── 配置 ──


def test_settings_invalid_values_raise() -> None:
    """非法配置启动即报错。"""
    with pytest.raises(ValueError):
        load_settings({"WEBCHAT_SESSION_TTL": "abc"})
    with pytest.raises(ValueError):
        load_settings({"WEBCHAT_LOGIN_RATE_LIMIT": "60"})
    with pytest.raises(ValueError):
        load_settings({"WEBCHAT_PORT": "99999"})


# ── 登录 ──


def test_login_success_and_me(tmp_path) -> None:
    """正确账密 → 票据 → /me 返回身份与角色。"""
    client = _make_client(tmp_path, accounts=[_account()], super_phones=[SUPER_PHONE])
    resp = client.post("/api/auth/login", json={"username": "alice", "password": PASSWORD})
    assert resp.status_code == 200
    body = resp.json()
    token = body["session_token"]
    assert token and body["username"] == "alice"
    assert body["is_super"] is False  # 平台身份是普通账号，未命中 super
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    me_body = me.json()
    assert me_body["username"] == "alice"
    assert me_body["phone_tail"] == PHONE[-4:]
    assert "token" not in me_body  # 业务 Token 不出现在响应


def test_login_wrong_password_and_unknown_user_same_401(tmp_path) -> None:
    """错误密码与不存在用户返回同构 401（防枚举）。"""
    client = _make_client(tmp_path, accounts=[_account()])
    wrong = client.post(
        "/api/auth/login", json={"username": "alice", "password": "bad"}
    )
    unknown = client.post(
        "/api/auth/login", json={"username": "nobody", "password": "bad"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]


def test_disabled_account_rejected(tmp_path) -> None:
    """disabled 账号拒绝登录（同构 401）。"""
    client = _make_client(tmp_path, accounts=[_account(enabled=False)])
    resp = client.post("/api/auth/login", json={"username": "alice", "password": PASSWORD})
    assert resp.status_code == 401


def test_platform_login_failure_masked(tmp_path) -> None:
    """平台登录失败：401 + 脱敏尾号，不泄露完整手机号。"""
    client = _make_client(
        tmp_path,
        accounts=[_account()],
        platform_error=PlatformLoginError("平台登录被拒绝"),
    )
    resp = client.post("/api/auth/login", json={"username": "alice", "password": PASSWORD})
    assert resp.status_code == 401
    detail = resp.json()["detail"]
    assert PHONE not in detail
    assert PHONE[-4:] in detail


def test_super_account_role_from_permissions(tmp_path) -> None:
    """绑定账号命中 superAccounts → is_super=true（写权限唯一判据）。"""
    client = _make_client(
        tmp_path,
        accounts=[_account(phone=SUPER_PHONE)],
        super_phones=[SUPER_PHONE],
        platform_result=PLATFORM_SUPER_OK,
    )
    resp = client.post("/api/auth/login", json={"username": "alice", "password": PASSWORD})
    assert resp.status_code == 200
    assert resp.json()["is_super"] is True


def test_superaccounts_alone_grants_no_access(tmp_path) -> None:
    """两份名单互不替代：仅命中 superAccounts 而账号库无条目 → 无法准入。"""
    client = _make_client(tmp_path, accounts=[], super_phones=[SUPER_PHONE])
    resp = client.post(
        "/api/auth/login", json={"username": "alice", "password": PASSWORD}
    )
    assert resp.status_code == 401


def test_accounts_store_config_error_503(tmp_path) -> None:
    """账号库缺失/损坏 → 503 明确配置错误。"""
    # 缺失：accounts 路径指向不存在的文件
    missing_path = tmp_path / "missing.json"
    settings = _make_settings(
        tmp_path, missing_path, _write_permissions(tmp_path, [], [])
    )
    client = TestClient(create_app(settings))
    resp = client.post("/api/auth/login", json={"username": "x", "password": "y"})
    assert resp.status_code == 503
    # 损坏：JSON 非法
    bad_path = tmp_path / "bad.json"
    bad_path.write_text("{not json", encoding="utf-8")
    settings2 = _make_settings(
        tmp_path, bad_path, _write_permissions(tmp_path, [], [])
    )
    client2 = TestClient(create_app(settings2))
    assert client2.post(
        "/api/auth/login", json={"username": "x", "password": "y"}
    ).status_code == 503


# ── 账号库热加载 ──


def test_accounts_hot_reload_on_change(tmp_path) -> None:
    """账号库 mtime 变化后自动重载：新增可查、损坏置配置错误。"""
    path = tmp_path / "accounts.json"
    path.write_text(
        json.dumps({"accounts": [_account()]}, ensure_ascii=False),
        encoding="utf-8",
    )
    store = AccountsStore(path)
    assert store.find("alice") is not None

    # 新增账号（显式推进 mtime，规避文件系统时间粒度）
    bob = _account(username="bob", phone="13900000001")
    path.write_text(
        json.dumps({"accounts": [bob]}, ensure_ascii=False), encoding="utf-8"
    )
    os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 1_000_000))
    assert store.find("bob") is not None
    assert store.find("alice") is None

    # 损坏：热加载后进入配置错误状态
    path.write_text("{not json", encoding="utf-8")
    os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 1_000_000))
    assert store.config_error is not None
    assert store.find("bob") is None


# ── 票据 ──


def test_logout_revokes_token(tmp_path) -> None:
    """登出后票据立即失效。"""
    client = _make_client(tmp_path, accounts=[_account()])
    token = client.post(
        "/api/auth/login", json={"username": "alice", "password": PASSWORD}
    ).json()["session_token"]
    assert client.post(
        "/api/auth/logout", headers={"Authorization": f"Bearer {token}"}
    ).status_code == 200
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 401


def test_token_expires_after_ttl(tmp_path) -> None:
    """票据 TTL 过期后 /me 拒绝（ttl=1 秒）。"""
    import time as _time

    client = _make_client(tmp_path, accounts=[_account()], ttl=1)
    token = client.post(
        "/api/auth/login", json={"username": "alice", "password": PASSWORD}
    ).json()["session_token"]
    _time.sleep(1.2)
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 401


# ── 限流 ──


def test_rate_limit_blocks_after_threshold(tmp_path) -> None:
    """连续失败超阈值 → 429 + Retry-After。"""
    client = _make_client(tmp_path, accounts=[_account()], rate_max_failures=3)
    for _ in range(3):
        resp = client.post(
            "/api/auth/login", json={"username": "alice", "password": "bad"}
        )
        assert resp.status_code == 401
    blocked = client.post(
        "/api/auth/login", json={"username": "alice", "password": PASSWORD}
    )
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers


# ── 业务凭据不外泄 ──


def test_business_token_never_in_responses(tmp_path) -> None:
    """登录与 /me 响应中均不含业务 Token。"""
    client = _make_client(tmp_path, accounts=[_account()])
    login_body = client.post(
        "/api/auth/login", json={"username": "alice", "password": PASSWORD}
    ).json()
    assert "biz-token-1" not in json.dumps(login_body, ensure_ascii=False)
    me_body = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {login_body['session_token']}"},
    ).json()
    assert "biz-token-1" not in json.dumps(me_body, ensure_ascii=False)
