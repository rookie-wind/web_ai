# 规约管理 MCP 服务化 + Vue 接入配置页面 Spec

> 日期：2026-09-08
> 状态：待实施

---

## 一、项目背景

### 1.1 现状

运维平台 Web 系统中，品牌/型号/规约管理需要手动在网页上操作：

```
网页登录 → 获取 Token → 新增品牌 → 新增型号 → 新增规约信息 → 配置数据项 → 生成脚本
```

当前 `server.py` 有 6 个桩工具，仅返回 `not_implemented`，未调用任何后端 API。

同时，MCP 接入配置页面（`access.html`）是一个独立的静态 HTML 页面，风格与运维平台不统一，且功能独立无法联动。

### 1.2 目标

**需求一**：将运维平台后端 API 封装为 MCP 细粒度工具函数，通过 Skill 调用实现自动化流程编排。

**需求二**：将 MCP 接入配置功能迁移到 Vue 运维平台中，作为规约管理下的子页面，使用独立酷炫风格。

---

## 二、需求一：MCP Server 改造

### 2.1 关键决策

| 决策项 | 选择 | 理由 |
|--------|------|------|
| 工具粒度 | 细粒度（每个 API 一个工具） | MCP 工具 = 原子操作，Skill = 流程编排；灵活性最大、错误隔离、可复用 |
| Token 传递 | login 返回 Token，后续工具需传入 | 调用者显式控制 Token，无状态，更透明 |
| 桩工具处理 | 保留 list_mcp_tools，删除 6 个桩 | 工具列表干净，无无用桩 |
| HTTP 客户端 | httpx（异步） | MCP Server 运行在 asyncio 中，同步调用会阻塞事件循环 |
| 代码组织 | 独立 api_client.py 模块 | API 调用逻辑与 MCP 工具注册分离，职责清晰 |
| 实现范围 | 全部 API 一期实现 | 不分 Phase，所有 30 个 API 对应的工具一次到位 |
| 登录方式 | 手机号 + 短信验证码（不过期） | 客户先在网页获取验证码，再在 Skill 中传入 |

### 2.2 架构设计

#### 目录结构

```
mcp_server/
├── server.py              ← MCP 工具注册 + ASGI 路由（改造：删桩、注册新工具）
├── api_client.py          ← 新增：后端 API 调用封装（httpx async）
├── requirements.txt       ← 新增 httpx 依赖
└── static/access.html     ← 不变（后续需求二替代）
```

#### 数据流

```
Skill 调用 MCP 工具
    ↓
server.py 工具函数（参数校验 + 调用 api_client）
    ↓
api_client.py（构造请求 + 发送 httpx async 请求）
    ↓
https://18091.chinadny.com/api/...（后端 API）
```

#### 后端 API 信息

| 项目 | 值 |
|------|-----|
| API 基地址 | `https://18091.chinadny.com` |
| 前端页面 | `https://18092.chinadny.com` |
| 鉴权方式 | 自定义 `Token` 请求头（非 Authorization: Bearer） |
| Token 格式 | 32 位大写十六进制字符串 |
| API 路径风格 | 大驼峰命名，如 `/api/Protocol/GetSysBrandList` |
| 成功响应码 | `code === 20000` |

### 2.3 api_client.py 设计

#### 类结构

```python
import httpx
from typing import Optional

API_BASE_URL = "https://18091.chinadny.com"

class ProtocolApiClient:
    """封装所有后端 API 调用，使用 httpx.AsyncClient"""

    def __init__(self, base_url: str = API_BASE_URL):
        self.base_url = base_url
        self._client: Optional[httpx.AsyncClient] = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=30.0,
                verify=True,
            )
        return self._client

    async def _request(
        self,
        method: str,
        path: str,
        token: str,
        data: Optional[dict] = None,
    ) -> dict:
        """统一请求方法。
        - 构造 headers: {"Token": token, "Content-Type": "application/json"}
        - 发送请求、解析响应
        - 统一错误处理：网络异常、401、业务错误码
        """

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
```

#### 错误处理策略

| 场景 | 返回格式 |
|------|---------|
| 网络异常 | `{ "error": True, "code": "NETWORK_ERROR", "message": "网络请求失败: ..." }` |
| 后端返回非 20000 | `{ "error": True, "code": "API_ERROR", "message": "业务错误信息", "raw": {...} }` |
| Token 无效/过期 | `{ "error": True, "code": "AUTH_ERROR", "message": "Token无效，请重新登录" }` |
| HTTP 状态码异常 | `{ "error": True, "code": "HTTP_ERROR", "message": "..." }` |

### 2.4 MCP 工具完整清单（39 个）

#### 探测 + 登录（2 个）

| # | 工具名 | 对应 API | 类型 | 说明 |
|---|--------|---------|------|------|
| 1 | `list_mcp_tools` | （保留） | 探测 | 列出所有工具 + 鉴权探测 |
| 2 | `login` | `/api/Auth/LoginByCode` | 登录 | 手机号+验证码登录，返回 Token |

#### 大类管理（4 个）

| # | 工具名 | 对应 API | 类型 |
|---|--------|---------|------|
| 3 | `get_classify_list` | `POST /api/Protocol/GetSysClassifyList` | 只读 |
| 4 | `add_classify` | `POST /api/Protocol/AddSysClassify` | 写入 |
| 5 | `update_classify` | `POST /api/Protocol/UpdateSysClassify` | 写入 |
| 6 | `del_classify` | `POST /api/Protocol/DelSysClassify` | 写入 |

#### 设备类型管理（4 个）

| # | 工具名 | 对应 API | 类型 |
|---|--------|---------|------|
| 7 | `get_device_type_list` | `POST /api/Protocol/GetProtocolDeviceTypeList` | 只读 |
| 8 | `add_device_type` | `POST /api/Protocol/AddProtocolDeviceType` | 写入 |
| 9 | `update_device_type` | `POST /api/Protocol/UpdateProtocolDeviceType` | 写入 |
| 10 | `del_device_type` | `POST /api/Protocol/DelProtocolDeviceType` | 写入 |

