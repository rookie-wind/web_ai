"""server-token-permission-showcase 集成测试。

覆盖：
  - login 工具：super / user / 无效参数
  - _require_session：未登录返回 NOT_LOGGED_IN
  - _require_super：非超级账号返回 FORBIDDEN
  - _call_platform：Token 失效透明刷新
  - gen_script：成功时递增 scriptsGenerated
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_MCP_DIR = Path(__file__).parent.parent
if str(_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_MCP_DIR))

os.environ.setdefault("MCP_AUTH_TOKEN", "test_token")


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def reset_globals():
    """每个测试前重置 session_registry 和 system_token_mgr。"""
    import server

    server.session_registry.clear()
    server.system_token_mgr._token = None
    server.system_token_mgr._active = False
    server.mcp_token_var.set("")
    yield


# ═══════════════════════════════════════════════════════════
# Login 工具测试
# ═══════════════════════════════════════════════════════════


class TestLoginTool:
    """login 工具三种场景。"""

    @pytest.mark.asyncio
    async def test_login_invalid_params(self):
        """无效参数返回 LOGIN_FAILED。"""
        import server

        with patch.object(
            server.api_client, "login", new_callable=AsyncMock
        ) as mock:
            mock.return_value = {"error": True}
            result = await server.login("000", "0000")
            assert result["success"] is False
            assert result["error"] == "LOGIN_FAILED"

    @pytest.mark.asyncio
    async def test_login_user_role(self):
        """普通用户 login 返回 role=user。"""
        import server

        server.mcp_token_var.set("mcp_tok_user")
        with patch.object(
            server.api_client, "login", new_callable=AsyncMock
        ) as mock:
            mock.return_value = {
                "data": {"token": "user_biz_tok", "userId": "999"},
            }
            with patch.object(
                server.super_account_config, "is_super", return_value=False
            ):
                result = await server.login("13800000001", "1234")
        assert result["success"] is True
        assert result["role"] == "user"
        sess = server.session_registry.get("mcp_tok_user")
        assert sess is not None
        assert sess.role == "user"
        assert sess.fallback_token == "user_biz_tok"

    @pytest.mark.asyncio
    async def test_login_super_role(self):
        """超级账号 login 返回 role=super。"""
        import server

        server.mcp_token_var.set("mcp_tok_super")
        server.system_token_mgr._token = "valid_sys"  # active = True
        with patch.object(
            server.api_client, "login", new_callable=AsyncMock
        ) as mock:
            mock.return_value = {
                "data": {"token": "sys_biz_tok", "userId": "001"},
            }
            with patch.object(
                server.super_account_config, "is_super", return_value=True
            ):
                result = await server.login("13912986342", "9413")
        assert result["success"] is True
        assert result["role"] == "super"


# ═══════════════════════════════════════════════════════════
# Session Guard 测试
# ═══════════════════════════════════════════════════════════


class TestRequireSession:
    """_require_session 未登录返回 NOT_LOGGED_IN。"""

    def test_no_session(self):
        import server

        server.mcp_token_var.set("unknown_token")
        result = server._require_session()
        assert isinstance(result, dict)
        assert result["code"] == "NOT_LOGGED_IN"

    def test_with_session(self):
        import server

        server.mcp_token_var.set("tok_ok")
        server.session_registry.create("tok_ok", "138", "user", None)
        result = server._require_session()
        assert not isinstance(result, dict)
        assert result.role == "user"


class TestRequireSuper:
    """_require_super 非超级返回 FORBIDDEN。"""

    def test_user_not_super(self):
        import server

        server.mcp_token_var.set("tok_u")
        server.session_registry.create("tok_u", "138", "user", "fb")
        result = server._require_super()
        assert isinstance(result, dict)
        assert result["code"] == "FORBIDDEN"

    def test_super_passes(self):
        import server

        server.mcp_token_var.set("tok_s")
        server.session_registry.create("tok_s", "139", "super", None)
        result = server._require_super()
        assert not isinstance(result, dict)
        assert result.role == "super"


# ═══════════════════════════════════════════════════════════
# _call_platform 降级链测试
# ═══════════════════════════════════════════════════════════


class TestCallPlatform:
    """透明刷新和降级链。"""

    @pytest.mark.asyncio
    async def test_no_token_returns_auth_expired(self):
        """无 system_token 和 fallback → AUTH_EXPIRED。"""
        import server

        server.mcp_token_var.set("tok_x")
        # 无 session
        result = await server._call_platform(
            AsyncMock(return_value={})
        )
        assert isinstance(result, dict)
        assert result["code"] == "AUTH_EXPIRED"

    @pytest.mark.asyncio
    async def test_system_token_success(self):
        """有 system_token → 直接成功。"""
        import server

        server.system_token_mgr._token = "valid_sys_tok"
        mock_fn = AsyncMock(return_value={"error": False, "rows": []})
        result = await server._call_platform(mock_fn, "arg1")
        mock_fn.assert_called_once_with("valid_sys_tok", "arg1")
        assert result["error"] is False

    @pytest.mark.asyncio
    async def test_token_expired_refresh_success(self):
        """system_token 过期 → 自动刷新 → 重试成功。"""
        import server

        server.system_token_mgr._token = "expired_tok"
        server.system_token_mgr._phone = "13912986342"
        server.system_token_mgr._code = "9413"

        # 第一次返回 AUTH_ERROR, 第二次成功
        mock_fn = AsyncMock(
            side_effect=[
                {"error": True, "code": "AUTH_ERROR"},
                {"error": False, "data": "ok"},
            ]
        )

        async def fake_refresh():
            server.system_token_mgr._token = "new_sys_tok"
            return True

        with patch.object(
            server.system_token_mgr, "arefresh", side_effect=fake_refresh
        ):
            result = await server._call_platform(mock_fn)
        assert result["error"] is False


# ═══════════════════════════════════════════════════════════
# Gen Script Counter
# ═══════════════════════════════════════════════════════════


class TestGenScriptCounter:
    """gen_script 成功后计数递增。"""

    @pytest.mark.asyncio
    async def test_increments_on_success(self):
        import server

        with tempfile.TemporaryDirectory() as td:
            stats_path = Path(td) / ".stats.json"
            stats_path.write_text(
                json.dumps({"scriptsGenerated": 5}), encoding="utf-8"
            )
            with patch.object(server, "STATS_PATH", stats_path):
                server.mcp_token_var.set("tok_g")
                server.session_registry.create("tok_g", "139", "super", None)
                server.system_token_mgr._token = "t"
                with patch.object(
                    server.api_client, "gen_script", new_callable=AsyncMock
                ) as mock:
                    mock.return_value = {"error": False, "success": True}
                    await server.gen_script({"test": 1})
                data = json.loads(stats_path.read_text(encoding="utf-8"))
                assert data["scriptsGenerated"] == 6


# ═══════════════════════════════════════════════════════════
# Stats Helpers
# ═══════════════════════════════════════════════════════════


class TestStatsHelpers:
    """_load_stats / _save_stats 单元测试。"""

    def test_load_default_when_missing(self):
        import server
        from pathlib import Path

        with patch.object(server, "STATS_PATH", Path("/nonexistent/.stats.json")):
            stats = server._load_stats()
            assert stats["scriptsGenerated"] == 19

    def test_save_and_load(self):
        import server

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / ".stats.json"
            with patch.object(server, "STATS_PATH", p):
                server._save_stats({"scriptsGenerated": 42, "testTotal": 10})
                loaded = server._load_stats()
                assert loaded["scriptsGenerated"] == 42
                assert loaded["testTotal"] == 10
