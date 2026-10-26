"""边缘建档后端客户端（RSA 登录 + 五头签名 + rtnCode 归一化）。

对接现场边缘建档后端 ``http://<IP>:7500``，与云端规约平台
``ProtocolApiClient`` 完全独立，不复用其 Token 与请求管线。

关键约束（来源 Path B 实测）：
  - 登录链路：``getRSAKey`` 取公钥 → RSA(PKCS1v15) 加密
    loginName/password/symmetricKey → ``login`` 返回 token 与 sysUser.id。
  - 每次业务调用携带五个签名头：appCode=5000、token、
    tokenEncrypt=md5(token + loginStr + dateTime)、dateTime、userId。
  - 后端统一以 ``rtnCode == 0`` 表示成功，``rtnData`` 为业务数据。
  - 联通类接口（下发/召测/通讯状态）在无实表时会阻塞，需要
    per-call 短超时，并归一化为 NOT_CONFIGURED / OFFLINE_TIMEOUT / OK。

安全：password、token、登录响应均为敏感数据，本模块不主动打印，
调用方在日志与工具返回中必须脱敏。
"""

from __future__ import annotations

__all__ = [
    "EdgeDeviceClient",
    "EdgeLinkState",
    "EdgeStageState",
    "EdgeApiError",
    "rsa_encrypt",
    "PORTAL_PROXY_API_URL",
]

import base64
import hashlib
import secrets
import time
from enum import Enum

import edge_proxy_config

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding

# 五头签名固定 appCode（来源 Path B 实测）
APP_CODE = "5000"
# 默认请求超时（普通档案读写）
DEFAULT_REQUEST_TIMEOUT = 25.0
# 联通类接口默认超时（无实表时后端会挂起，客户端侧短超时判离线）
DEFAULT_LINK_TIMEOUT = 12.0
# 代理通信方式未配置的关键字（秒拒，非阻塞）
_NOT_CONFIGURED_KEYWORDS = ("未配置", "代理通信方式", "通信方式未")
# 通讯超时的关键字（后端以 rtnCode!=0 + rtnMsg 返回）
_TIMEOUT_KEYWORDS = ("超时",)
# ── 门户代理配置（来源 portal-proxy-archiving-guide.md 实测） ──
# 门户 API 代理地址，由服务端配置文件 proxy_config.json（服务端私有运维配置）读取，
# 缺失时回退到环境变量；未配置时为空串，代理模式不会启用。
PORTAL_PROXY_API_URL = edge_proxy_config.portal_proxy_api_url()
# 门户代理转发端口（固定）
PORTAL_PROXY_FORWARD_PORT = "7500"
# 门户代理转发类型（固定）
PORTAL_PROXY_FORWARD_TYPE = "SmartUnit"


class EdgeLinkState(str, Enum):
    """联通类操作三态归一化结果。"""

    OK = "OK"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    OFFLINE_TIMEOUT = "OFFLINE_TIMEOUT"


class EdgeStageState(str, Enum):
    """五类阶段状态（design §8）。

    用于所有业务调用的结果分类：
      - COMPLETE: HTTP 200 + rtnCode 0，操作成功。
      - ACCEPTED: HTTP 200 + rtnCode != 0，后端受理但业务失败。
      - HTTP_ERROR: 非 200 HTTP 状态码。
      - TIMEOUT: 请求超时（httpx.TimeoutException）。
      - NOT_CONFIGURED: 代理通信方式未配置（秒拒）。
    """

    COMPLETE = "COMPLETE"
    ACCEPTED = "ACCEPTED"
    HTTP_ERROR = "HTTP_ERROR"
    TIMEOUT = "TIMEOUT"
    NOT_CONFIGURED = "NOT_CONFIGURED"


class EdgeApiError(Exception):
    """边缘建档后端调用异常（登录失败、网络错误、非零业务码）。"""

    def __init__(
        self,
        message: str,
        *,
        rtn_code=None,
        rtn_msg: str = "",
        http_status: int | None = None,
        raw=None,
    ):
        """初始化异常。

        Args:
            message: 可读错误描述。
            rtn_code: 后端返回码（若有）。
            rtn_msg: 后端返回消息（若有）。
            http_status: HTTP 状态码（若有）。
            raw: 原始响应或异常上下文。
        """
        super().__init__(message)
        self.rtn_code = rtn_code
        self.rtn_msg = rtn_msg
        self.http_status = http_status
        self.raw = raw