#### 品牌管理（4 个）

| # | 工具名 | 对应 API | 类型 |
|---|--------|---------|------|
| 11 | `get_brand_list` | `POST /api/Protocol/GetSysBrandList` | 只读 |
| 12 | `add_brand` | `POST /api/Protocol/AddSysBrand` | 写入 |
| 13 | `update_brand` | `POST /api/Protocol/UpdateSysBrand` | 写入 |
| 14 | `del_brand` | `POST /api/Protocol/DelSysBrand` | 写入 |

#### 型号管理（4 个）

| # | 工具名 | 对应 API | 类型 |
|---|--------|---------|------|
| 15 | `get_model_list` | `POST /api/Protocol/GetProtocolModelList` | 只读 |
| 16 | `add_model` | `POST /api/Protocol/AddProtocolModel` | 写入 |
| 17 | `update_model` | `POST /api/Protocol/UpdateProtocolModel` | 写入 |
| 18 | `del_model` | `POST /api/Protocol/DelProtocolModel` | 写入 |

#### 规约信息管理（5 个）

| # | 工具名 | 对应 API | 类型 |
|---|--------|---------|------|
| 19 | `get_protocol_info_list` | `POST /api/Protocol/GetProtocolInfos` | 只读 |
| 20 | `add_protocol_info` | `POST /api/Protocol/AddProtocolInfo` | 写入 |
| 21 | `update_protocol` | `POST /api/Protocol/UpdateProtocol` | 写入 |
| 22 | `del_protocol_info` | `POST /api/Protocol/DelProtocolInfo` | 写入 |
| 23 | `upload_protocol_file` | `POST /api/file/UploadProtocolFile` | 写入 |

#### 数据项管理（4 个）

| # | 工具名 | 对应 API | 类型 |
|---|--------|---------|------|
| 24 | `get_data_item_list` | `POST /api/ProtocolDataItem/GetProtocolDataItemList` | 只读 |
| 25 | `add_data_item` | `POST /api/ProtocolDataItem/AddProtocolDataItem` | 写入 |
| 26 | `update_data_item` | `POST /api/ProtocolDataItem/UpdateProtocolDataItem` | 写入 |
| 27 | `del_data_item` | `POST /api/ProtocolDataItem/DelProtocolDataItem` | 写入 |

#### 脚本管理（4 个）

| # | 工具名 | 对应 API | 类型 |
|---|--------|---------|------|
| 28 | `gen_script` | `POST /api/ProtocolDataItem/GenDataScript` | 写入 |
| 29 | `get_script_list` | `POST /api/Protocol/GetDataScriptList` | 只读 |
| 30 | `get_json_detail` | `POST /api/Protocol/GetJsonDetail` | 只读 |
| 31 | `del_script` | `POST /api/Protocol/DelDataScript` | 写入 |

#### 系数管理（4 个）

| # | 工具名 | 对应 API | 类型 |
|---|--------|---------|------|
| 32 | `get_coeff_list` | `POST /api/Protocol/GetDataItemCoeffList` | 只读 |
| 33 | `add_coeff` | `POST /api/Protocol/AddDataItemCoeff` | 写入 |
| 34 | `update_coeff` | `POST /api/Protocol/UpdateDataItemCoeff` | 写入 |
| 35 | `del_coeff` | `POST /api/Protocol/DelDataItemCoeff` | 写入 |

#### 感知管理（4 个）

| # | 工具名 | 对应 API | 类型 |
|---|--------|---------|------|
| 36 | `get_sense_list` | `POST /api/Protocol/GetDataItemSenseList` | 只读 |
| 37 | `add_sense` | `POST /api/Protocol/AddDataItemSense` | 写入 |
| 38 | `update_sense` | `POST /api/Protocol/UpdateDataItemSense` | 写入 |
| 39 | `del_sense` | `POST /api/Protocol/DelDataItemSense` | 写入 |

#### 规约类型/字典（3 个）

| # | 工具名 | 对应 API | 类型 |
|---|--------|---------|------|
| 40 | `get_protocol_type_list` | `POST /api/Dictionary/GetDictionaryListPage` | 只读 |
| 41 | `save_protocol_type` | `POST /api/Dictionary/SaveDictionary` | 写入 |
| 42 | `del_protocol_type` | `POST /api/Dictionary/DeleteDictionary` | 写入 |

#### 功能项管理（3 个）

| # | 工具名 | 对应 API | 类型 |
|---|--------|---------|------|
| 43 | `get_function_type_list` | `POST /api/Protocol/GetProtocoFunctionTypeList` | 只读 |
| 44 | `save_function_item` | `POST /api/Protocol/SaveFunctionItem` | 写入 |
| 45 | `del_function_item` | `POST /api/Protocol/DelFunctionItem` | 写入 |

#### 导出 + 文件删除（3 个）

| # | 工具名 | 对应 API | 类型 |
|---|--------|---------|------|
| 46 | `export_model_data` | `POST /api/Protocol/ExportModelData` | 只读 |
| 47 | `export_data` | `POST /api/Protocol/ExportData` | 只读 |
| 48 | `del_protocol_file` | `POST /api/Protocol/DeleteProtocolFile` | 写入 |

### 2.5 server.py 变更清单

#### 删除

- 6 个桩工具函数：`query_device_classes`、`update_protocol_file`、`add_device_class`、`check_script_exists`、`publish_work_log`、`publish_converted_script`
- `TOOL_DEFINITIONS` 中的桩条目
- `_stub_response` 辅助函数
- `WRITE_TOOLS` 常量

#### 新增

- `from api_client import ProtocolApiClient` 导入
- `api_client = ProtocolApiClient()` 全局实例
- 47 个 async 工具函数（除 list_mcp_tools 外），每个模式：

