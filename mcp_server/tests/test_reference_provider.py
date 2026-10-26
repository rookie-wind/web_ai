"""task 2.2 验收：固定参考环境配置 + 系统 Token 专用读取链隔离测试。

三项验收（design §1）以 mock 证明，全程无网络：
  1. 无个人云端会话（无 fallback）也能取参——只认系统 Token。
  2. 缺参考配置即报错——不预置 175/23，不以现场连接补位。
  3. 刷新失败不换来源——绝不回退用户会话，绝不引入第二个 Token。

边缘侧验证真实 :class:`EdgeDeviceClient` 签名登录生命周期接线（工厂 + login +
signed call + close），且登录只用参考边缘来源。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_MCP_DIR = Path(__file__).parent.parent
if str(_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_MCP_DIR))

from archiving.reference_config import (  # noqa: E402
    ReferenceConfig,
    ReferenceConfigError,
    load_reference_config,
)
from archiving.reference_provider import (  # noqa: E402
    COMM_MODE_DICT_TYPE_CODE,
    EDGE_DICT_ITEM_LIST_PATH,
    ReferenceAuthError,
    ReferenceDictError,
    ReferenceDictProvider,
)

_SUCCESS = {
    "error": False,
    "empty": False,
    "code": 20000,
    "message": "成功",
    "data": {"rows": [{"id": 1}]},
}
_EXPIRED = {"error": True, "code": "AUTH_ERROR", "message": "Token无效或登录已失效"}
_BIZ_ERROR = {"error": True, "code": "API_ERROR", "message": "后端业务错误"}


class _FakeCloud:
    """云端客户端替身：按方法名顺序返回预置结果并记录调用。"""

    def __init__(self, responses: dict[str, list[dict]]):
        """初始化。

        Args:
            responses: 方法名到结果序列的映射，逐次弹出。
        """
        self._responses = {k: list(v) for k, v in responses.items()}
        self.calls: list[tuple[str, str]] = []

    def _pop(self, name: str, token: str) -> dict:
        self.calls.append((name, token))
        seq = self._responses.get(name) or [_SUCCESS]
        return seq.pop(0) if len(seq) > 1 else seq[0]

    async def get_device_type_list(self, token, *a, **k) -> dict:
        """返回设备类型列表替身结果。"""
        return self._pop("get_device_type_list", token)

    async def get_brand_list(self, token, *a, **k) -> dict:
        """返回品牌列表替身结果。"""
        return self._pop("get_brand_list", token)

    async def get_model_list(self, token, *a, **k) -> dict:
        """返回型号列表替身结果。"""
        return self._pop("get_model_list", token)


class _FakeEdge:
    """边缘客户端替身：记录构造参数、登录、签名调用与关闭。"""

    instances: list["_FakeEdge"] = []

    def __init__(self, base_url, login_name, password, *a, **k):
        """初始化并登记实例。"""
        self.base_url = base_url
        self.login_name = login_name
        self.password = password
        self.logged_in = False
        self.closed = False
        self.calls: list[tuple[str, dict]] = []
        _FakeEdge.instances.append(self)

    def login(self) -> dict:
        """模拟 RSA 登录成功。"""
        self.logged_in = True
        return {"ok": True, "rtnCode": 0, "rtnMsg": "", "data": {"token": "t"}}

    def call(self, path, payload=None) -> dict:
        """记录签名调用并返回成功结构。"""
        self.calls.append((path, payload or {}))
        return {
            "ok": True,
            "rtnCode": 0,
            "rtnMsg": "",
            "data": [{"dictItemCode": "13"}],
        }

    def close(self) -> None:
        """标记关闭。"""
        self.closed = True


def _provider(cfg, cloud, tokens, refresh_results):
    """构造注入式 provider（无 server.py 依赖）。"""
    token_seq = list(tokens)
    refresh_seq = list(refresh_results)
    state = {"refresh_calls": 0}

    def accessor() -> str | None:
        return token_seq[0] if token_seq else None

    async def refresher() -> bool:
        state["refresh_calls"] += 1
        ok = refresh_seq.pop(0) if refresh_seq else False
        if ok and len(token_seq) > 1:
            token_seq.pop(0)  # 刷新后切到下一个系统 Token
        return ok

    provider = ReferenceDictProvider(
        cfg,
        api_client=cloud,
        system_token_accessor=accessor,
        system_token_refresher=refresher,
        edge_client_factory=_FakeEdge,
    )
    return provider, state


_FULL_CFG = ReferenceConfig(
    reference_edge_url="http://ref-edge:7500",
    reference_edge_login_name="refuser",
    reference_edge_password="refpass",
    cloud_base_url="https://cloud.example.com",
)


# ── 验收 2：缺参考配置即报错，不预置现场地址 ──


class TestReferenceConfig:
    """参考环境配置加载与校验。"""

    def test_no_preset_field_address(self):
        """空环境不预置任何参考边缘地址/账号/密码。"""
        cfg = load_reference_config({})
        assert cfg.reference_edge_url == ""
        assert cfg.reference_edge_login_name == ""
        assert cfg.reference_edge_password == ""
        assert not cfg.edge_ready()

    def test_require_edge_raises_when_missing(self):
        """参考边缘三件套缺失时 require_edge 报错。"""
        cfg = load_reference_config({"PCA_API_BASE_URL": "https://c"})
        with pytest.raises(ReferenceConfigError):
            cfg.require_edge()

    def test_reads_env_and_preserves_password(self):
        """从环境读取三件套，密码保留原文不去空白。"""
        cfg = load_reference_config({
            "XLPA_REFERENCE_EDGE_URL": "  http://h:7500  ",
            "XLPA_REFERENCE_EDGE_LOGIN_NAME": " u ",
            "XLPA_REFERENCE_EDGE_PASSWORD": " p p ",
            "PCA_API_BASE_URL": "https://cloud",
        })
        assert cfg.reference_edge_url == "http://h:7500"
        assert cfg.reference_edge_login_name == "u"
        assert cfg.reference_edge_password == " p p "
        assert cfg.edge_ready() and cfg.cloud_ready()

    def test_redacted_masks_password(self):
        """脱敏视图掩码密码。"""
        out = _FULL_CFG.redacted()
        assert out["reference_edge_password"] != "refpass"
        assert out["reference_edge_url"] == "http://ref-edge:7500"


# ── 验收 1：无个人云端会话（无 fallback）也能取参 ──


class TestCloudSystemTokenOnly:
    """云端链只认系统 Token，绝不引入用户 fallback。"""

    @pytest.mark.asyncio
    async def test_fetch_with_system_token_only(self):
        """仅凭系统 Token 即可取参（无任何用户会话）。"""
        cloud = _FakeCloud({"get_device_type_list": [_SUCCESS]})
        provider, state = _provider(_FULL_CFG, cloud, ["SYS"], [])
        result = await provider.fetch_user_big_no()
        assert result["error"] is False
        assert cloud.calls == [("get_device_type_list", "SYS")]
        assert state["refresh_calls"] == 0

    @pytest.mark.asyncio
    async def test_no_system_token_raises_without_calling_api(self):
        """无系统 Token 直接报认证不可用，且不调用云端接口。"""
        cloud = _FakeCloud({})
        provider, _ = _provider(_FULL_CFG, cloud, [], [])
        with pytest.raises(ReferenceAuthError):
            await provider.fetch_user_big_no()
        assert cloud.calls == []

    @pytest.mark.asyncio
    async def test_business_error_raises_dict_error(self):
        """非认证类业务失败抛 ReferenceDictError，不触发刷新。"""
        cloud = _FakeCloud({"get_brand_list": [_BIZ_ERROR]})
        provider, state = _provider(_FULL_CFG, cloud, ["SYS"], [])
        with pytest.raises(ReferenceDictError):
            await provider.fetch_brands()
        assert state["refresh_calls"] == 0


# ── 验收 3：刷新失败不换来源，绝不回退用户会话 ──


class TestNoSourceSwitchOnRefresh:
    """系统 Token 失效后的刷新与来源隔离。"""

    @pytest.mark.asyncio
    async def test_refresh_failure_does_not_switch_source(self):
        """刷新失败即报认证不可用，不重试第二个 Token。"""
        cloud = _FakeCloud({"get_device_type_list": [_EXPIRED, _EXPIRED]})
        provider, state = _provider(_FULL_CFG, cloud, ["SYS"], [False])
        with pytest.raises(ReferenceAuthError):
            await provider.fetch_user_big_no()
        # 仅调用一次云端接口 + 一次刷新；绝不引入其它 Token
        assert cloud.calls == [("get_device_type_list", "SYS")]
        assert state["refresh_calls"] == 1

    @pytest.mark.asyncio
    async def test_refresh_success_retries_with_new_system_token(self):
        """刷新成功后用新系统 Token 重试一次并成功。"""
        cloud = _FakeCloud({"get_device_type_list": [_EXPIRED, _SUCCESS]})
        provider, state = _provider(_FULL_CFG, cloud, ["SYS1", "SYS2"], [True])
        result = await provider.fetch_user_big_no()
        assert result["error"] is False
        assert cloud.calls == [
            ("get_device_type_list", "SYS1"),
            ("get_device_type_list", "SYS2"),
        ]
        assert state["refresh_calls"] == 1

    @pytest.mark.asyncio
    async def test_refresh_success_but_still_expired_raises(self):
        """刷新成功但仍失效 → 报认证不可用，只调用两次。"""
        cloud = _FakeCloud({"get_model_list": [_EXPIRED, _EXPIRED]})
        provider, state = _provider(_FULL_CFG, cloud, ["SYS1", "SYS2"], [True])
        with pytest.raises(ReferenceAuthError):
            await provider.fetch_models()
        assert cloud.calls == [
            ("get_model_list", "SYS1"),
            ("get_model_list", "SYS2"),
        ]
        assert state["refresh_calls"] == 1


# ── 边缘真实签名登录接线（option B）──


class TestEdgeLoginWiring:
    """参考边缘真实登录生命周期，且只用参考来源。"""

    def test_open_edge_uses_reference_source_not_field(self):
        """边缘客户端用参考三件套登录，不以现场连接补位。"""
        _FakeEdge.instances.clear()
        provider = ReferenceDictProvider(
            _FULL_CFG,
            api_client=_FakeCloud({}),
            system_token_accessor=lambda: "SYS",
            system_token_refresher=lambda: _never(),
            edge_client_factory=_FakeEdge,
        )
        client = provider.open_edge()
        assert client.base_url == "http://ref-edge:7500"
        assert client.login_name == "refuser"
        assert client.logged_in is True
        provider.close()
        assert client.closed is True

    def test_open_edge_reuses_session(self):
        """重复 open_edge 复用同一登录会话。"""
        _FakeEdge.instances.clear()
        provider = ReferenceDictProvider(
            _FULL_CFG,
            api_client=_FakeCloud({}),
            system_token_accessor=lambda: "SYS",
            system_token_refresher=lambda: _never(),
            edge_client_factory=_FakeEdge,
        )
        provider.open_edge()
        provider.open_edge()
        assert len(_FakeEdge.instances) == 1
        provider.close()

    def test_fetch_comm_modes_uses_verified_path(self):
        """代理通信方式取数走已核实路径与 dictTypeCode。"""
        _FakeEdge.instances.clear()
        provider = ReferenceDictProvider(
            _FULL_CFG,
            api_client=_FakeCloud({}),
            system_token_accessor=lambda: "SYS",
            system_token_refresher=lambda: _never(),
            edge_client_factory=_FakeEdge,
        )
        result = provider.fetch_comm_modes()
        assert result["ok"] is True
        edge = _FakeEdge.instances[0]
        assert edge.calls == [
            (EDGE_DICT_ITEM_LIST_PATH, {"dictTypeCode": COMM_MODE_DICT_TYPE_CODE})
        ]
        provider.close()

    def test_open_edge_raises_when_config_missing(self):
        """参考边缘配置缺失时 open_edge 报错，不构造客户端。"""
        _FakeEdge.instances.clear()
        cfg = ReferenceConfig(cloud_base_url="https://c")
        provider = ReferenceDictProvider(
            cfg,
            api_client=_FakeCloud({}),
            system_token_accessor=lambda: "SYS",
            system_token_refresher=lambda: _never(),
            edge_client_factory=_FakeEdge,
        )
        with pytest.raises(ReferenceConfigError):
            provider.open_edge()
        assert _FakeEdge.instances == []


async def _never() -> bool:
    """永不成功的刷新替身（本组用例不触发刷新）。"""
    return False
