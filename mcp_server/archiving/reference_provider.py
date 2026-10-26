"""固定参考环境字典读取提供者（阶段一模板生成专用）。

两条互相隔离的读取链，均只认管理员提供的参考来源：

- 云端链：只使用服务端系统 Token（``SystemTokenManager`` 注入的只读回调）。
  Token 失效时刷新**一次**并重试；刷新失败或仍失效一律抛
  :class:`ReferenceAuthError`，**绝不**回退用户 ``session.fallback_token``
  或任何个人云端会话（design §1）。
- 边缘链：用独立 ``XLPA_REFERENCE_EDGE_*`` 三件套对参考边缘做真实 RSA 签名
  登录（:class:`EdgeDeviceClient`），登录一次复用同一会话；不与现场连接互补。

本模块只做 2.2 范围：配置消费 + 系统 Token 专用链 + 边缘登录生命周期 +
已核实路径的字典取数骨架。完整分页、同名异码检测、作用域关联与快照归一化
属后续任务（2.3 / 2.4）。
"""

from __future__ import annotations

__all__ = [
    "ReferenceDictProvider",
    "ReferenceAuthError",
    "ReferenceDictError",
    "EDGE_DICT_ITEM_LIST_PATH",
    "EDGE_DEVICE_TYPE_SELECT_PATH",
    "COMM_MODE_DICT_TYPE_CODE",
]

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from edge_client import EdgeApiError, EdgeDeviceClient
from permissions import is_auth_expired

from .reference_config import ReferenceConfig

if TYPE_CHECKING:
    from api_client import ProtocolApiClient

# 参考边缘字典项接口路径（design §1，实测无 /v1 后缀）
EDGE_DICT_ITEM_LIST_PATH = "/sysConfigServer/dict/get/getDictItemList"
# 参考边缘设备类型下拉接口路径（Path B 175 实测，带 /v1）
EDGE_DEVICE_TYPE_SELECT_PATH = "/devArchManager/doc/get/getDeviceTypeSelect/v1"
# 代理通信方式字典类型编码（CommunicationMode）
COMM_MODE_DICT_TYPE_CODE = "CommunicationMode"


class ReferenceAuthError(Exception):
    """参考云端认证不可用（无系统 Token 或刷新失败），不回退用户会话。"""


class ReferenceDictError(Exception):
    """参考字典读取业务失败（非认证类）。"""

    def __init__(self, message: str, *, raw: Any = None):
        """初始化异常。

        Args:
            message: 可读错误描述。
            raw: 后端原始返回，供排障（调用方须脱敏后展示）。
        """
        super().__init__(message)
        self.raw = raw