```python
@mcp.tool()
async def add_brand(token: str, nameCN: str, name: str, code: str, deviceTypeId: int) -> dict:
    """新增品牌。

    Args:
        token: 登录后获取的 Token
        nameCN: 品牌中文名称
        name: 品牌英文名称
        code: 品牌编码
        deviceTypeId: 设备类型 ID
    """
    return await api_client.add_brand(token, nameCN, name, code, deviceTypeId)
```

#### 保留不变

- `list_mcp_tools` 工具（更新工具列表内容）
- `TokenManager` 类
- `AuthMiddleware` 类
- `CompositeApp` 类
- ASGI 鉴权中间件
- 接入页面路由
- Skills 下载路由

### 2.6 依赖变更

requirements.txt 新增：

```
httpx>=0.27.0
```

### 2.7 典型调用流程（Skill 视角）

```
1. login(phoneNum="13912986342", code="9413")
   → 返回 { token: "A3AAF6FA...", user: {...} }

2. get_brand_list(token="A3AAF6FA...", deviceTypeId=1)
   → 返回 { data: { rows: [...], total: N } }
   → 检查目标品牌是否已存在

3. add_brand(token="A3AAF6FA...", nameCN="华为", name="Huawei", code="HW", deviceTypeId=1)
   → 返回 { code: 20000, message: "成功" }

4. add_model(token="A3AAF6FA...", name="Model-X", brandId=123)
   → 返回 { code: 20000, message: "成功" }

5. add_protocol_info(token="A3AAF6FA...", protocolName="Modbus-RTU", classifyId=1, ...)
   → 返回 { code: 20000, message: "成功" }

6. add_data_item(token="A3AAF6FA...", ...)
   → 配置数据项

7. gen_script(token="A3AAF6FA...", ...)
   → 生成脚本文件
```

---

## 三、API 接口规格汇总

> 本模块 7 个页面 + 字典 + 功能项共 **30 个 API 接口**，分布在 3 个 Controller 中。

### 3.1 通用约定

- 所有接口均为 `POST` 方法
- 请求头携带 `Token`（由 MCP api_client 统一注入）
- 统一响应结构：`{ code: number, data: object, message: string }`
- 分页列表响应 data 结构：`{ rows: array, total: number }`
- `code === 20000` 表示成功
- `code === 40100` 表示登录失效
- `code === 40000` 表示业务异常

### 3.2 页面-API 映射矩阵

| 页面/模块 | 使用的 API |
|----------|-----------|
| 大类管理 | `GetSysClassifyList`, `AddSysClassify`, `DelSysClassify`, `UpdateSysClassify` |
| 设备类型管理 | `GetProtocolDeviceTypeList`, `AddProtocolDeviceType`, `DelProtocolDeviceType`, `UpdateProtocolDeviceType`, `GetSysClassifyList`(级联) |
| 品牌管理 | `GetSysBrandList`, `AddSysBrand`, `DelSysBrand`, `UpdateSysBrand`, `GetProtocolDeviceTypeList`(级联) |
| 型号管理 | `GetProtocolModelList`, `AddProtocolModel`, `DelProtocolModel`, `UpdateProtocolModel`, `GetSysBrandList`(级联), `ExportModelData` |
| 规约信息 | `GetProtocolInfos`, `AddProtocolInfo`, `DelProtocolInfo`, `UpdateProtocol`, `DeleteProtocolFile`, `GetProtocolDataItemList`, `GetDataScriptList`, `ExportData`, `GetDataItemCoeffList`, `GetProtocoFunctionTypeList`, 四级分类列表(级联), `GetDictionaryListPage`(规约类型) |
| 规约类型(字典) | `GetDictionaryListPage`, `SaveDictionary`, `DeleteDictionary` |
| 功能项管理 | `GetProtocoFunctionTypeList`, `SaveFunctionItem`, `DelFunctionItem` |

### 3.3 接口详细规格

#### A. 大类管理接口

##### A1: GetSysClassifyList — 查询大类列表

| 项目 | 值 |
|------|-----|
| 后端路径 | `POST /api/Protocol/GetSysClassifyList` |
| MCP 工具 | `get_classify_list` |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| sysName | string | 否 | 大类名称（模糊搜索） |
| pageIndex | number | 是 | 当前页码 |
| pageSize | number | 是 | 每页条数 |

**响应参数（data.rows 中每项）：**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | number | 大类编号 |
| sysName | string | 大类名称 |

##### A2: AddSysClassify — 新增大类

| 项目 | 值 |
|------|-----|
| 后端路径 | `POST /api/Protocol/AddSysClassify` |
| MCP 工具 | `add_classify` |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | number | 否 | 默认 -1 |
| sysName | string | 是 | 大类名称 |

##### A3: DelSysClassify — 删除大类

| 项目 | 值 |
|------|-----|
| 后端路径 | `POST /api/Protocol/DelSysClassify` |
| MCP 工具 | `del_classify` |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | number | 是 | 大类ID |
| sysName | string | 是 | 大类名称 |

##### A4: UpdateSysClassify — 更新大类

| 项目 | 值 |
|------|-----|
| 后端路径 | `POST /api/Protocol/UpdateSysClassify` |
| MCP 工具 | `update_classify` |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | number | 是 | 大类ID |
| sysName | string | 是 | 大类名称 |

#### B. 设备类型管理接口

##### B1: GetProtocolDeviceTypeList — 查询设备类型列表

| 项目 | 值 |
|------|-----|
| 后端路径 | `POST /api/Protocol/GetProtocolDeviceTypeList` |
| MCP 工具 | `get_device_type_list` |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| deviceTypeName | string | 否 | 类型名称（模糊搜索） |
| deviceTypeCode | string | 否 | 类型编码 |
| sysId | number | 否 | 所属大类ID（-1=全部） |
| pageIndex | number | 是 | 当前页码 |
| pageSize | number | 是 | 每页条数 |

