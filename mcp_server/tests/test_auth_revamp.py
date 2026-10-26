"""鉴权改造（rev3）新增测试。

覆盖：
  - login role 双源判定：内置账号命中即 system，即使 superAccounts 未命中
  - 并发回归：内置 token 失效时，多用户各自用本人 fallback 独立只读；普通 user 不写内置
  - 重启持久化：本机 token 写入 registry 重启后仍有效；内置凭据 update 持久化到 permissions.json
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_MCP_DIR = Path(__file__).parent.parent
if str(_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_MCP_DIR))
import os

os.environ.setdefault("MCP_AUTH_TOKEN", "test_token")


@pytest.fixture(autouse=True)
def reset_globals():
    """清理全局 session 与 system token 状态。"""
    import server

    server.session_registry.clear()
    server.system_token_mgr._token = None
    server.system_token_mgr._phone = ""
    server.system_token_mgr._code = ""
    server.mcp_token_var.set("")
    yield


# ═══════════════════════════════════════════════════════════
# 1. login role 双源判定
# ═══════════════════════════════════════════════════════════


class TestLoginDoubleSource:
    @pytest.mark.asyncio
    async def test_inbuilt_phone_is_system_even_if_not_whitelisted(self):
        """内置账号命中→system，即使 superAccounts 未命中。"""
        import server

        server.mcp_token_var.set("tok_inbuilt")
        server.system_token_mgr._phone = "13912986342"  # 内置账号
        server.system_token_mgr._code = "9413"
        server.system_token_mgr._token = "valid_sys"
        with patch.object(
            server.api_client, "login", new_callable=AsyncMock
        ) as mock_login:
            mock_login.return_value = {
                "data": {"token": "biz_tok", "userId": "u001"},
            }
            with patch.object(
                server.super_account_config, "is_super", return_value=False
            ):
                result = await server.login("13912986342", "9413")
        assert result["success"] is True
        assert result["role"] == "super"
        assert "系统账号" in result["message"]

    @pytest.mark.asyncio
    async def test_non_inbuilt_phone_is_user_even_if_fallback_absent(self):
        """非内置且不在白名单→user。"""
        import server

        server.mcp_token_var.set("tok_u")
        server.system_token_mgr._phone = "13912986342"
        server.system_token_mgr._token = "valid_sys"
        with patch.object(
            server.api_client, "login", new_callable=AsyncMock
        ) as mock_login:
            mock_login.return_value = {
                "data": {"token": "u_biz", "userId": "999"},
            }
            with patch.object(
                server.super_account_config, "is_super", return_value=False
            ):
                result = await server.login("13800000001", "1234")
        assert result["success"] is True
        assert result["role"] == "user"
        assert "只读权限" in result["message"]


# ═══════════════════════════════════════════════════════════
# 2. 并发回归：内置失效后各 user 各自 fallback 独立只读
# ═══════════════════════════════════════════════════════════


class TestConcurrentIndependentRead:
    async def _run_for(self, mcp_token, fallback):
        import server

        server.mcp_token_var.set(mcp_token)
        server.session_registry.create(mcp_token, "138", "user", fallback)
        return await server._call_platform(self.mock_fn)

    @pytest.mark.asyncio
    async def test_two_users_each_use_own_fallback(self):
        import server

        # 内置 token 设为失效值（非 None），内置平台 also 连不上 → arefresh 失败
        server.system_token_mgr._token = "expired_sys"
        server.system_token_mgr._phone = "13912986342"
        server.system_token_mgr._code = "9413"

        seen: list[str] = []

        async def flaky(token, *a, **k):
            seen.append(token)
            if token == "expired_sys":
                return {"error": True, "code": "AUTH_ERROR"}
            return {"error": False, "data": f"data-{token}"}

        self.mock_fn = AsyncMock(side_effect=flaky)

        async def fail_refresh():
            return False

        with patch.object(
            server.system_token_mgr, "arefresh", side_effect=fail_refresh
        ):
            ra = await self._run_for("tokA", "fbA")
            rb = await self._run_for("tokB", "fbB")

        assert ra["data"] == "data-fbA"
        assert rb["data"] == "data-fbB"
        # 各自独立：A 用 fbA、B 用 fbB，互不串用
        assert "fbA" in seen and "fbB" in seen

    @pytest.mark.asyncio
    async def test_user_read_does_not_touch_inbuilt_credentials(self):
        """普通 user 只读降级不会改写内置凭据。"""
        import server

        server.system_token_mgr._token = "expired_sys"
        server.system_token_mgr._phone = "13912986342"
        server.system_token_mgr._code = "9413"

        async def flaky(token, *a, **k):
            if token == "expired_sys":
                return {"error": True, "code": "AUTH_ERROR"}
            return {"error": False, "data": "ok"}

        self.mock_fn = AsyncMock(side_effect=flaky)

        async def fail_refresh():
            return False

        with patch.object(
            server.system_token_mgr, "arefresh", side_effect=fail_refresh
        ):
            result = await self._run_for("tokX", "fbX")
        assert result["data"] == "ok"
        # 内置凭据未被动过（普通 user 不 update）
        assert server.system_token_mgr._phone == "13912986342"
        assert server.system_token_mgr._code == "9413"


# ═══════════════════════════════════════════════════════════
# 3. 重启持久化
# ═══════════════════════════════════════════════════════════


class TestRestartPersistence:
    def test_local_token_persists_across_restart(self):
        from server import TokenManager

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            tmp = Path(f.name)
        try:
            mgr = TokenManager(admin_token="admin_tok", registry_path=tmp)
            tok = mgr.get_or_create_token("127.0.0.1")  # 本机
            assert tok == "admin_tok"

            # 模拟重启：registry 保留，.env 换成别的 admin token
            mgr2 = TokenManager(admin_token="OTHER_ADMIN", registry_path=tmp)
            assert mgr2.is_valid("admin_tok")  # 重启后旧本机 token 仍有效
            info = mgr2.get_token_info("127.0.0.1")
            assert info["token"] == "admin_tok"  # 复用 registry，而非 OTHER_ADMIN
        finally:
            tmp.unlink(missing_ok=True)

    def test_inbuilt_credentials_persist_via_update(self):
        from token_manager import SystemTokenManager

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "permissions.json"
            p.write_text(
                json.dumps({"systemAccount": {"phone": "old", "code": "old"}}),
                encoding="utf-8",
            )
            client = AsyncMock()
            client.login.return_value = {
                "error": False,
                "data": {"token": "t", "userId": "u"},
            }
            mgr = SystemTokenManager(client, p)
            ok = mgr.update_credentials("13912986342", "9413")
            assert ok is True
            disk = json.loads(p.read_text(encoding="utf-8"))
            assert disk["systemAccount"]["phone"] == "13912986342"
            assert disk["systemAccount"]["code"] == "9413"