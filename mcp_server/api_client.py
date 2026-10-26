"""规约管理后端 API 客户端。

封装规约管理后端（https://18091.chinadny.com）的 HTTP 调用，
为 MCP 工具层提供统一请求入口和统一返回结构。

- 鉴权：自定义 Token 请求头（非 Authorization: Bearer）。
- 统一响应：code === 20000 成功，40100 登录失效，40000 业务异常。
- 错误归一化：网络异常、HTTP 异常、业务异常、认证异常均转换为
  带 error/code/message 的字典，供 Skill 区分"查询为空"与"查询失败"。
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import httpx

__all__ = ["API_BASE_URL", "SUCCESS_CODE", "AUTH_EXPIRED_CODE", "BIZ_ERROR_CODE", "ProtocolApiClient"]

# 后端 API 基地址（可用环境变量覆盖）
API_BASE_URL: str = os.getenv("PCA_API_BASE_URL", "https://18091.chinadny.com")

# 后端统一响应码约定（来源：规约管理MCP服务化Spec.md 3.1）
SUCCESS_CODE: int = 20000
AUTH_EXPIRED_CODE: int = 40100
BIZ_ERROR_CODE: int = 40000

# 请求超时（秒）
DEFAULT_TIMEOUT: float = 30.0


class ProtocolApiClient:
    """封装所有后端 API 调用，使用 httpx.AsyncClient。

    - 统一注入 Token 请求头与 Content-Type。
    - 统一处理网络异常、HTTP 状态异常、业务错误码。
    - 统一返回结构，error 为 False 时区分 empty（查询为空）。
    """

    def __init__(self, base_url: str = API_BASE_URL):
        """初始化 API 客户端。

        Args:
            base_url: 后端 API 基地址，默认取环境变量 PCA_API_BASE_URL。
        """
        self.base_url = base_url
        self._client: httpx.AsyncClient | None = None
        self._client_loop: asyncio.AbstractEventLoop | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        """获取或创建底层 httpx.AsyncClient。

        检测当前事件循环是否与创建客户端时相同，
        不同则关闭旧客户端并重建（避免 ``Event loop is closed``）。
        """
        current_loop = asyncio.get_running_loop()
        need_recreate = (
            self._client is None
            or self._client.is_closed
            or self._client_loop is not current_loop
        )
        if need_recreate:
            # 关闭旧客户端（如果仍在有效事件循环中）
            if (
                self._client is not None
                and not self._client.is_closed
                and self._client_loop is not None
                and not self._client_loop.is_closed()
            ):
                await self._client.aclose()
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=DEFAULT_TIMEOUT,
                verify=True,
            )
            self._client_loop = current_loop
        return self._client

    async def close(self) -> None:
        """关闭底层 HTTP 客户端。"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    @staticmethod
    def _success(data: Any, *, empty: bool = False) -> dict:
        """构造成功返回结构。

        Args:
            data: 后端返回的 data 字段内容。
            empty: 查询结果是否为空（仅查询类接口使用）。

        Returns:
            统一成功结构字典。
        """
        return {
            "error": False,
            "empty": empty,
            "code": SUCCESS_CODE,
            "message": "成功",
            "data": data,
        }

    @staticmethod
    def _error(code: str, message: str, raw: Any = None) -> dict:
        """构造错误返回结构。

        Args:
            code: 错误码（NETWORK_ERROR/HTTP_ERROR/AUTH_ERROR/API_ERROR）。
            message: 错误描述。
            raw: 后端原始响应或异常上下文。

        Returns:
            统一错误结构字典。
        """
        return {
            "error": True,
            "empty": False,
            "code": code,
            "message": message,
            "raw": raw,
        }

    async def _request(
        self,
        path: str,
        token: str,
        data: dict | None = None,
    ) -> dict:
        """统一 POST JSON 请求方法。

        Args:
            path: 后端 API 路径，如 /api/Protocol/GetSysBrandList。
            token: 登录获取的后端业务 Token。
            data: 请求体参数，可为 None（视为空对象）。

        Returns:
            统一返回结构：
            - 成功：{"error": False, "empty": bool, "code": 20000, "data": ...}
            - 失败：{"error": True, "code": "...", "message": "...", "raw": ...}
        """
        if not token:
            return self._error(
                "AUTH_ERROR",
                "缺少后端业务 Token，请先调用 login(phoneNum, code) 登录",
            )

        headers = {
            "Token": token,
            "Content-Type": "application/json",
        }

        client = await self._ensure_client()
        try:
            resp = await client.post(path, json=data if data is not None else {}, headers=headers)
        except httpx.TimeoutException as exc:
            return self._error("NETWORK_ERROR", f"网络请求超时: {exc}")
        except httpx.HTTPError as exc:
            return self._error("NETWORK_ERROR", f"网络请求失败: {exc}")

        if resp.status_code != 200:
            return self._error(
                "HTTP_ERROR",
                f"HTTP 状态码异常: {resp.status_code}",
                raw={"status_code": resp.status_code, "text": resp.text[:500]},
            )

        try:
            body = resp.json()
        except ValueError:
            return self._error(
                "HTTP_ERROR",
                "响应体不是合法 JSON",
                raw={"text": resp.text[:500]},
            )

        code = body.get("code")
        message = body.get("message", "")

        if code == AUTH_EXPIRED_CODE:
            return self._error("AUTH_ERROR", "Token无效或登录已失效，请重新登录", raw=body)
        if code != SUCCESS_CODE:
            return self._error(
                "API_ERROR",
                message or f"后端业务错误，code={code}",
                raw=body,
            )

        payload = body.get("data")
        # 分页列表接口：rows 为空时标记 empty，供 Skill 区分"无数据"与"失败"
        empty = isinstance(payload, dict) and "rows" in payload and not payload.get("rows")
        return self._success(payload, empty=empty)

    async def _request_json_file(
        self,
        path: str,
        token: str,
        file_name: str,
        file_content: bytes,
        form_fields: dict | None = None,
    ) -> dict:
        """统一 multipart/form-data 文件上传请求。

        Args:
            path: 后端 API 路径，如 /api/file/UploadProtocolFile。
            token: 登录获取的后端业务 Token。
            file_name: 上传文件名。
            file_content: 文件二进制内容。
            form_fields: 附加 form field，如 {"fileType": "proto"}。

        Returns:
            统一返回结构，成功时 data 含 url/fileId 等字段。
        """
        if not token:
            return self._error(
                "AUTH_ERROR",
                "缺少后端业务 Token，请先调用 login(phoneNum, code) 登录",
            )

        client = await self._ensure_client()
        try:
            fields: dict[str, Any] = dict(form_fields or {})
            fields["file"] = (file_name, file_content)
            resp = await client.post(
                path,
                files=fields,
                headers={"Token": token},
            )
        except httpx.TimeoutException as exc:
            return self._error("NETWORK_ERROR", f"网络请求超时: {exc}")
        except httpx.HTTPError as exc:
            return self._error("NETWORK_ERROR", f"网络请求失败: {exc}")

        if resp.status_code != 200:
            return self._error(
                "HTTP_ERROR",
                f"HTTP 状态码异常: {resp.status_code}",
                raw={"status_code": resp.status_code, "text": resp.text[:500]},
            )

        try:
            body = resp.json()
        except ValueError:
            return self._error(
                "HTTP_ERROR",
                "响应体不是合法 JSON",
                raw={"text": resp.text[:500]},
            )

        code = body.get("code")
        message = body.get("message", "")

        if code == AUTH_EXPIRED_CODE:
            return self._error("AUTH_ERROR", "Token无效或登录已失效，请重新登录", raw=body)
        if code != SUCCESS_CODE:
            return self._error(
                "API_ERROR",
                message or f"后端业务错误，code={code}",
                raw=body,
            )

        return self._success(body.get("data"))

    async def _request_blob(self, path: str, token: str, data: dict | None = None) -> dict:
        """统一二进制文件流请求（导出类接口）。

        Args:
            path: 后端 API 路径，如 /api/Protocol/ExportData。
            token: 登录获取的后端业务 Token。
            data: 请求体参数。

        Returns:
            统一返回结构，成功时 data 含 base64 编码的文件内容与 content_type。
        """
        if not token:
            return self._error(
                "AUTH_ERROR",
                "缺少后端业务 Token，请先调用 login(phoneNum, code) 登录",
            )

        headers = {
            "Token": token,
            "Content-Type": "application/json",
        }

        client = await self._ensure_client()
        try:
            resp = await client.post(path, json=data or {}, headers=headers)
        except httpx.TimeoutException as exc:
            return self._error("NETWORK_ERROR", f"网络请求超时: {exc}")
        except httpx.HTTPError as exc:
            return self._error("NETWORK_ERROR", f"网络请求失败: {exc}")

        if resp.status_code != 200:
            return self._error(
                "HTTP_ERROR",
                f"HTTP 状态码异常: {resp.status_code}",
                raw={"status_code": resp.status_code, "text": resp.text[:500]},
            )

        content_type = resp.headers.get("content-type", "")
        if "json" in content_type.lower():
            # 后端可能以 JSON 返回业务错误
            try:
                body = resp.json()
            except ValueError:
                body = {}
            code = body.get("code")
            if code == AUTH_EXPIRED_CODE:
                return self._error("AUTH_ERROR", "Token无效或登录已失效，请重新登录", raw=body)
            if code != SUCCESS_CODE:
                return self._error(
                    "API_ERROR",
                    body.get("message", "") or f"后端业务错误，code={code}",
                    raw=body,
                )

        import base64

        encoded = base64.b64encode(resp.content).decode("ascii")
        return self._success(
            {
                "content_base64": encoded,
                "content_type": content_type or "application/octet-stream",
                "size": len(resp.content),
            }
        )

    # ── 登录 ──

    async def login(self, phoneNum: str, code: str) -> dict:
        """手机号+验证码登录，返回业务 Token。

        Args:
            phoneNum: 手机号。
            code: 短信验证码（不会过期）。

        Returns:
            统一返回结构，成功时 data 含 token 与用户信息。
        """
        headers = {"Content-Type": "application/json"}
        client = await self._ensure_client()
        try:
            resp = await client.post(
                "/api/Auth/LoginByCode",
                json={"phoneNum": phoneNum, "code": code},
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            return self._error("NETWORK_ERROR", f"网络请求超时: {exc}")
        except httpx.HTTPError as exc:
            return self._error("NETWORK_ERROR", f"网络请求失败: {exc}")

        if resp.status_code != 200:
            return self._error(
                "HTTP_ERROR",
                f"HTTP 状态码异常: {resp.status_code}",
                raw={"status_code": resp.status_code, "text": resp.text[:500]},
            )

        try:
            body = resp.json()
        except ValueError:
            return self._error(
                "HTTP_ERROR",
                "响应体不是合法 JSON",
                raw={"text": resp.text[:500]},
            )

        resp_code = body.get("code")
        if resp_code != SUCCESS_CODE:
            return self._error(
                "API_ERROR",
                body.get("message", "") or f"登录失败，code={resp_code}",
                raw=body,
            )

        return self._success(body.get("data"))

    # ── 大类管理 ──

    async def get_classify_list(
        self, token: str, sysName: str = "", pageIndex: int = 1, pageSize: int = 9999
    ) -> dict:
        """查询大类列表。

        Args:
            token: 后端业务 Token。
            sysName: 大类名称（模糊搜索）。
            pageIndex: 当前页码。
            pageSize: 每页条数。

        Returns:
            统一返回结构，data.rows 每项含 id（大类编号）、sysName。
        """
        return await self._request(
            "/api/Protocol/GetSysClassifyList",
            token,
            {"sysName": sysName, "pageIndex": pageIndex, "pageSize": pageSize},
        )

    async def add_classify(self, token: str, sysName: str) -> dict:
        """新增大类。

        Args:
            token: 后端业务 Token。
            sysName: 大类名称。

        Returns:
            统一返回结构。
        """
        return await self._request(
            "/api/Protocol/AddSysClassify",
            token,
            {"id": -1, "sysName": sysName},
        )

    async def update_classify(self, token: str, classify_id: int, sysName: str) -> dict:
        """更新大类。

        Args:
            token: 后端业务 Token。
            classify_id: 大类ID。
            sysName: 大类名称。

        Returns:
            统一返回结构。
        """
        return await self._request(
            "/api/Protocol/UpdateSysClassify",
            token,
            {"id": classify_id, "sysName": sysName},
        )

    async def del_classify(self, token: str, classify_id: int, sysName: str) -> dict:
        """删除大类。

        Args:
            token: 后端业务 Token。
            classify_id: 大类ID。
            sysName: 大类名称。

        Returns:
            统一返回结构。
        """
        return await self._request(
            "/api/Protocol/DelSysClassify",
            token,
            {"id": classify_id, "sysName": sysName},
        )

    # ── 设备类型管理 ──

    async def get_device_type_list(
        self,
        token: str,
        deviceTypeName: str = "",
        deviceTypeCode: str = "",
        sysId: int = -1,
        pageIndex: int = 1,
        pageSize: int = 9999,
    ) -> dict:
        """查询设备类型列表。

        Args:
            token: 后端业务 Token。
            deviceTypeName: 类型名称（模糊搜索）。
            deviceTypeCode: 类型编码。
            sysId: 所属大类ID，-1 表示全部。
            pageIndex: 当前页码。
            pageSize: 每页条数。

        Returns:
            统一返回结构，data.rows 每项含 id、deviceTypeName、
            deviceTypeCode、sysId、sysName。
        """
        return await self._request(
            "/api/Protocol/GetProtocolDeviceTypeList",
            token,
            {
                "deviceTypeName": deviceTypeName,
                "deviceTypeCode": deviceTypeCode,
                "sysId": sysId,
                "pageIndex": pageIndex,
                "pageSize": pageSize,
            },
        )

    async def add_device_type(
        self, token: str, deviceTypeName: str, deviceTypeCode: str, sysId: int
    ) -> dict:
        """新增设备类型。

        Args:
            token: 后端业务 Token。
            deviceTypeName: 类型名称。
            deviceTypeCode: 类型编码（纯数字）。
            sysId: 所属大类ID。

        Returns:
            统一返回结构。
        """
        return await self._request(
            "/api/Protocol/AddProtocolDeviceType",
            token,
            {
                "deviceTypeName": deviceTypeName,
                "deviceTypeCode": deviceTypeCode,
                "sysId": sysId,
            },
        )

    async def update_device_type(
        self, token: str, device_type_id: int, deviceTypeName: str, deviceTypeCode: str, sysId: int
    ) -> dict:
        """更新设备类型。

        Args:
            token: 后端业务 Token。
            device_type_id: 记录ID。
            deviceTypeName: 类型名称。
            deviceTypeCode: 类型编码。
            sysId: 所属大类ID。

        Returns:
            统一返回结构。
        """
        return await self._request(
            "/api/Protocol/UpdateProtocolDeviceType",
            token,
            {
                "id": device_type_id,
                "deviceTypeName": deviceTypeName,
                "deviceTypeCode": deviceTypeCode,
                "sysId": sysId,
            },
        )

    async def del_device_type(self, token: str, device_type_id: int) -> dict:
        """删除设备类型。

        Args:
            token: 后端业务 Token。
            device_type_id: 记录ID。

        Returns:
            统一返回结构。
        """
        return await self._request(
            "/api/Protocol/DelProtocolDeviceType",
            token,
            {"id": device_type_id},
        )

    # ── 品牌管理 ──

    async def get_brand_list(
        self,
        token: str,
        nameCN: str = "",
        code: str = "",
        deviceTypeId: int = -1,
        pageIndex: int = 1,
        pageSize: int = 9999,
    ) -> dict:
        """查询品牌列表。

        Args:
            token: 后端业务 Token。
            nameCN: 品牌名称-中文（模糊搜索）。
            code: 品牌编码。
            deviceTypeId: 所属设备类型ID，-1 表示全部。
            pageIndex: 当前页码。
            pageSize: 每页条数。

        Returns:
            统一返回结构，data.rows 每项含 id、nameCN、name、code、
            deviceTypeId、deviceTypeName。
        """
        return await self._request(
            "/api/Protocol/GetSysBrandList",
            token,
            {
                "name": nameCN,
                "nameCN": nameCN,
                "code": code,
                "deviceTypeId": deviceTypeId,
                "pageIndex": pageIndex,
                "pageSize": pageSize,
            },
        )

    async def add_brand(
        self, token: str, nameCN: str, name: str, code: str, deviceTypeId: int
    ) -> dict:
        """新增品牌。

        Args:
            token: 后端业务 Token。
            nameCN: 品牌名称-中文。
            name: 品牌名称-英文（禁止中文）。
            code: 品牌编码。
            deviceTypeId: 所属设备类型ID。

        Returns:
            统一返回结构。
        """
        return await self._request(
            "/api/Protocol/AddSysBrand",
            token,
            {
                "nameCN": nameCN,
                "name": name,
                "code": code,
                "deviceTypeId": deviceTypeId,
            },
        )

    async def update_brand(
        self, token: str, brand_id: int, nameCN: str, name: str, code: str, deviceTypeId: int
    ) -> dict:
        """更新品牌。

        Args:
            token: 后端业务 Token。
            brand_id: 记录ID。
            nameCN: 品牌名称-中文。
            name: 品牌名称-英文。
            code: 品牌编码。
            deviceTypeId: 所属设备类型ID。

        Returns:
            统一返回结构。
        """
        return await self._request(
            "/api/Protocol/UpdateSysBrand",
            token,
            {
                "id": brand_id,
                "nameCN": nameCN,
                "name": name,
                "code": code,
                "deviceTypeId": deviceTypeId,
            },
        )

    async def del_brand(self, token: str, brand_id: int, name: str, code: str) -> dict:
        """删除品牌。

        Args:
            token: 后端业务 Token。
            brand_id: 记录ID。
            name: 品牌名称-英文。
            code: 品牌编码。

        Returns:
            统一返回结构。
        """
        return await self._request(
            "/api/Protocol/DelSysBrand",
            token,
            {"id": brand_id, "name": name, "code": code},
        )

    # ── 型号管理 ──

    async def get_model_list(
        self,
        token: str,
        name: str = "",
        brandId: int = -1,
        pageIndex: int = 1,
        pageSize: int = 9999,
    ) -> dict:
        """查询型号列表。

        Args:
            token: 后端业务 Token。
            name: 型号名称（模糊搜索）。
            brandId: 所属品牌ID，-1 表示全部。
            pageIndex: 当前页码。
            pageSize: 每页条数。

        Returns:
            统一返回结构，data.rows 每项含 id、name、brandId、brandName。
        """
        return await self._request(
            "/api/Protocol/GetProtocolModelList",
            token,
            {
                "name": name,
                "brandId": brandId,
                "pageIndex": pageIndex,
                "pageSize": pageSize,
            },
        )

    async def add_model(self, token: str, name: str, brandId: int) -> dict:
        """新增型号。

        Args:
            token: 后端业务 Token。
            name: 型号名称。
            brandId: 所属品牌ID。

        Returns:
            统一返回结构。
        """
        return await self._request(
            "/api/Protocol/AddProtocolModel",
            token,
            {"name": name, "brandId": brandId},
        )

    async def update_model(self, token: str, model_id: int, name: str, brandId: int) -> dict:
        """更新型号。

        Args:
            token: 后端业务 Token。
            model_id: 记录ID。
            name: 型号名称。
            brandId: 所属品牌ID。

        Returns:
            统一返回结构。
        """
        return await self._request(
            "/api/Protocol/UpdateProtocolModel",
            token,
            {"id": model_id, "name": name, "brandId": brandId},
        )

    async def del_model(self, token: str, model_id: int) -> dict:
        """删除型号。

        Args:
            token: 后端业务 Token。
            model_id: 记录ID。

        Returns:
            统一返回结构。
        """
        return await self._request(
            "/api/Protocol/DelProtocolModel",
            token,
            {"id": model_id},
        )

    async def export_model_data(self, token: str) -> dict:
        """导出型号统计数据。

        Args:
            token: 后端业务 Token。

        Returns:
            统一返回结构，成功时 data.content_base64 为文件内容。
        """
        return await self._request_blob(
            "/api/Protocol/ExportModelData",
            token,
            {},
        )

    # ── 规约信息 ──

    async def get_protocol_info_list(
        self,
        token: str,
        name: str = "",
        classifyId: int | None = None,
        deviceTypeId: int | None = None,
        brandId: int | None = None,
        modelId: int | None = None,
        pageIndex: int = 1,
        pageSize: int = 9999,
    ) -> dict:
        """查询规约列表。

        Args:
            token: 后端业务 Token。
            name: 规约名称（模糊搜索，后端必填字段，空串查全部）。
            classifyId: 大类ID。
            deviceTypeId: 设备类型ID。
            brandId: 品牌ID。
            modelId: 型号ID。
            pageIndex: 当前页码。
            pageSize: 每页条数。

        Returns:
            统一返回结构，data.rows 每项含 id/name/protoType/protoTypeName
            与四级分类字段（protoType 为字符串）。

        Notes:
            真实后端要求必填字段 name（Spec 中的 protocolName 字段名有误），
            且不支持 protoType 过滤（2026-09 实测传任意值结果不变）。
        """
        payload: dict[str, Any] = {
            "name": name,
            "pageIndex": pageIndex,
            "pageSize": pageSize,
        }
        # 可选过滤条件仅在有值时传递
        if classifyId is not None:
            payload["classifyId"] = classifyId
        if deviceTypeId is not None:
            payload["deviceTypeId"] = deviceTypeId
        if brandId is not None:
            payload["brandId"] = brandId
        if modelId is not None:
            payload["modelId"] = modelId
        return await self._request("/api/Protocol/GetProtocolInfos", token, payload)

    async def add_protocol_info(
        self,
        token: str,
        protocolName: str,
        protoType: int,
        classifyId: int,
        deviceTypeId: int,
        brandId: int,
        modelId: int,
        protocolFiles: list | None = None,
    ) -> dict:
        """新增规约。

        Args:
            token: 后端业务 Token。
            protocolName: 规约名称。
            protoType: 规约类型。
            classifyId: 大类ID。
            deviceTypeId: 设备类型ID。
            brandId: 品牌ID。
            modelId: 型号ID。
            protocolFiles: 规约文档文件列表。

        Returns:
            统一返回结构。
        """
        payload: dict[str, Any] = {
            "protocolName": protocolName,
            "protoType": protoType,
            "classifyId": classifyId,
            "deviceTypeId": deviceTypeId,
            "brandId": brandId,
            "modelId": modelId,
        }
        if protocolFiles is not None:
            payload["protocolFiles"] = protocolFiles
        return await self._request("/api/Protocol/AddProtocolInfo", token, payload)

    async def update_protocol(
        self,
        token: str,
        protocol_id: int,
        protocolName: str,
        protoType: int,
        classifyId: int,
        deviceTypeId: int,
        brandId: int,
        modelId: int,
        protocolFiles: list | None = None,
    ) -> dict:
        """更新规约。

        Args:
            token: 后端业务 Token。
            protocol_id: 规约ID。
            protocolName: 规约名称。
            protoType: 规约类型。
            classifyId: 大类ID。
            deviceTypeId: 设备类型ID。
            brandId: 品牌ID。
            modelId: 型号ID。
            protocolFiles: 规约文档文件列表。

        Returns:
            统一返回结构。
        """
        payload: dict[str, Any] = {
            "id": protocol_id,
            "protocolName": protocolName,
            "protoType": protoType,
            "classifyId": classifyId,
            "deviceTypeId": deviceTypeId,
            "brandId": brandId,
            "modelId": modelId,
        }
        if protocolFiles is not None:
            payload["protocolFiles"] = protocolFiles
        return await self._request("/api/Protocol/UpdateProtocol", token, payload)

    async def del_protocol_info(self, token: str, protocol_id: int, protocolName: str) -> dict:
        """删除规约。

        Args:
            token: 后端业务 Token。
            protocol_id: 规约ID。
            protocolName: 规约名称。

        Returns:
            统一返回结构。
        """
        return await self._request(
            "/api/Protocol/DelProtocolInfo",
            token,
            {"id": protocol_id, "protocolName": protocolName},
        )

    async def del_protocol_file(self, token: str, file_id: int) -> dict:
        """删除规约文档文件。

        Args:
            token: 后端业务 Token。
            file_id: 文件ID。

        Returns:
            统一返回结构。
        """
        return await self._request(
            "/api/Protocol/DeleteProtocolFile",
            token,
            {"fileId": file_id},
        )

    async def get_data_item_list(
        self, token: str, protocolId: int, protoType: int, pageIndex: int = 1, pageSize: int = 9999
    ) -> dict:
        """查询协议数据项列表。

        Args:
            token: 后端业务 Token。
            protocolId: 规约ID。
            protoType: 规约类型。
            pageIndex: 当前页码。
            pageSize: 每页条数。

        Returns:
            统一返回结构，data.rows 为数据项列表。
        """
        return await self._request(
            "/api/ProtocolDataItem/GetProtocolDataItemList",
            token,
            {
                "protocolId": protocolId,
                "protoType": protoType,
                "pageIndex": pageIndex,
                "pageSize": pageSize,
            },
        )

    async def add_data_item(self, token: str, data: dict) -> dict:
        """新增协议数据项。

        Args:
            token: 后端业务 Token。
            data: 数据项参数字典（由 MCP 工具层透传）。

        Returns:
            统一返回结构。
        """
        return await self._request(
            "/api/ProtocolDataItem/AddProtocolDataItem",
            token,
            data,
        )

    async def update_data_item(self, token: str, data: dict) -> dict:
        """更新协议数据项。

        Args:
            token: 后端业务 Token。
            data: 数据项参数字典（由 MCP 工具层透传）。

        Returns:
            统一返回结构。
        """
        return await self._request(
            "/api/ProtocolDataItem/UpdateProtocolDataItem",
            token,
            data,
        )

    async def del_data_item(self, token: str, data: dict) -> dict:
        """删除协议数据项。

        Args:
            token: 后端业务 Token。
            data: 数据项参数字典（由 MCP 工具层透传）。

        Returns:
            统一返回结构。
        """
        return await self._request(
            "/api/ProtocolDataItem/DelProtocolDataItem",
            token,
            data,
        )

    async def get_script_list(self, token: str, protocolId: int, protoType: int) -> dict:
        """查询脚本列表。

        Args:
            token: 后端业务 Token。
            protocolId: 规约ID。
            protoType: 规约类型。

        Returns:
            统一返回结构，data 为脚本文件列表。
        """
        return await self._request(
            "/api/Protocol/GetDataScriptList",
            token,
            {"protocolId": protocolId, "protoType": protoType},
        )

    async def get_json_detail(self, token: str, data: dict) -> dict:
        """获取脚本 JSON 内容。

        Args:
            token: 后端业务 Token。
            data: 请求参数字典（由 MCP 工具层透传）。

        Returns:
            统一返回结构。
        """
        return await self._request("/api/Protocol/GetJsonDetail", token, data)

    async def export_data(self, token: str, protocolId: int) -> dict:
        """导出协议数据项。

        Args:
            token: 后端业务 Token。
            protocolId: 规约ID。

        Returns:
            统一返回结构，成功时 data.content_base64 为 Excel 文件内容。
        """
        return await self._request_blob(
            "/api/Protocol/ExportData",
            token,
            {"protocolId": protocolId},
        )

    async def get_coeff_list(self, token: str, protocolId: int, dataItemId: int) -> dict:
        """查询数据项系数列表。

        Args:
            token: 后端业务 Token。
            protocolId: 规约ID。
            dataItemId: 数据项ID。

        Returns:
            统一返回结构，data 为系数列表。
        """
        return await self._request(
            "/api/Protocol/GetDataItemCoeffList",
            token,
            {"protocolId": protocolId, "dataItemId": dataItemId},
        )

    async def add_coeff(self, token: str, data: dict) -> dict:
        """新增数据项系数。

        Args:
            token: 后端业务 Token。
            data: 系数参数字典（由 MCP 工具层透传）。

        Returns:
            统一返回结构。
        """
        return await self._request("/api/Protocol/AddDataItemCoeff", token, data)

    async def update_coeff(self, token: str, data: dict) -> dict:
        """更新数据项系数。

        Args:
            token: 后端业务 Token。
            data: 系数参数字典（由 MCP 工具层透传）。

        Returns:
            统一返回结构。
        """
        return await self._request("/api/Protocol/UpdateDataItemCoeff", token, data)

    async def del_coeff(self, token: str, data: dict) -> dict:
        """删除数据项系数。

        Args:
            token: 后端业务 Token。
            data: 系数参数字典（由 MCP 工具层透传）。

        Returns:
            统一返回结构。
        """
        return await self._request("/api/Protocol/DelDataItemCoeff", token, data)

    async def get_sense_list(self, token: str, data: dict) -> dict:
        """查询感知结构列表。

        Args:
            token: 后端业务 Token。
            data: 请求参数字典（由 MCP 工具层透传）。

        Returns:
            统一返回结构。
        """
        return await self._request("/api/Protocol/GetDataItemSenseList", token, data)

    async def add_sense(self, token: str, data: dict) -> dict:
        """新增感知结构。

        Args:
            token: 后端业务 Token。
            data: 感知参数字典（由 MCP 工具层透传）。

        Returns:
            统一返回结构。
        """
        return await self._request("/api/Protocol/AddDataItemSense", token, data)

    async def update_sense(self, token: str, data: dict) -> dict:
        """更新感知结构。

        Args:
            token: 后端业务 Token。
            data: 感知参数字典（由 MCP 工具层透传）。

        Returns:
            统一返回结构。
        """
        return await self._request("/api/Protocol/UpdateDataItemSense", token, data)

    async def del_sense(self, token: str, data: dict) -> dict:
        """删除感知结构。

        Args:
            token: 后端业务 Token。
            data: 感知参数字典（由 MCP 工具层透传）。

        Returns:
            统一返回结构。
        """
        return await self._request("/api/Protocol/DelDataItemSense", token, data)

    # ── 规约类型（字典） ──

    async def get_protocol_type_list(
        self,
        token: str,
        name: str = "",
        dictItemCode: str = "",
        dictTypeCode: str = "protocolType",
        pageIndex: int = 1,
        pageSize: int = 9999,
    ) -> dict:
        """查询规约类型字典分页列表。

        Args:
            token: 后端业务 Token。
            name: 字典项名称（模糊搜索）。
            dictItemCode: 字典项编码。
            dictTypeCode: 字典类型编码，规约类型固定 protocolType。
            pageIndex: 当前页码。
            pageSize: 每页条数。

        Returns:
            统一返回结构，data.rows 每项含 id、name、code。
        """
        return await self._request(
            "/api/Dictionary/GetDictionaryListPage",
            token,
            {
                "name": name,
                "dictItemCode": dictItemCode,
                "dictTypeCode": dictTypeCode,
                "pageIndex": pageIndex,
                "pageSize": pageSize,
            },
        )

    async def save_protocol_type(
        self, token: str, name: str, dictItemCode: str, dictTypeCode: str = "protocolType",
        type_id: int = 0,
    ) -> dict:
        """保存规约类型字典项（新增/编辑共用）。

        Args:
            token: 后端业务 Token。
            name: 字典项名称。
            dictItemCode: 字典项编码。
            dictTypeCode: 字典类型编码，固定 protocolType。
            type_id: 字典项ID，新增时为 0。

        Returns:
            统一返回结构。
        """
        return await self._request(
            "/api/Dictionary/SaveDictionary",
            token,
            {
                "id": type_id,
                "name": name,
                "dictItemCode": dictItemCode,
                "dictTypeCode": dictTypeCode,
            },
        )

    async def del_protocol_type(self, token: str, type_id: int) -> dict:
        """删除规约类型字典项。

        Args:
            token: 后端业务 Token。
            type_id: 字典项ID。

        Returns:
            统一返回结构。
        """
        return await self._request(
            "/api/Dictionary/DeleteDictionary",
            token,
            {"id": type_id},
        )

    # ── 功能项管理 ──

    async def get_function_type_list(
        self,
        token: str,
        functionTypeName: str = "",
        functionCode: str = "",
        pageIndex: int = 1,
        pageSize: int = 9999,
    ) -> dict:
        """查询功能项列表。

        Args:
            token: 后端业务 Token。
            functionTypeName: 功能项名称（模糊搜索）。
            functionCode: 功能码。
            pageIndex: 当前页码。
            pageSize: 每页条数。

        Returns:
            统一返回结构，data.rows 每项含 functionId、functionName、
            functionCode、dataType、enumUnique、enumDescription 等字段。
        """
        return await self._request(
            "/api/Protocol/GetProtocoFunctionTypeList",
            token,
            {
                "functionTypeName": functionTypeName,
                "functionCode": functionCode,
                "pageIndex": pageIndex,
                "pageSize": pageSize,
            },
        )

    async def save_function_item(self, token: str, data: dict) -> dict:
        """保存功能项（新增/编辑共用）。

        Args:
            token: 后端业务 Token。
            data: 功能项参数字典（由 MCP 工具层透传）。

        Returns:
            统一返回结构。
        """
        return await self._request("/api/Protocol/SaveFunctionItem", token, data)

    async def del_function_item(self, token: str, functionId: int) -> dict:
        """删除功能项。

        Args:
            token: 后端业务 Token。
            functionId: 功能项ID。

        Returns:
            统一返回结构。
        """
        return await self._request(
            "/api/Protocol/DelFunctionItem",
            token,
            {"functionId": functionId},
        )

    # ── 文件上传 ──

    async def upload_protocol_file(
        self, token: str, file_name: str, file_content: bytes
    ) -> dict:
        """上传规约文档文件。

        Args:
            token: 后端业务 Token。
            file_name: 上传文件名。
            file_content: 文件二进制内容。

        Returns:
            统一返回结构，成功时 data 含 url、fileId、uploadType。
        """
        return await self._request_json_file(
            "/api/file/UploadProtocolFile",
            token,
            file_name,
            file_content,
            form_fields={"fileType": "proto"},
        )

    # ── 脚本生成 ──

    async def gen_script(self, token: str, data: dict) -> dict:
        """生成脚本。

        Args:
            token: 后端业务 Token。
            data: 脚本生成参数字典（由 MCP 工具层透传）。

        Returns:
            统一返回结构。
        """
        return await self._request("/api/ProtocolDataItem/GenDataScript", token, data)