**响应参数（data.rows 中每项）：**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | number | 记录ID |
| deviceTypeName | string | 类型名称 |
| deviceTypeCode | string | 类型编码 |
| sysId | number | 所属大类ID |
| sysName | string | 所属大类名称 |

##### B2: AddProtocolDeviceType — 新增设备类型

| 项目 | 值 |
|------|-----|
| 后端路径 | `POST /api/Protocol/AddProtocolDeviceType` |
| MCP 工具 | `add_device_type` |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| deviceTypeName | string | 是 | 类型名称 |
| deviceTypeCode | string | 是 | 类型编码（纯数字） |
| sysId | number | 是 | 所属大类ID |

##### B3: DelProtocolDeviceType — 删除设备类型

| 项目 | 值 |
|------|-----|
| 后端路径 | `POST /api/Protocol/DelProtocolDeviceType` |
| MCP 工具 | `del_device_type` |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | number | 是 | 记录ID |

##### B4: UpdateProtocolDeviceType — 更新设备类型

| 项目 | 值 |
|------|-----|
| 后端路径 | `POST /api/Protocol/UpdateProtocolDeviceType` |
| MCP 工具 | `update_device_type` |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | number | 是 | 记录ID |
| deviceTypeName | string | 是 | 类型名称 |
| deviceTypeCode | string | 是 | 类型编码 |
| sysId | number | 是 | 所属大类ID |

#### C. 品牌管理接口

##### C1: GetSysBrandList — 查询品牌列表

| 项目 | 值 |
|------|-----|
| 后端路径 | `POST /api/Protocol/GetSysBrandList` |
| MCP 工具 | `get_brand_list` |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| nameCN | string | 否 | 品牌名称-中文（模糊搜索） |
| code | string | 否 | 品牌编码 |
| deviceTypeId | number | 否 | 所属设备类型ID（-1=全部） |
| pageIndex | number | 是 | 当前页码 |
| pageSize | number | 是 | 每页条数 |

**响应参数（data.rows 中每项）：**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | number | 记录ID |
| nameCN | string | 品牌名称-中文 |
| name | string | 品牌名称-英文 |
| code | string | 品牌编码 |
| deviceTypeId | number | 所属设备类型ID |
| deviceTypeName | string | 所属设备类型名称 |

##### C2: AddSysBrand — 新增品牌

| 项目 | 值 |
|------|-----|
| 后端路径 | `POST /api/Protocol/AddSysBrand` |
| MCP 工具 | `add_brand` |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| nameCN | string | 是 | 品牌名称-中文 |
| name | string | 是 | 品牌名称-英文（禁止中文） |
| code | string | 是 | 品牌编码 |
| deviceTypeId | number | 是 | 所属设备类型ID |

##### C3: DelSysBrand — 删除品牌

| 项目 | 值 |
|------|-----|
| 后端路径 | `POST /api/Protocol/DelSysBrand` |
| MCP 工具 | `del_brand` |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | number | 是 | 记录ID |
| name | string | 是 | 品牌名称-英文 |
| code | string | 是 | 品牌编码 |

##### C4: UpdateSysBrand — 更新品牌

| 项目 | 值 |
|------|-----|
| 后端路径 | `POST /api/Protocol/UpdateSysBrand` |
| MCP 工具 | `update_brand` |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | number | 是 | 记录ID |
| nameCN | string | 是 | 品牌名称-中文 |
| name | string | 是 | 品牌名称-英文 |
| code | string | 是 | 品牌编码 |
| deviceTypeId | number | 是 | 所属设备类型ID |

#### D. 型号管理接口

##### D1: GetProtocolModelList — 查询型号列表

| 项目 | 值 |
|------|-----|
| 后端路径 | `POST /api/Protocol/GetProtocolModelList` |
| MCP 工具 | `get_model_list` |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 否 | 型号名称（模糊搜索） |
| brandId | number | 否 | 所属品牌ID（-1=全部） |
| pageIndex | number | 是 | 当前页码 |
| pageSize | number | 是 | 每页条数 |

**响应参数（data.rows 中每项）：**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | number | 记录ID |
| name | string | 型号名称 |
| brandId | number | 所属品牌ID |
| brandName | string | 所属品牌名称 |

##### D2: AddProtocolModel — 新增型号

| 项目 | 值 |
|------|-----|
| 后端路径 | `POST /api/Protocol/AddProtocolModel` |
| MCP 工具 | `add_model` |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 是 | 型号名称 |
| brandId | number | 是 | 所属品牌ID |

##### D3: DelProtocolModel — 删除型号

| 项目 | 值 |
|------|-----|
| 后端路径 | `POST /api/Protocol/DelProtocolModel` |
| MCP 工具 | `del_model` |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | number | 是 | 记录ID |

##### D4: UpdateProtocolModel — 更新型号

| 项目 | 值 |
|------|-----|
| 后端路径 | `POST /api/Protocol/UpdateProtocolModel` |
| MCP 工具 | `update_model` |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | number | 是 | 记录ID |
| name | string | 是 | 型号名称 |
| brandId | number | 是 | 所属品牌ID |

##### D5: ExportModelData — 导出型号统计数据

| 项目 | 值 |
|------|-----|
| 后端路径 | `POST /api/Protocol/ExportModelData` |
| MCP 工具 | `export_model_data` |
| 响应类型 | `blob`（二进制文件流） |

**请求参数：** 无业务参数（传空对象 `{}`）

#### E. 规约信息接口

##### E1: GetProtocolInfos — 查询规约列表

| 项目 | 值 |
|------|-----|
| 后端路径 | `POST /api/Protocol/GetProtocolInfos` |
| MCP 工具 | `get_protocol_info_list` |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| classifyId | number | 否 | 大类ID |
| deviceTypeId | number | 否 | 设备类型ID |
| brandId | number | 否 | 品牌ID |
| modelId | number | 否 | 型号ID |
| protoType | number | 否 | 规约类型（1=Modbus, 2=BACnet, 3=OPC-UA） |
| protocolName | string | 否 | 规约名称（模糊搜索） |
| pageIndex | number | 是 | 当前页码 |
| pageSize | number | 是 | 每页条数 |

