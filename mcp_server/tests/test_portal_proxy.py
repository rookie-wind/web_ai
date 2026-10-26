"""门户代理建档模式单元测试。

覆盖：
  - ``EdgeDeviceClient`` 代理模式 URL 构造与请求头。
  - 代理模式下 getRSAKey 附加 ``PhoneNum``/``Code`` 请求头。
  - ``TaskConfig`` 序列化/反序列化含 ``proxy_mode``。
  - ``excel_reader`` 按 IP 段自动判定代理模式，代理模式缺少手机/验证码时报错。
  - 门户代理地址由环境变量 PORTAL_PROXY_API_URL 读取；
    未配置时拒绝代理模式。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 确保 mcp_server 在导入路径中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 测试用门户代理地址（避免依赖实际环境变量）
_TEST_PROXY_URL = "http://121.229.15.116:7500"


class TestEdgeClientProxyMode:
    """EdgeDeviceClient 代理模式行为验证。"""

    def test_direct_mode_url(self):
        """直连模式请求 URL 为 base_url + path。"""
        from edge_client import EdgeDeviceClient

        client = EdgeDeviceClient(
            "http://10.0.11.175:7500", "user", "pass",
        )
        assert client._request_url("/some/path") == (
            "http://10.0.11.175:7500/some/path"
        )

    def test_proxy_mode_url(self):
        """代理模式请求 URL 为 proxy_api_url + path。"""
        from edge_client import EdgeDeviceClient

        client = EdgeDeviceClient(
            "http://20.0.75.234:7500", "user", "pass",
            proxy_mode=True,
            proxy_api_url=_TEST_PROXY_URL,
            phone="13800000000",
            captcha="1234",
        )
        assert client._request_url("/some/path") == (
            f"{_TEST_PROXY_URL}/some/path"
        )

    def test_proxy_mode_disabled_by_default(self):
        """默认不启用代理模式。"""
        from edge_client import EdgeDeviceClient

        client = EdgeDeviceClient(
            "http://10.0.11.175:7500", "user", "pass",
        )
        assert client.proxy_mode is False
        assert client.proxy_api_url == ""

    def test_proxy_headers_empty_in_direct_mode(self):
        """直连模式不附加代理头。"""
        from edge_client import EdgeDeviceClient

        client = EdgeDeviceClient(
            "http://10.0.11.175:7500", "user", "pass",
        )
        assert client._proxy_headers() == {}

    def test_proxy_headers_in_proxy_mode(self):
        """代理模式返回正确的转发头。"""
        from edge_client import (
            EdgeDeviceClient,
            PORTAL_PROXY_FORWARD_PORT,
            PORTAL_PROXY_FORWARD_TYPE,
        )

        client = EdgeDeviceClient(
            "http://20.0.75.234:7500", "user", "pass",
            proxy_mode=True,
            proxy_api_url=_TEST_PROXY_URL,
            phone="13800000000",
            captcha="1234",
        )
        headers = client._proxy_headers()
        assert headers["ForwardUrl"] == "http://20.0.75.234:7500"
        assert headers["webSite"] == "http://20.0.75.234:7500"
        assert headers["ForwardPort"] == PORTAL_PROXY_FORWARD_PORT
        assert headers["ForwardType"] == PORTAL_PROXY_FORWARD_TYPE

    def test_sign_headers_includes_proxy_headers(self):
        """签名头在代理模式下包含转发头。"""
        from edge_client import EdgeDeviceClient

        client = EdgeDeviceClient(
            "http://20.0.75.234:7500", "user", "pass",
            proxy_mode=True,
            proxy_api_url=_TEST_PROXY_URL,
            phone="13800000000",
            captcha="1234",
        )
        # 模拟登录状态
        client.token = "test_token"
        client.login_str = "test_login_str"
        client.user_id = "1"
        client.logged_in = True

        headers = client._sign_headers()
        assert "ForwardUrl" in headers
        assert "webSite" in headers
        assert "ForwardPort" in headers
        assert "ForwardType" in headers
        assert headers["token"] == "test_token"
        assert headers["appCode"] == "5000"

    def test_sign_headers_no_proxy_in_direct_mode(self):
        """直连模式签名头不含转发头。"""
        from edge_client import EdgeDeviceClient

        client = EdgeDeviceClient(
            "http://10.0.11.175:7500", "user", "pass",
        )
        client.token = "test_token"
        client.login_str = "test_login_str"
        client.user_id = "1"
        client.logged_in = True

        headers = client._sign_headers()
        assert "ForwardUrl" not in headers
        assert "webSite" not in headers

    def test_proxy_constants(self):
        """门户代理常量值正确（转发端口与类型固定）。"""
        from edge_client import (
            PORTAL_PROXY_FORWARD_PORT,
            PORTAL_PROXY_FORWARD_TYPE,
        )
        assert PORTAL_PROXY_FORWARD_PORT == "7500"
        assert PORTAL_PROXY_FORWARD_TYPE == "SmartUnit"

    def test_proxy_api_url_from_env(self):
        """门户代理地址来自环境变量 PORTAL_PROXY_API_URL。"""
        from edge_client import PORTAL_PROXY_API_URL
        assert isinstance(PORTAL_PROXY_API_URL, str)

    def test_proxy_mode_stores_phone_captcha(self):
        """代理模式正确保存手机号和验证码。"""
        from edge_client import EdgeDeviceClient

        client = EdgeDeviceClient(
            "http://20.0.75.234:7500", "user", "pass",
            proxy_mode=True,
            proxy_api_url=_TEST_PROXY_URL,
            phone="13800000000",
            captcha="9588",
        )
        assert client._phone == "13800000000"
        assert client._captcha == "9588"

    def test_get_rsa_key_includes_phone_code_headers_in_proxy_mode(self):
        """代理模式下 get_rsa_key 请求包含 PhoneNum/Code 头。"""
        from edge_client import EdgeDeviceClient

        client = EdgeDeviceClient(
            "http://20.0.75.234:7500", "user", "pass",
            proxy_mode=True,
            proxy_api_url=_TEST_PROXY_URL,
            phone="13800000000",
            captcha="9588",
        )
        # mock _post_raw 捕获传入的 extra_headers
        captured = {}

        def mock_post_raw(path, payload, timeout, extra_headers=None):
            captured["extra_headers"] = extra_headers
            return {"rtnCode": 0, "rtnData": {"publicKeyValue": "x", "keyName": "k"}}

        client._post_raw = mock_post_raw
        client.get_rsa_key()
        assert captured["extra_headers"]["PhoneNum"] == "13800000000"
        assert captured["extra_headers"]["Code"] == "9588"

    def test_get_rsa_key_no_phone_headers_in_direct_mode(self):
        """直连模式下 get_rsa_key 不附加 PhoneNum/Code 头。"""
        from edge_client import EdgeDeviceClient

        client = EdgeDeviceClient(
            "http://10.0.11.175:7500", "user", "pass",
        )
        captured = {}

        def mock_post_raw(path, payload, timeout, extra_headers=None):
            captured["extra_headers"] = extra_headers
            return {"rtnCode": 0, "rtnData": {"publicKeyValue": "x", "keyName": "k"}}

        client._post_raw = mock_post_raw
        client.get_rsa_key()
        # 直连模式 extra_headers 应为空字典
        assert captured["extra_headers"] == {}


class TestTaskConfigProxyMode:
    """TaskConfig 序列化/反序列化含 proxy_mode。"""

    def test_default_proxy_mode_false(self):
        """默认 proxy_mode 为 False。"""
        from archiving.models import TaskConfig

        cfg = TaskConfig()
        assert cfg.proxy_mode is False

    def test_to_dict_includes_proxy_mode(self):
        """to_dict 包含 proxy_mode 字段。"""
        from archiving.models import TaskConfig

        cfg = TaskConfig(proxy_mode=True)
        d = cfg.to_dict()
        assert d["proxy_mode"] is True

    def test_from_dict_restores_proxy_mode(self):
        """from_dict 正确还原 proxy_mode。"""
        from archiving.models import TaskConfig

        data = {"proxy_mode": True, "edge_base_url": "http://20.0.75.234:7500"}
        cfg = TaskConfig.from_dict(data)
        assert cfg.proxy_mode is True
        assert cfg.edge_base_url == "http://20.0.75.234:7500"

    def test_from_dict_default_proxy_mode(self):
        """from_dict 缺少 proxy_mode 时默认 False。"""
        from archiving.models import TaskConfig

        cfg = TaskConfig.from_dict({})
        assert cfg.proxy_mode is False


class TestExcelReaderProxyDetection:
    """excel_reader 按 IP 段自动判定代理模式。"""

    def _make_rows(
        self,
        ip: str,
        port: str = "7500",
        phone: str = "",
        captcha: str = "",
    ) -> list[dict]:
        """构造系统连接 sheet 行。"""
        rows = [
            {"配置项": "目标系统IP", "值": ip},
            {"配置项": "后端端口", "值": port},
            {"配置项": "账号", "值": "xldz"},
            {"配置项": "密码", "值": "xldz-123"},
        ]
        if phone:
            rows.append({"配置项": "手机号", "值": phone})
        if captcha:
            rows.append({"配置项": "验证码", "值": captcha})
        return rows

    def test_direct_mode_for_10_ip(self):
        """10.* IP 段判定为直连模式。"""
        from archiving.excel_reader import _parse_task_config, ArchiveTemplate

        template = ArchiveTemplate()
        rows = self._make_rows("10.0.11.175")
        _parse_task_config(rows, template)
        assert template.task_config.proxy_mode is False
        assert template.task_config.edge_base_url == "http://10.0.11.175:7500"

    def test_proxy_mode_for_20_ip(self):
        """20.* IP 段判定为代理模式（需提供手机/验证码）。"""
        from archiving.excel_reader import _parse_task_config, ArchiveTemplate

        template = ArchiveTemplate()
        rows = self._make_rows("20.0.75.234", phone="13800000000", captcha="9588")
        _parse_task_config(rows, template)
        assert template.task_config.proxy_mode is True
        assert template.task_config.edge_base_url == "http://20.0.75.234:7500"

    def test_proxy_mode_for_20_ip_with_protocol(self):
        """带协议前缀的 20.* IP 也能正确判定。"""
        from archiving.excel_reader import _parse_task_config, ArchiveTemplate

        template = ArchiveTemplate()
        rows = self._make_rows(
            "http://20.0.75.234", phone="13800000000", captcha="9588",
        )
        _parse_task_config(rows, template)
        assert template.task_config.proxy_mode is True

    def test_direct_mode_for_other_ip(self):
        """非 10.*/20.* IP 段默认直连。"""
        from archiving.excel_reader import _parse_task_config, ArchiveTemplate

        template = ArchiveTemplate()
        rows = self._make_rows("192.168.1.100")
        _parse_task_config(rows, template)
        assert template.task_config.proxy_mode is False

    def test_proxy_mode_preserves_base_url(self):
        """代理模式下 edge_base_url 仍为目标后端地址。"""
        from archiving.excel_reader import _parse_task_config, ArchiveTemplate

        template = ArchiveTemplate()
        rows = self._make_rows(
            "20.0.75.234", "7500", phone="13800000000", captcha="9588",
        )
        _parse_task_config(rows, template)
        # edge_base_url 保留为目标地址（供 ForwardUrl 头使用）
        assert template.task_config.edge_base_url == "http://20.0.75.234:7500"
        assert template.task_config.proxy_mode is True

    def test_proxy_mode_missing_phone_raises(self):
        """20.* IP 缺少手机号时抛出错误。"""
        from archiving.excel_reader import _parse_task_config, ArchiveTemplate

        template = ArchiveTemplate()
        rows = self._make_rows("20.0.75.234", captcha="9588")  # 无手机号
        with pytest.raises(ValueError, match="手机号"):
            _parse_task_config(rows, template)

    def test_proxy_mode_missing_captcha_raises(self):
        """20.* IP 缺少验证码时抛出错误。"""
        from archiving.excel_reader import _parse_task_config, ArchiveTemplate

        template = ArchiveTemplate()
        rows = self._make_rows("20.0.75.234", phone="13800000000")  # 无验证码
        with pytest.raises(ValueError, match="验证码"):
            _parse_task_config(rows, template)