def rsa_encrypt(public_key_pem: str, plain: str) -> str:
    """使用 RSA PKCS1v15 公钥加密并返回 Base64 文本。

    Args:
        public_key_pem: 公钥，可含或不含 PEM 头尾。
        plain: 待加密明文。

    Returns:
        Base64 编码的密文字符串。
    """
    if "BEGIN" not in public_key_pem:
        public_key_pem = (
            "-----BEGIN PUBLIC KEY-----\n"
            + public_key_pem
            + "\n-----END PUBLIC KEY-----"
        )
    key = serialization.load_pem_public_key(public_key_pem.encode())
    return base64.b64encode(
        key.encrypt(plain.encode(), padding.PKCS1v15())
    ).decode()


class EdgeDeviceClient:
    """边缘建档后端最小签名客户端。

    典型用法::

        client = EdgeDeviceClient("http://10.0.11.175:7500", "xldz", "***")
        client.login()
        result = client.call("/devArchManager/doc/set/modifyDevice/v1", {...})
        client.close()

    - ``login`` 完成 RSA 登录并保存 token / loginStr / userId 签名上下文。
    - ``call`` 携带五头签名，返回归一化结构
      ``{ok, rtnCode, rtnMsg, data}``。
    - ``call_link`` 用于联通类接口，附加三态归一化 ``state``。
    """

    def __init__(
        self,
        base_url: str,
        login_name: str,
        password: str,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
        link_timeout: float = DEFAULT_LINK_TIMEOUT,
        *,
        proxy_mode: bool = False,
        proxy_api_url: str = PORTAL_PROXY_API_URL,
        phone: str = "",
        captcha: str = "",
    ):
        """初始化客户端（不自动登录）。

        Args:
            base_url: 边缘后端基地址，如 ``http://10.0.11.175:7500``。
                代理模式下仍为目标后端逻辑地址（用于构造转发头）。
            login_name: 边缘登录账号。
            password: 边缘登录密码（敏感，不外泄）。
            request_timeout: 普通档案接口默认超时（秒）。
            link_timeout: 联通类接口默认超时（秒）。
            proxy_mode: 是否启用门户代理模式（20.* IP 段）。
            proxy_api_url: 门户 API 代理地址，默认读环境变量。
            phone: 手机号，代理模式下 getRSAKey 需要。
            captcha: 验证码，代理模式下 getRSAKey 需要。
        """
        self.base_url = base_url.rstrip("/")
        self.login_name = login_name
        self._password = password
        self.request_timeout = (
            float(request_timeout) if request_timeout else DEFAULT_REQUEST_TIMEOUT
        )
        self.link_timeout = (
            float(link_timeout) if link_timeout else DEFAULT_LINK_TIMEOUT
        )
        self._client = httpx.Client(timeout=self.request_timeout)
        # 登录后填充的签名上下文
        self.token: str = ""
        self.login_str: str = ""
        self.user_id: str = ""
        self.logged_in: bool = False
        # 门户代理模式
        self.proxy_mode = proxy_mode
        self.proxy_api_url = proxy_api_url.rstrip("/") if proxy_mode else ""
        # 代理模式凭据（getRSAKey 需要 PhoneNum/Code 头）
        self._phone = phone
        self._captcha = captcha
        # 时钟召测等特殊接口不发送 ForwardUrl 头，由门户根据会话状态自动转发
        self._skip_proxy_headers = False

    # ── 登录链路 ──

    def get_rsa_key(self) -> dict:
        """请求后端 RSA 公钥信息。

        代理模式下自动附加 ``PhoneNum``/``Code`` 请求头，
        门户代理层要求这两个头作为身份预验证。

        Returns:
            ``rtnData`` 字典，含 ``publicKeyValue`` 与 ``keyName``。

        Raises:
            EdgeApiError: 网络错误或后端返回码非零。
        """
        extra = {}
        if self.proxy_mode:
            extra = {"PhoneNum": self._phone, "Code": self._captcha}
        resp = self._post_raw(
            "/authorityManageServer/manage/action/getRSAKey/v1",
            {},
            timeout=self.request_timeout,
            extra_headers=extra,
        )
        return self._unwrap(resp, "getRSAKey")

    def login(self) -> dict:
        """执行 RSA 登录并保存签名上下文。

        Returns:
            归一化登录结果 ``{ok, rtnCode, rtnMsg, data}``，
            ``data`` 含 token 与 sysUser 信息（调用方需脱敏后再展示）。

        Raises:
            EdgeApiError: 登录失败或网络错误。
        """
        key_data = self.get_rsa_key()
        public_key = key_data["publicKeyValue"]
        key_name = key_data["keyName"]
        # loginStr 为本次会话对称密钥种子，参与后续 tokenEncrypt 签名
        self.login_str = secrets.token_hex(8)
        payload = {
            "loginName": rsa_encrypt(public_key, self.login_name),
            "password": rsa_encrypt(public_key, self._password),
            "keyName": key_name,
            "symmetricKey": rsa_encrypt(public_key, self.login_str),
        }
        resp = self._post_raw(
            "/authorityManageServer/manage/action/login/v1",
            payload,
            timeout=self.request_timeout,
        )
        data = self._unwrap(resp, "login")
        self.token = str(data.get("token", ""))
        self.user_id = str((data.get("sysUser") or {}).get("id", ""))
        if not self.token:
            raise EdgeApiError("登录响应缺少 token", raw=data)
        self.logged_in = True
        return {"ok": True, "rtnCode": 0, "rtnMsg": "", "data": data}

    # ── 业务调用 ──

    def _request_url(self, path: str) -> str:
        """根据连接模式构造实际请求 URL。

        代理模式下请求发往门户代理层，由 ``ForwardUrl`` 头指定目标后端；
        直连模式直接请求目标后端。

        Args:
            path: 接口路径。

        Returns:
            完整请求 URL。
        """
        base = self.proxy_api_url if self.proxy_mode else self.base_url
        return f"{base}{path}"

    def _proxy_headers(self) -> dict:
        """构造门户代理额外请求头（仅代理模式生效）。

        门户代理层根据 ``ForwardUrl`` 头将请求转发到目标后端。
        非代理模式或 _skip_proxy_headers 为 True 时返回空字典。

        Returns:
            代理请求头字典。
        """
        if not self.proxy_mode or getattr(self, "_skip_proxy_headers", False):
            return {}
        return {
            "webSite": self.base_url,
            "ForwardUrl": self.base_url,
            "ForwardPort": PORTAL_PROXY_FORWARD_PORT,
            "ForwardType": PORTAL_PROXY_FORWARD_TYPE,
        }

    def _sign_headers(self) -> dict:
        """构造五头签名请求头（含代理头）。

        Returns:
            含 appCode/token/tokenEncrypt/dateTime/userId 的头字典，
            代理模式下额外含 ForwardUrl/webSite/ForwardPort/ForwardType。
        """
        ts = int(time.time() * 1000)
        sign = hashlib.md5(
            f"{self.token}{self.login_str}{ts}".encode()
        ).hexdigest()
        headers = {
            "appCode": APP_CODE,
            "token": self.token,
            "tokenEncrypt": sign,
            "dateTime": str(ts),
            "userId": self.user_id,
        }
        headers.update(self._proxy_headers())
        return headers

    def _post_raw(
        self,
        path: str,
        payload: dict,
        timeout: float,
        extra_headers: dict | None = None,
    ) -> dict:
        """发起原始 POST 请求并返回 JSON。

        代理模式下请求发往门户代理层，并附加代理转发头。

        Args:
            path: 接口路径（以 ``/`` 开头）。
            payload: 请求体。
            timeout: 本次请求超时（秒）。
            extra_headers: 额外请求头，与代理头合并。

        Returns:
            后端 JSON 响应字典。

        Raises:
            EdgeApiError: 网络错误、超时或响应非合法 JSON。
        """
        headers = self._proxy_headers()
        if extra_headers:
            headers.update(extra_headers)
        try:
            resp = self._client.post(
                self._request_url(path),
                json=payload,
                timeout=timeout,
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            raise EdgeApiError(f"请求超时: {path}", raw=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise EdgeApiError(f"网络请求失败: {path}", raw=str(exc)) from exc
        try:
            return resp.json()
        except ValueError as exc:
            raise EdgeApiError(
                f"响应非合法 JSON: {path}", raw=resp.text[:200]
            ) from exc

    def call(
        self, path: str, payload: dict | None = None, timeout: float | None = None
    ) -> dict:
        """带五头签名调用后端接口，返回统一归一化结构。

        Args:
            path: 接口路径。
            payload: 请求体，默认空字典。
            timeout: per-call 超时（秒），默认取 ``request_timeout``。

        Returns:
            ``{ok, rtnCode, rtnMsg, data, http_status, stage}``。
            ``stage`` 为五类阶段状态之一。

        Raises:
            EdgeApiError: 未登录或网络层错误。
        """
        if not self.logged_in:
            raise EdgeApiError("EdgeDeviceClient 尚未登录")
        effective_timeout = self.request_timeout if timeout is None else float(timeout)
        try:
            resp_body, http_status = self._post_signed(
                path, payload or {}, effective_timeout,
            )
        except EdgeApiError as exc:
            # 传输层异常：分类为 TIMEOUT 或 HTTP_ERROR
            if "超时" in str(exc):
                return {
                    "ok": False, "rtnCode": None, "rtnMsg": str(exc),
                    "data": None, "http_status": None,
                    "stage": EdgeStageState.TIMEOUT.value,
                }
            return {
                "ok": False, "rtnCode": None, "rtnMsg": str(exc),
                "data": None, "http_status": exc.http_status,
                "stage": EdgeStageState.HTTP_ERROR.value,
            }
        return self._normalize(resp_body, http_status)

    def _post_signed(
        self, path: str, payload: dict, timeout: float,
    ) -> tuple[dict, int]:
        """带签名头发起 POST。

        代理模式下请求发往门户代理层，签名头与代理头合并发送。

        Args:
            path: 接口路径。
            payload: 请求体。
            timeout: 本次超时（秒）。

        Returns:
            ``(json_body, http_status)`` 元组。

        Raises:
            EdgeApiError: 网络错误或响应非合法 JSON。
        """
        try:
            resp = self._client.post(
                self._request_url(path),
                json=payload,
                timeout=timeout,
                headers=self._sign_headers(),
            )
        except httpx.TimeoutException as exc:
            raise EdgeApiError(
                f"请求超时: {path}", raw=str(exc),
            ) from exc
        except httpx.HTTPError as exc:
            raise EdgeApiError(
                f"网络请求失败: {path}", raw=str(exc),
            ) from exc
        http_status = resp.status_code
        if http_status != 200:
            raise EdgeApiError(
                f"HTTP {http_status}: {path}",
                http_status=http_status,
                raw=resp.text[:200],
            )
        try:
            return resp.json(), http_status
        except ValueError as exc:
            raise EdgeApiError(
                f"响应非合法 JSON: {path}",
                http_status=http_status,
                raw=resp.text[:200],
            ) from exc

    @staticmethod
    def _normalize(resp: dict, http_status: int = 200) -> dict:
        """将后端响应归一化为统一结构，含阶段状态分类。

        Args:
            resp: 后端原始 JSON 响应。
            http_status: HTTP 状态码。

        Returns:
            ``{ok, rtnCode, rtnMsg, data, http_status, stage}``。
        """
        if not isinstance(resp, dict):
            return {
                "ok": False, "rtnCode": None, "rtnMsg": "响应结构异常",
                "data": None, "http_status": http_status,
                "stage": EdgeStageState.HTTP_ERROR.value,
            }
        rtn_code = resp.get("rtnCode")
        rtn_msg = resp.get("rtnMsg", "")
        # 阶段状态分类
        if rtn_code == 0:
            stage = EdgeStageState.COMPLETE.value
        elif any(kw in rtn_msg for kw in _NOT_CONFIGURED_KEYWORDS):
            stage = EdgeStageState.NOT_CONFIGURED.value
        else:
            stage = EdgeStageState.ACCEPTED.value
        return {
            "ok": rtn_code == 0,
            "rtnCode": rtn_code,
            "rtnMsg": rtn_msg,
            "data": resp.get("rtnData"),
            "http_status": http_status,
            "stage": stage,
        }

    @staticmethod
    def _unwrap(resp: dict, action: str) -> dict:
        """解包登录类响应，非零码抛异常。

        Args:
            resp: 后端原始 JSON 响应。
            action: 动作名，用于错误描述。

        Returns:
            ``rtnData`` 字典。

        Raises:
            EdgeApiError: 后端返回码非零或缺少 rtnData。
        """
        if not isinstance(resp, dict):
            raise EdgeApiError(f"{action} 响应结构异常")
        rtn_code = resp.get("rtnCode")
        if rtn_code != 0:
            raise EdgeApiError(
                f"{action} 失败: {resp.get('rtnMsg', '')}",
                rtn_code=rtn_code,
                rtn_msg=str(resp.get("rtnMsg", "")),
                raw=resp,
            )
        data = resp.get("rtnData")
        if not isinstance(data, dict):
            raise EdgeApiError(f"{action} 响应缺少 rtnData", raw=resp)
        return data

    # ── 联通类三态归一化 ──

    def call_link(
        self, path: str, payload: dict | None = None, timeout: float | None = None
    ) -> dict:
        """调用联通类接口并归一化为三态结果。

        联通类接口（下发/召测/通讯状态）在无实表时会阻塞，使用较短
        的 ``link_timeout``。返回结构在 ``call`` 基础上附加：
          - ``state``：OK / NOT_CONFIGURED / OFFLINE_TIMEOUT。
          - ``kind``：细分类别（ok/not_configured/timeout/conn_error/rtn_error）。
          - ``elapsed``：本次调用耗时（秒）。

        Args:
            path: 接口路径。
            payload: 请求体。
            timeout: per-call 超时，默认取 ``link_timeout``。

        Returns:
            归一化结果字典，含 state / kind / elapsed 与 rtnCode / rtnMsg / data。
        """
        effective_timeout = self.link_timeout if timeout is None else float(timeout)
        started = time.time()
        try:
            resp, http_status = self._post_signed(path, payload or {}, effective_timeout)
        except EdgeApiError as exc:
            elapsed = round(time.time() - started, 1)
            raw = str(exc.raw or exc)
            # 超时与连接错误统一归一化为离线（无实表时后端挂起）
            kind = "timeout" if "超时" in str(exc) else "conn_error"
            return {
                "ok": False,
                "state": EdgeLinkState.OFFLINE_TIMEOUT.value,
                "kind": kind,
                "elapsed": elapsed,
                "rtnCode": None,
                "rtnMsg": "",
                "data": None,
                "detail": raw,
            }
        elapsed = round(time.time() - started, 1)
        normalized = self._normalize(resp, http_status)
        rtn_msg = str(normalized.get("rtnMsg") or "")
        if normalized["ok"]:
            state, kind = EdgeLinkState.OK.value, "ok"
        elif any(kw in rtn_msg for kw in _NOT_CONFIGURED_KEYWORDS):
            state, kind = EdgeLinkState.NOT_CONFIGURED.value, "not_configured"
        elif any(kw in rtn_msg for kw in _TIMEOUT_KEYWORDS):
            state, kind = EdgeLinkState.OFFLINE_TIMEOUT.value, "offline_msg"
        else:
            # 其它非零业务码：保留原始信息，归一化为离线（终端未成功应答）
            state, kind = EdgeLinkState.OFFLINE_TIMEOUT.value, "rtn_error"
        normalized.update({"state": state, "kind": kind, "elapsed": elapsed})
        return normalized

    def close(self) -> None:
        """关闭底层 HTTP 客户端。"""
        if self._client is not None and not self._client.is_closed:
            self._client.close()

    def __enter__(self) -> "EdgeDeviceClient":
        """支持 with 语法，进入时返回自身。"""
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """退出 with 时关闭客户端。"""
        self.close()