**响应参数（data.rows 中每项）：**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | number | 规约ID |
| protocolName | string | 规约名称 |
| protoType | number | 规约类型编码 |
| protoTypeName | string | 规约类型名称 |
| classifyId | number | 大类ID |
| classifyName | string | 大类名称 |
| deviceTypeId | number | 设备类型ID |
| deviceTypeName | string | 设备类型名称 |
| brandId | number | 品牌ID |
| brandName | string | 品牌名称 |
| modelId | number | 型号ID |
| modelName | string | 型号名称 |
| protocolFiles | array | 规约文档文件列表 |

##### E2: AddProtocolInfo — 新增规约

| 项目 | 值 |
|------|-----|
| 后端路径 | `POST /api/Protocol/AddProtocolInfo` |
| MCP 工具 | `add_protocol_info` |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| protocolName | string | 是 | 规约名称 |
| protoType | number | 是 | 规约类型 |
| classifyId | number | 是 | 大类ID |
| deviceTypeId | number | 是 | 设备类型ID |
| brandId | number | 是 | 品牌ID |
| modelId | number | 是 | 型号ID |
| protocolFiles | array | 否 | 规约文档文件列表 |

##### E3: DelProtocolInfo — 删除规约

| 项目 | 值 |
|------|-----|
| 后端路径 | `POST /api/Protocol/DelProtocolInfo` |
| MCP 工具 | `del_protocol_info` |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | number | 是 | 规约ID |
| protocolName | string | 是 | 规约名称 |

##### E4: UpdateProtocol — 更新规约

| 项目 | 值 |
|------|-----|
| 后端路径 | `POST /api/Protocol/UpdateProtocol` |
| MCP 工具 | `update_protocol` |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | number | 是 | 规约ID |
| protocolName | string | 是 | 规约名称 |
| protoType | number | 是 | 规约类型 |
| classifyId | number | 是 | 大类ID |
| deviceTypeId | number | 是 | 设备类型ID |
| brandId | number | 是 | 品牌ID |
| modelId | number | 是 | 型号ID |
| protocolFiles | array | 否 | 规约文档文件列表 |

##### E5: DeleteProtocolFile — 删除规约文档文件

| 项目 | 值 |
|------|-----|
| 后端路径 | `POST /api/Protocol/DeleteProtocolFile` |
| MCP 工具 | `del_protocol_file` |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| fileId | number | 是 | 文件ID |

##### E6: GetProtocolDataItemList — 查询协议数据项列表

| 项目 | 值 |
|------|-----|
| 后端路径 | `POST /api/ProtocolDataItem/GetProtocolDataItemList` |
| MCP 工具 | `get_data_item_list` |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| protocolId | number | 是 | 规约ID |
| protoType | number | 是 | 规约类型 |
| pageIndex | number | 是 | 当前页码 |
| pageSize | number | 是 | 每页条数 |

##### E7: GetDataScriptList — 查询脚本列表

| 项目 | 值 |
|------|-----|
| 后端路径 | `POST /api/Protocol/GetDataScriptList` |
| MCP 工具 | `get_script_list` |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| protocolId | number | 是 | 规约ID |
| protoType | number | 是 | 规约类型 |

##### E8: ExportData — 导出协议数据项

| 项目 | 值 |
|------|-----|
| 后端路径 | `POST /api/Protocol/ExportData` |
| MCP 工具 | `export_data` |
| 响应类型 | `blob`（二进制文件流） |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| protocolId | number | 是 | 规约ID |

##### E9: GetDataItemCoeffList — 查询数据项系数列表

| 项目 | 值 |
|------|-----|
| 后端路径 | `POST /api/Protocol/GetDataItemCoeffList` |
| MCP 工具 | `get_coeff_list` |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| protocolId | number | 是 | 规约ID |
| dataItemId | number | 是 | 数据项ID |

##### E10: GetProtocoFunctionTypeList — 查询功能项列表

| 项目 | 值 |
|------|-----|
| 后端路径 | `POST /api/Protocol/GetProtocoFunctionTypeList` |
| MCP 工具 | `get_function_type_list` |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| functionTypeName | string | 否 | 功能项名称（模糊搜索） |
| functionCode | string | 否 | 功能码 |
| pageIndex | number | 是 | 当前页码 |
| pageSize | number | 是 | 每页条数 |

**响应参数（data.rows 中每项）：**

| 字段 | 类型 | 说明 |
|------|------|------|
| functionId | number | 功能项ID |
| functionName | string | 功能项名称 |
| functionCode | string | 功能项编码 |
| dataType | string | 数据类型 |
| dataTypeDesc | string | 数据类型描述 |
| required | string | 请求必选标志 |
| requiredDesc | string | 请求必选标志描述 |
| writeOrRead | string | 读写标志 |
| writeOrReadDesc | string | 读写标志描述 |
| unit | string | 数据单位 |
| length | string | 长度 |
| max | string | 最大值 |
| min | string | 最小值 |
| enumUnique | string | 标签标记 |
| enumDescription | string | 枚举描述 |

#### F. 规约类型接口（通用字典）

##### F1: GetDictionaryListPage — 查询字典项分页列表

| 项目 | 值 |
|------|-----|
| 后端路径 | `POST /api/Dictionary/GetDictionaryListPage` |
| MCP 工具 | `get_protocol_type_list` |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 否 | 字典项名称（模糊搜索） |
| dictItemCode | string | 否 | 字典项编码 |
| dictTypeCode | string | 是 | 字典类型编码（规约类型固定传 `'protocolType'`） |
| pageIndex | number | 是 | 当前页码 |
| pageSize | number | 是 | 每页条数 |

**响应参数（data.rows 中每项）：**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | number | 字典项ID |
| name | string | 字典项名称 |
| code | string | 字典项编码（对应 dictItemCode） |