class ReferenceDictProvider:
    """参考环境字典读取提供者。

    构造时注入依赖，不反向 import ``server.py``（design §4）：

    - ``system_token_accessor``：返回当前系统 Token 的只读回调
      （对应 ``SystemTokenManager.get_token``）。
    - ``system_token_refresher``：异步刷新系统 Token 的回调
      （对应 ``SystemTokenManager.arefresh``）。
    - ``api_client``：云端规约平台客户端。
    - ``edge_client_factory``：参考边缘客户端工厂，默认
      :class:`EdgeDeviceClient`，测试可注入替身。
    """

    def __init__(
        self,
        config: ReferenceConfig,
        *,
        api_client: "ProtocolApiClient",
        system_token_accessor: Callable[[], str | None],
        system_token_refresher: Callable[[], Awaitable[bool]],
        edge_client_factory: Callable[..., EdgeDeviceClient] | None = None,
    ):
        """初始化提供者。

        Args:
            config: 参考环境配置。
            api_client: 云端客户端实例。
            system_token_accessor: 系统 Token 只读回调。
            system_token_refresher: 系统 Token 异步刷新回调。
            edge_client_factory: 边缘客户端工厂（默认 EdgeDeviceClient）。
        """
        self._config = config
        self._api = api_client
        self._get_system_token = system_token_accessor
        self._refresh_system_token = system_token_refresher
        self._edge_factory = edge_client_factory or EdgeDeviceClient
        self._edge: EdgeDeviceClient | None = None

    @property
    def api_client(self) -> "ProtocolApiClient":
        """云端客户端（只读暴露，供分页驱动按方法名取用）。"""
        return self._api

    # ── 云端：系统 Token 专用链（绝不回退用户会话）──

    async def cloud_call(
        self, api_method: Callable[..., Awaitable[dict]], *args, **kwargs
    ) -> dict:
        """以系统 Token 调用云端读接口，失效刷新一次后重试。

        Args:
            api_method: 云端 api_client 的异步方法（首参为 token）。
            *args: 位置参数（透传，token 之后）。
            **kwargs: 关键字参数（透传）。

        Returns:
            api_client 统一成功返回结构。

        Raises:
            ReferenceAuthError: 无系统 Token、刷新失败或刷新后仍失效。
            ReferenceDictError: 非认证类业务失败。
        """
        self._config.require_cloud()
        token = self._get_system_token()
        if not token:
            raise ReferenceAuthError(
                "参考云端认证不可用：服务端无有效系统 Token（不回退用户会话）"
            )
        result = await api_method(token, *args, **kwargs)
        if is_auth_expired(result):
            refreshed = await self._refresh_system_token()
            if not refreshed:
                raise ReferenceAuthError(
                    "参考云端认证不可用：系统 Token 刷新失败（不回退用户会话）"
                )
            token = self._get_system_token()
            if not token:
                raise ReferenceAuthError(
                    "参考云端认证不可用：刷新后仍无系统 Token（不回退用户会话）"
                )
            result = await api_method(token, *args, **kwargs)
            if is_auth_expired(result):
                raise ReferenceAuthError(
                    "参考云端认证不可用：刷新后系统 Token 仍失效（不回退用户会话）"
                )
        if isinstance(result, dict) and result.get("error"):
            raise ReferenceDictError(
                str(result.get("message") or "参考云端读取失败"), raw=result
            )
        return result

    async def fetch_user_big_no(self) -> dict:
        """读取云端设备类型列表（用户大分类来源）。

        Returns:
            api_client 统一成功结构，``data.rows`` 为类型记录。
        """
        return await self.cloud_call(self._api.get_device_type_list)

    async def fetch_brands(self) -> dict:
        """读取云端品牌列表。

        Returns:
            api_client 统一成功结构。
        """
        return await self.cloud_call(self._api.get_brand_list)

    async def fetch_models(self) -> dict:
        """读取云端型号列表。

        Returns:
            api_client 统一成功结构。
        """
        return await self.cloud_call(self._api.get_model_list)

    # ── 边缘：真实签名登录生命周期（独立参考来源）──

    def open_edge(self) -> EdgeDeviceClient:
        """打开（或复用）参考边缘签名会话。

        使用独立参考边缘三件套登录，绝不以现场连接补位。

        Returns:
            已登录的 :class:`EdgeDeviceClient`。

        Raises:
            ReferenceConfigError: 参考边缘配置不完整。
            EdgeApiError: 登录失败或网络错误。
        """
        self._config.require_edge()
        if self._edge is None:
            client = self._edge_factory(
                self._config.reference_edge_url,
                self._config.reference_edge_login_name,
                self._config.reference_edge_password,
            )
            try:
                client.login()
            except Exception:
                # 登录失败不缓存半成品会话，关闭并重置以便重试重新登录
                try:
                    client.close()
                except Exception:  # noqa: BLE001 - 清理失败不掩盖登录错误
                    pass
                raise
            self._edge = client
        return self._edge

    def edge_call(self, path: str, payload: dict | None = None) -> dict:
        """以参考边缘签名会话调用接口。

        Args:
            path: 接口路径。
            payload: 请求体，默认空字典。

        Returns:
            归一化结构 ``{ok, rtnCode, rtnMsg, data}``。

        Raises:
            ReferenceDictError: 后端返回码非零。
        """
        client = self.open_edge()
        try:
            result = client.call(path, payload or {})
        except EdgeApiError as exc:
            raise ReferenceDictError(
                f"参考边缘调用失败: {path}（{exc}）", raw=str(exc)
            ) from exc
        if not result.get("ok"):
            raise ReferenceDictError(
                f"参考边缘返回非零: {path} {result.get('rtnMsg', '')}",
                raw=result,
            )
        return result

    def fetch_device_types(self) -> dict:
        """读取参考边缘设备类型下拉（getDeviceTypeSelect）。

        Returns:
            归一化结构，``data`` 为 ``[{code, name}]`` 列表（无分页）。
        """
        return self.edge_call(EDGE_DEVICE_TYPE_SELECT_PATH, {})

    def fetch_comm_modes(self) -> dict:
        """读取参考边缘代理通信方式字典（CommunicationMode）。

        Returns:
            归一化结构，``data`` 为字典项集合。
        """
        return self.edge_call(
            EDGE_DICT_ITEM_LIST_PATH,
            {"dictTypeCode": COMM_MODE_DICT_TYPE_CODE},
        )

    def close(self) -> None:
        """关闭参考边缘会话（若已打开）。"""
        if self._edge is not None:
            self._edge.close()
            self._edge = None

    def __enter__(self) -> "ReferenceDictProvider":
        """支持 with 语法，进入时返回自身。"""
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """退出 with 时关闭边缘会话。"""
        self.close()