##### F2: SaveDictionary — 保存字典项（新增/编辑共用）

| 项目 | 值 |
|------|-----|
| 后端路径 | `POST /api/Dictionary/SaveDictionary` |
| MCP 工具 | `save_protocol_type` |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | number | 否 | 字典项ID（新增时为0或空，编辑时必填） |
| name | string | 是 | 字典项名称 |
| dictItemCode | string | 是 | 字典项编码 |
| dictTypeCode | string | 是 | 字典类型编码（固定 `'protocolType'`） |

##### F3: DeleteDictionary — 删除字典项

| 项目 | 值 |
|------|-----|
| 后端路径 | `POST /api/Dictionary/DeleteDictionary` |
| MCP 工具 | `del_protocol_type` |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | number | 是 | 字典项ID |

#### G. 功能项管理接口

##### G1: SaveFunctionItem — 保存功能项（新增/编辑共用）

| 项目 | 值 |
|------|-----|
| 后端路径 | `POST /api/Protocol/SaveFunctionItem` |
| MCP 工具 | `save_function_item` |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| functionId | number | 否 | 功能项ID（新增时为0，编辑时必填） |
| functionName | string | 是 | 功能项名称 |
| functionCode | string | 是 | 功能项编码 |
| dataType | string | 否 | 数据类型：`1`/`2`/`4` |
| required | string | 否 | 请求必选标志：`0`/`1` |
| writeOrRead | string | 否 | 读写标志：`RO`/`WO`/`RW` |
| unit | string | 否 | 数据单位 |
| length | string | 否 | 长度 |
| max | string | 否 | 最大值 |
| min | string | 否 | 最小值 |
| enumUnique | string | 否 | 标签标记：`0`/`1` |
| enumDescription | string | 否 | 枚举描述 |

##### G2: DelFunctionItem — 删除功能项

| 项目 | 值 |
|------|-----|
| 后端路径 | `POST /api/Protocol/DelFunctionItem` |
| MCP 工具 | `del_function_item` |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| functionId | number | 是 | 功能项ID |

#### H. 文件上传接口

##### H1: UploadProtocolFile — 上传规约文档

| 项目 | 值 |
|------|-----|
| 后端路径 | `POST /api/file/UploadProtocolFile` |
| MCP 工具 | `upload_protocol_file` |
| 请求格式 | `multipart/form-data` |

**额外参数（通过 form field 传递）：**

| 参数 | 值 | 说明 |
|------|-----|------|
| fileType | `'proto'` | 文件类型标识 |
| file | binary | 文件内容 |

**响应参数：**

| 字段 | 类型 | 说明 |
|------|------|------|
| code | number | 状态码（20000=成功） |
| data.url | string | 文件访问路径 |
| data.fileId | number | 文件ID |
| data.uploadType | string | 上传类型标识 |
| message | string | 提示信息 |

#### I. 数据项 CRUD 接口

##### I1-I4: 数据项增删改查

| 操作 | 后端路径 | MCP 工具 |
|------|---------|---------|
| 新增 | `POST /api/ProtocolDataItem/AddProtocolDataItem` | `add_data_item` |
| 更新 | `POST /api/ProtocolDataItem/UpdateProtocolDataItem` | `update_data_item` |
| 删除 | `POST /api/ProtocolDataItem/DelProtocolDataItem` | `del_data_item` |

#### J. 脚本生成接口

##### J1: GenDataScript — 生成脚本

| 项目 | 值 |
|------|-----|
| 后端路径 | `POST /api/ProtocolDataItem/GenDataScript` |
| MCP 工具 | `gen_script` |

##### J2: GetJsonDetail — 获取脚本 JSON 内容

| 项目 | 值 |
|------|-----|
| 后端路径 | `POST /api/Protocol/GetJsonDetail` |
| MCP 工具 | `get_json_detail` |

##### J3: DelDataScript — 删除脚本

| 项目 | 值 |
|------|-----|
| 后端路径 | `POST /api/Protocol/DelDataScript` |
| MCP 工具 | `del_script` |

#### K. 系数/感知 CRUD 接口

##### K1: 系数（Coeff）

| 操作 | 后端路径 | MCP 工具 |
|------|---------|---------|
| 查询 | `POST /api/Protocol/GetDataItemCoeffList` | `get_coeff_list` |
| 新增 | `POST /api/Protocol/AddDataItemCoeff` | `add_coeff` |
| 更新 | `POST /api/Protocol/UpdateDataItemCoeff` | `update_coeff` |
| 删除 | `POST /api/Protocol/DelDataItemCoeff` | `del_coeff` |

##### K2: 感知（Sense）

| 操作 | 后端路径 | MCP 工具 |
|------|---------|---------|
| 查询 | `POST /api/Protocol/GetDataItemSenseList` | `get_sense_list` |
| 新增 | `POST /api/Protocol/AddDataItemSense` | `add_sense` |
| 更新 | `POST /api/Protocol/UpdateDataItemSense` | `update_sense` |
| 删除 | `POST /api/Protocol/DelDataItemSense` | `del_sense` |

### 3.4 四级分类级联关系

```
大类(Classify)
    │ sysId
    ▼
设备类型(DeviceType)
    │ deviceTypeId
    ▼
品牌(Brand)
    │ brandId
    ▼
型号(Model)
    │ modelId
    ▼
规约信息(Protocol) + 规约类型(字典)
```

级联清空规则（查询规约信息时）：

| 触发变更的字段 | 需要清空的下游字段 | 需要重新加载的选项 |
|---------------|-------------------|-------------------|
| 大类(classifyId) | deviceTypeId, brandId, modelId | 设备类型列表 |
| 设备类型(deviceTypeId) | brandId, modelId | 品牌列表 |
| 品牌(brandId) | modelId | 型号列表 |

---

## 四、需求二：Vue 前端 MCP 接入配置页面

### 4.1 目标

将 `access.html` 的 MCP 接入配置功能迁移到 Vue 运维平台中，作为规约管理下的子页面。页面已设计完成（静态预览：`static/mcp-access-preview.html`），迁移时以该预览为基准。

### 4.2 页面位置

在 `managerRouter.js` 的 `/protocol` children 中新增路由：

```javascript
{
  path: 'mcpAccessConfig',
  name: 'mcpAccessConfig',
  component: () => import('@/views/protocol/mcpAccessConfig'),
  meta: {
    title: 'MCP 接入配置',
    icon: '',
    roles: ['admin'],
    code: "待分配新UUID",    // 需后端权限系统注册
    keepAlive: true
  }
}
```

### 4.3 权限控制

- 使用与现有页面相同的 `code` UUID 机制
- 在侧边栏"规约管理"菜单下新增"MCP 接入配置"子菜单
- 按钮级别操作（如生成配置、复制等）通过 `v-permission:param="'UUID'"` 控制
- 需要后端权限系统中注册新的 UUID，分配给对应角色

### 4.4 页面设计

#### 4.4.1 整体风格

- **独立酷炫风格**，与现有 Element UI 表单页面不同
- 使用 `<style scoped>` 隔离样式，不影响其他页面
- 仍嵌入在平台 layout 中（侧边栏 + 顶栏不变）
- 设计令牌系统（CSS Custom Properties）：24 个语义化变量控制全部颜色/圆角/过渡
- 字体：`Inter`（正文）+ `JetBrains Mono`（代码/数值），通过 Google Fonts 加载

#### 4.4.2 主题系统（深色 / 浅色）

| 特性 | 实现方式 |
|------|----------|
| 默认主题 | 深色（OLED 风格，`#070b14` 基底） |
| 浅色主题 | `[data-theme="light"]` 覆盖全部 24 个令牌 |
| 切换动效 | View Transitions API：从按钮位置圆形 `clip-path` 扩散（600ms） |
| 降级方案 | 无 View Transitions 时用 `html.theme-transitioning` 临时类 + 420ms 过渡 |
| 持久化 | `localStorage('mcp-theme')` 记忆用户选择 |
| 系统偏好 | `prefers-color-scheme` 媒体查询自动检测 |
| 防闪烁 | `<head>` 内联脚本在渲染前设置 `data-theme`，避免 FOUC |
| 粒子联动 | 粒子颜色跟随主题动态切换（深色靛蓝+翠绿，浅色加深降调） |
| 代码面板 | 浅色模式下保持深色终端风格（语法高亮无需重做） |

#### 4.4.3 视觉特效清单

| 特效 | 技术 | 说明 |
|------|------|------|
| 粒子网络背景 | Canvas 2D | 55 个粒子 + 连线（距离 < 130px）+ 鼠标吸引/连线，主题颜色联动 |
| 3D 轨道系统 | CSS 3D transforms | Hero 区：三环交叉旋转（`rotateX(78deg)` + `rotateY(±58deg)`）+ 发光核心脉冲 + 卫星粒子 |
| 3D 分层全息卡片 | `preserve-3d` + `translateZ` | 5 层深度：数值 +52px、图标 +36px、标签 +20px、卡面 0px、背板 -26px |
| 鼠标跟随 tilt | JS `mousemove` | `perspective(1000px)` + `rotateX/Y`（最大 8°）+ 光泽跟随 + 光源方向投影 |
| 入场编排 | CSS `@keyframes` + stagger | 6 级延迟（d1~d6，50ms 间隔），卡片 3D 立起入场（`rotateX(32deg)` → 0） |
| 打字机效果 | JS 逐字符渲染 | JSON 6ms/字符、MD 3ms/字符，完成后切换为语法高亮版本 |
| 语法高亮 | 正则替换 | JSON（key/str/num/bool/null 分色）+ Markdown（h1/h2/bold/code/list 分色） |
| macOS 红绿灯 | CSS | 代码面板头部：红/黄/绿三圆点 |
| Toast 通知 | CSS transition | 底部居中弹出，2.4s 自动消失，深色底 + 绿色文字 |
| 顶部极光 | CSS `radial-gradient` | 固定定位渐变光带，主题颜色联动 |

#### 4.4.4 无障碍（a11y）

| 特性 | 实现 |
|------|------|
| ARIA | 平台列表 `role="radiogroup"`、每项 `role="radio"` + `aria-checked`、主题按钮 `aria-label` |
| 焦点样式 | `:focus-visible` 2px 主色轮廓 + offset |
| 减弱动画 | `@media (prefers-reduced-motion: reduce)` 关闭全部动画/粒子/3D 分层 |
| 触屏降级 | 检测 `ontouchstart` 跳过 tilt 交互 |
| 键盘导航 | 全部交互元素可 Tab 聚焦，平台选择支持按钮键盘操作 |

#### 4.4.5 响应式布局

| 断点 | 变化 |
|------|------|
| ≤ 1024px | 状态卡片 4列 → 2列 |
| ≤ 960px | 主内容双栏 → 单栏（左侧面板在上） |
| ≤ 860px | Hero 区横排 → 纵排（轨道缩小 0.72x） |
| ≤ 768px | 底部提示条 4列 → 2列 |
| ≤ 520px | 状态卡片 2列 → 1列 |

#### 4.4.6 页面结构与功能

**Hero 区**
- 状态徽章：`MCP SERVER ONLINE · v1.0`（绿色心跳圆点）
- 标题：`MCP 接入配置中心`（渐变文字）
- 副标题：`自动检测服务器地址 · 一键生成 AI IDE 配置 · 支持 7 大平台`
- 3D 轨道系统（右侧 / 移动端上方）

**状态卡片（4 张，3D 分层全息）**
1. 服务器地址 — 自动检测显示（如 `http://192.168.1.100:8765`）
2. Access Token — 脱敏显示 + 快捷复制按钮（带 copied 反馈）
3. 权限级别 — 徽章样式（`系统级 · 读写` / `用户级 · 只读`）
4. MCP 端点 — `/mcp` + `Streamable HTTP` 标签

**左侧面板（平台选择 + 操作）**
- 7 平台列表（单选 radio 组）：
  - Trae（字节跳动）
  - Cursor（AI-First IDE）
  - VS Code（GitHub Copilot）
  - Claude Desktop（Anthropic）
  - Windsurf（Codeium）
  - Cline（VS Code Extension）
  - Kimi Code（月之暗面）
- 每个平台：首字母 Logo + 名称 + 描述 + 选中指示条 + 勾选动画
- 操作按钮：
  - 「生成接入配置」（主按钮，渐变 + 流光扫过）
  - 「下载 .md 接入文本」（幽灵按钮）

**右侧代码面板**
- macOS 红绿灯 + 双 Tab（MCP 配置 / 完整接入文本）
- 右上角复制按钮（带 copied 状态）
- 打字机效果渲染，完成后语法高亮
- JSON Tab：展示各平台对应的 MCP 配置 JSON（`mcpServers` / `servers` 根键差异）
- Markdown Tab：完整接入文本（含配置、Skills 安装步骤、安全要求）

**底部提示条（4 项）**
- Token 为临时凭证，请勿泄露
- Skills 包服务端自动打包
- localhost 访问获得读写权限
- 接入后调用 list_mcp_tools 验证

#### 4.4.7 各平台配置生成规则

| 平台 | rootKey | 特殊字段 |
|------|---------|----------|
| Trae | `mcpServers` | `url` + `headers.Authorization` |
| Cursor | `servers` | `type: "http"` + `url` + `headers` |
| VS Code | `servers` | `type: "http"` + `url` + `headers` |
| Claude Desktop | `mcpServers` | `type: "streamableHttp"` + `url` + `headers` |
| Windsurf | `mcpServers` | `serverUrl`（非 url）+ `headers` |
| Cline | `mcpServers` | `type: "streamableHttp"` + `url` + `headers` |
| Kimi Code | `mcpServers` | `url` + `transport: "http"` + `headers` |

### 4.5 Vue 迁移注意事项

| 事项 | 说明 |
|------|------|
| Canvas 粒子 | 组件 `mounted()` 初始化，`beforeDestroy()` 清理 `requestAnimationFrame` |
| View Transitions | 需检测浏览器支持（Chrome 111+），Safari/Firefox 走降级路径 |
| 主题持久化 | `localStorage` key: `mcp-theme`，与预览页保持一致 |
| 3D tilt | `mounted` 绑定 `mousemove`，`beforeDestroy` 解绑；触屏设备跳过 |
| 样式隔离 | 全部 CSS 加 `scoped`；全局字体引入在 `public/index.html` 或组件内 `@import` |
| 数据接口化 | `accessInfo` 对象改为 API 获取（见 4.6） |
| Element UI | 不强制使用；页面视觉独立于 Element，仅 Toast/Dialog 等可复用 |

### 4.6 后端接口（后续实现）

当前先做前端页面，后端接口后续补充。预期需要：

| 接口 | 方法 | 说明 |
|------|------|------|
| `GET /api/access-info` | GET | 返回 `{ baseUrl, token, accessLevel, source }` 供状态卡片和配置生成使用 |
| `GET /api/docs/export-skills-package` | GET | 复用现有 Skills 包下载接口 |

### 4.7 文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/views/protocol/mcpAccessConfig.vue` | 新增 | MCP 接入配置页面组件（从 `mcp-access-preview.html` 迁移） |
| `src/router/managerRouter.js` | 修改 | 在 /protocol children 中新增路由 |
| `static/mcp-access-preview.html` | 参考 | 设计稿 / 静态预览（已实现全部视觉效果） |

---

## 五、实施顺序

| 步骤 | 内容 | 涉及文件 |
|------|------|---------|
| 1 | 创建 `api_client.py`，封装所有后端 API 调用 | `api_client.py`（新增） |
| 2 | 改造 `server.py`：删除桩工具，注册 47 个新工具 | `server.py`（修改） |
| 3 | 更新 `requirements.txt` 添加 httpx 依赖 | `requirements.txt`（修改） |
| 4 | 创建 Vue MCP 接入配置页面 | `mcpAccessConfig.vue`（新增） |
| 5 | 注册 Vue 路由 + 分配权限 UUID | `managerRouter.js`（修改） |

---

## 六、附录

### 6.1 规约管理现有子页面清单

| 页面 | 路径 | 权限 code (UUID) |
|------|------|------------------|
| 规约信息 | `modbusProtocolList` | `a27eb484-7f1c-44c6-a8d0-7fd7ac1efcfd` |
| 大类管理 | `classificationManage` | `d3f0c058-bf4a-462a-b9a1-02989ae1970d` |
| 设备类型 | `devicetypeManage` | `3d19f18c-dc2d-4b81-bd03-d6ee6a7852e5` |
| 品牌管理 | `brandManage` | `40a257d6-dc49-46e3-9e1f-4a7a6623d3b2` |
| 型号管理 | `protocolModelManage` | `0e4eacf4-67a9-4df5-b869-7aa31eb55d59` |
| 规约类型 | `protocolType` | `f695ad6f-ad5f-450f-bb43-dd47e00ca32e` |
| 功能项管理 | `functionType` | `a82e931f-c8b6-4a66-a269-457f5a716202` |
| 空调规约管理 | `acprotocolmanage` | `c03d9dda-d762-44ed-900f-29fed1fad760` |
| 协议统计报表 | `protocolStatis` | `D7C341E6-3593-4B67-8C8F-B6024EF7B03C` |
| 抄表方案任务 | `gatewayTaskCfg` | `D7C341E6-3593-4B67-8C8F-B6024EF7B03C` |
| **MCP 接入配置** ★ | `mcpAccessConfig` | **待分配** |
