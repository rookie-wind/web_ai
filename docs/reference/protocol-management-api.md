# 规约管理 — 基础数据模块 Spec

> 本文档覆盖"规约管理"一级导航下 7 个核心基础页面的业务逻辑与 API 接口规范。

---

## 一、模块概述

本模块构成规约管理的**四级分类层级**：

```
大类(Classification) → 设备类型(DeviceType) → 品牌(Brand) → 型号(Model) → 规约信息(Protocol)
```

每一级页面既独立管理自身 CRUD，又作为下一级的下拉数据源。`modbusProtocolList` 为最终消费页面，汇聚四级分类 + 规约类型，并提供数据项配置、脚本生成、感知结构生成三大高级功能。

---

## 二、页面业务逻辑详解

### 2.1 classificationManage.vue — 大类管理

**文件路径**: `src/views/protocol/classificationManage.vue` (235行)

#### 页面功能
管理规约体系的最顶层分类——"大类"。

#### 业务逻辑
1. **页面初始化**：`mounted` 时调用 `queryData()` 加载全部大类列表
2. **查询**：按大类名称模糊搜索，支持分页
3. **新增**：弹窗输入大类名称 → 表单校验(必填) → 调 `AddSysClassify` → 成功后刷新列表
4. **编辑**：点击编辑 → 回填 `id` + `sysName` → 调 `UpdateSysClassify` → 成功后刷新并关闭弹窗
5. **删除**：二次确认弹窗 → 调 `DelSysClassify` 传 `{id, sysName}` → 成功后刷新列表

#### 数据模型

| 字段 | 类型 | 说明 |
|------|------|------|
| id | number | 大类编号（后端自增） |
| sysName | string | 大类名称（必填） |

#### 权限码

| 操作 | 权限UUID |
|------|----------|
| 新增 | `7448e563-7fd5-42ef-a8bf-48a8b657a955` |
| 编辑 | `23721f51-4e60-48c6-9217-06c0b5cb72cc` |
| 删除 | `f5ed8131-263e-49d3-8df8-ca2a0d0b9856` |

---

### 2.2 devicetypeManage.vue — 设备类型管理

**文件路径**: `src/views/protocol/devicetypeManage.vue` (325行)

#### 页面功能
管理设备类型，每个设备类型归属于一个大类（级联第二级）。

#### 业务逻辑
1. **页面初始化**：
   - 调用 `queryData()` 加载设备类型列表
   - 调用 `GetClassificationList({sysName:'', code:'', pageIndex:1, pageSize:9999})` 加载全部大类
   - 将大类数据映射为下拉选项 `[{label: sysName, value: id}]`，搜索区追加"全部"选项(value=-1)
   - 新增弹窗默认选中第一个大类
2. **查询**：按类型名称、类型编码、所属大类ID搜索
3. **新增**：弹窗填写类型名称、类型编码（纯数字校验 `validateNumber`）、选择所属大类 → `AddProtocolDeviceType`
4. **编辑**：回填 `id, deviceTypeName, deviceTypeCode, sysId` → `UpdateProtocolDeviceType`
5. **删除**：传 `{id}` → `DelProtocolDeviceType`

#### 数据模型

| 字段 | 类型 | 说明 |
|------|------|------|
| id | number | 记录ID（后端自增） |
| deviceTypeName | string | 类型名称（必填） |
| deviceTypeCode | string | 类型编码（必填，纯数字） |
| sysId | number | 所属大类ID（必填） |
| sysName | string | 所属大类名称（列表展示用，来自后端关联） |

#### 特殊校验
- `deviceTypeCode` 输入时实时过滤非数字字符：`value.replace(/\D/g, '')`

---

### 2.3 brandManage.vue — 品牌管理

**文件路径**: `src/views/protocol/brandManage.vue` (348行)

#### 页面功能
管理品牌信息，每个品牌归属于一个设备类型（级联第三级）。

#### 业务逻辑
1. **页面初始化**：
   - 调用 `queryData()` 加载品牌列表
   - 调用 `GetProtocolDeviceTypeList({sysId:-1, pageIndex:1, pageSize:9999})` 加载全部设备类型
   - 映射为下拉选项，搜索区追加"全部"选项
   - 新增弹窗默认选中第一个设备类型
2. **查询**：按品牌名称(CN)、品牌编码、设备类型ID搜索
3. **新增**：弹窗填写品牌名称CN、品牌名称EN、品牌编码、选择设备类型 → `AddSysBrand`
4. **编辑**：回填 `id, name, code, nameCN, deviceTypeId` → `UpdateSysBrand`
5. **删除**：传 `{id, name, code}` → `DelSysBrand`

#### 数据模型

| 字段 | 类型 | 说明 |
|------|------|------|
| id | number | 记录ID |
| nameCN | string | 品牌名称-中文（必填） |
| name | string | 品牌名称-英文（必填，**禁止输入中文**） |
| code | string | 品牌编码（必填） |
| deviceTypeId | number | 所属设备类型ID |
| deviceTypeName | string | 所属设备类型名称（列表展示用） |

#### 特殊校验
- `name`（英文名）通过 `watch` 监听，正则 `/[\u4E00-\u9FA5]/` 检测中文字符，若包含则 `alert("禁止中文")` 并清空

---

### 2.4 protocolModelManage.vue — 型号管理

**文件路径**: `src/views/protocol/protocolModelManage.vue` (443行)

#### 页面功能
管理设备型号，每个型号归属于一个品牌（级联第四级/最末级）。额外提供**导出空调协议统计 Excel** 功能。

#### 业务逻辑
1. **页面初始化**：
   - 调用 `queryData()` 加载型号列表
   - 调用 `GetProtocolBrandList({nameCN:'', code:'', deviceTypeId:-1, pageIndex:1, pageSize:9999})` 加载全部品牌
   - 映射为下拉选项
2. **查询**：按型号名称、型号编码、所属品牌ID搜索
3. **新增**：弹窗填写型号名称、选择所属品牌 → `AddProtocolMode`
4. **编辑**：回填 `id, name, brandId` → `UpdateProtocolMode`
5. **删除**：传 `{id}` → `DelProtocolMode`
6. **导出**：调用 `ExportModelData` 获取 blob → 创建下载链接 → 文件名 `空调协议统计汇总.xlsx`

#### 数据模型

| 字段 | 类型 | 说明 |
|------|------|------|
| id | number | 记录ID |
| name | string | 型号名称（必填） |
| brandId | number | 所属品牌ID |
| brandName | string | 所属品牌名称（列表展示用） |

#### 导出逻辑
```javascript
ExportModelData({}).then(res => {
    const url = window.URL.createObjectURL(new Blob([res]))
    const link = document.createElement('a')
    link.href = url
    link.download = '空调协议统计汇总.xlsx'
    link.click()
})
```

---

### 2.5 modbusProtocolList.vue — 规约信息（核心页面）

**文件路径**: `src/views/protocol/modbusProtocolList.vue` (1204行)

#### 页面功能
规约管理的核心消费页面，汇聚四级分类 + 规约类型，提供规约的新增/编辑/删除 + 数据项配置 + 脚本生成 + 感知结构生成 + 导出。

#### 业务逻辑

##### 1) 页面初始化
- 并行加载四级分类下拉：
  - `GetClassificationList` → 大类选项
  - `GetProtocolDeviceTypeList` → 设备类型选项
  - `GetProtocolBrandList` → 品牌选项
  - `GetProtocolModelList` → 型号选项
- 加载规约类型下拉：`GetExceptionTypeListPage({dictTypeCode:'protocolType', pageIndex:1, pageSize:9999})`
- 加载功能类型列表：`GetProtocoFunctionTypeList` → 供数据项配置使用
- 调用 `queryData()` 加载规约列表

##### 2) 四级级联联动
- **大类变更** → 清空设备类型/品牌/型号 → 按新大类ID重新加载设备类型
- **设备类型变更** → 清空品牌/型号 → 按新设备类型ID重新加载品牌
- **品牌变更** → 清空型号 → 按新品牌ID重新加载型号

##### 3) 查询
搜索条件：`classifyId`(大类)、`deviceTypeId`(设备类型)、`brandId`(品牌)、`modelId`(型号)、`protoType`(规约类型)、`protocolName`(规约名称) + 分页参数

##### 4) 新增/编辑弹窗
- 字段：规约名称、规约类型(下拉)、大类(下拉)、设备类型(下拉)、品牌(下拉)、型号(下拉)
- 规约文档上传：`el-upload`，`action = window.baseUrl + '/api/file/UploadProtocolFile'`，`fileType: 'proto'`
- 编辑时回填已有文件列表

##### 5) 数据项配置（核心复杂功能）
- 点击"数据项配置"按钮 → 打开弹窗
- 根据选中规约的 `protoType` 动态加载不同子组件：
  - `protoType == 1 || protoType == 4` → `ModbusPrtlTable`（Modbus协议数据项表）
  - `protoType == 2` → `BacnetPrtlTable`（BACnet协议数据项表）
  - `protoType == 3` → `OpcuaPrtlTable`（OPC-UA协议数据项表）
- 向子组件传递 `protocolId` 和 `protoType`

##### 6) 脚本生成
- 点击"脚本生成"按钮 → 打开弹窗
- 根据 `protoType` 动态加载：
  - `protoType == 1 || protoType == 4` → `MbFile` 组件
  - `protoType == 2` → `BACnetFile` 组件
  - `protoType == 3` → `opcuaFile` 组件
- 传递 `protocolId` 和 `protoType`

##### 7) 感知结构生成
- 点击"感知结构生成"按钮 → 打开弹窗
- 统一使用 `PreFile` 组件（不区分协议类型）
- 传递 `protocolId` 和 `protoType`

##### 8) 导出
- 调用 `ExportData` 获取 blob → 创建下载链接 → 文件名 `协议数据项.xlsx`

##### 9) 删除
- 二次确认 → `DelProtocolInfo({id, protocolName})` → 刷新列表

#### 数据模型

| 字段 | 类型 | 说明 |
|------|------|------|
| id | number | 规约ID |
| protocolName | string | 规约名称 |
| protoType | number | 规约类型（1=Modbus, 2=BACnet, 3=OPC-UA, 4=Modbus） |
| protoTypeName | string | 规约类型名称（展示用） |
| classifyId | number | 大类ID |
| classifyName | string | 大类名称（展示用） |
| deviceTypeId | number | 设备类型ID |
| deviceTypeName | string | 设备类型名称（展示用） |
| brandId | number | 品牌ID |
| brandName | string | 品牌名称（展示用） |
| modelId | number | 型号ID |
| modelName | string | 型号名称（展示用） |
| protocolFiles | array | 规约文档文件列表 |

---

### 2.6 protocolType.vue — 规约类型

**文件路径**: `src/views/protocol/protocolType.vue` (207行)

#### 页面功能
管理规约类型字典数据（如 Modbus、BACnet、OPC-UA 等），使用通用字典接口。

#### 业务逻辑
1. **页面初始化**：调用 `queryData()` 加载规约类型列表
2. **查询**：按名称搜索，固定传 `dictTypeCode: 'protocolType'`
3. **新增**：弹窗填写名称 + 编码 → `SaveExceptionType`（新增/编辑共用接口）
4. **编辑**：回填 `name, id, code → dictItemCode` → `SaveExceptionType`
5. **删除**：传 `{id}` → `DeleteExceptionType`（无二次确认弹窗）

#### 数据模型

| 字段 | 类型 | 说明 |
|------|------|------|
| id | number | 字典项ID |
| name | string | 规约类型名称（必填） |
| dictItemCode | string | 规约类型编码（必填） |
| dictTypeCode | string | 固定值 `'protocolType'`（查询/新增时携带） |
| code | string | 规约编码（列表展示用，对应 dictItemCode） |

#### 特殊说明
- 该页面使用 `@/api/questionWizard` 中的**通用字典接口**，而非 `@/api/protocol` 的专用接口
- 后端实际路径为 `/api/Dictionary/*`

---

### 2.7 functionType.vue — 功能项管理

**文件路径**: `src/views/protocol/functionType.vue` (386行)

#### 页面功能
管理 Modbus 协议的功能项（功能码），定义数据项的元数据属性（数据类型、读写标志、精度、枚举等）。

#### 业务逻辑
1. **页面初始化**：调用 `queryData()` 加载功能项列表
2. **查询**：按功能项名称、功能码搜索
3. **新增**：弹窗填写12个字段 → `SaveFunctionItem`
4. **编辑**：回填全部字段 → `SaveFunctionItem`（新增/编辑共用接口）
5. **删除**：传 `{functionId}` → `DelFunctionItem`（无二次确认弹窗）

#### 数据模型

| 字段 | 类型 | 说明 |
|------|------|------|
| functionId | number | 功能项ID（后端自增） |
| functionName | string | 功能项名称（必填） |
| functionCode | string | 功能项编码（必填） |
| dataType | string | 数据类型：`1`=整型, `2`=浮点型, `4`=字符串 |
| required | string | 请求必选标志：`0`=非必须, `1`=必须 |
| writeOrRead | string | 读写标志：`RO`=只读, `WO`=只写, `RW`=可读写 |
| unit | string | 数据单位 |
| length | string | 长度 |
| max | string | 最大值 |
| min | string | 最小值 |
| enumUnique | string | 标签标记：`0`=不独有, `1`=独有 |
| enumDescription | string | 枚举描述 |
| dataTypeDesc | string | 数据类型描述（列表展示用） |
| requiredDesc | string | 请求必选标志描述（列表展示用） |
| writeOrReadDesc | string | 读写标志描述（列表展示用） |

---

## 三、API 接口汇总

### 3.1 接口总览

本模块 7 个页面共使用 **30 个 API 接口**，分布在 2 个 API 文件中：

| API 文件 | 接口数 | 后端 Controller |
|----------|--------|-----------------|
| `@/api/protocol` | 27 | `/api/Protocol/*` + `/api/ProtocolDataItem/*` |
| `@/api/questionWizard` | 3 | `/api/Dictionary/*` |

### 3.2 页面-API 映射矩阵

| 页面 | 使用的 API |
|------|-----------|
| classificationManage | `GetClassificationList`, `AddSysClassify`, `DelSysClassify`, `UpdateSysClassify` |
| devicetypeManage | `GetProtocolDeviceTypeList`, `AddProtocolDeviceType`, `DelProtocolDeviceType`, `UpdateProtocolDeviceType`, `GetClassificationList` |
| brandManage | `GetProtocolBrandList`, `AddSysBrand`, `DelSysBrand`, `UpdateSysBrand`, `GetProtocolDeviceTypeList` |
| protocolModelManage | `GetProtocolModelList`, `AddProtocolMode`, `DelProtocolMode`, `UpdateProtocolMode`, `GetProtocolBrandList`, `ExportModelData` |
| modbusProtocolList | `GetProtocolInfos`, `AddProtocolInfo`, `DelProtocolInfo`, `UpdateProtocol`, `DeleteProtocolFile`, `GetProtocolDataItemList`, `GetDataScriptList`, `ExportData`, `GetDataItemCoeffList`, `GetProtocoFunctionTypeList`, `GetClassificationList`, `GetProtocolDeviceTypeList`, `GetProtocolBrandList`, `GetProtocolModelList`, `GetExceptionTypeListPage` |
| protocolType | `GetExceptionTypeListPage`, `SaveExceptionType`, `DeleteExceptionType` |
| functionType | `GetProtocoFunctionTypeList`, `SaveFunctionItem`, `DelFunctionItem` |

---

### 3.3 接口详细规格

> **通用说明**
> - 所有接口均为 `POST` 方法
> - 请求头携带 `token: localStorage.getItem('xl_token')`（由 Axios 拦截器统一注入）
> - 统一响应结构：`{ code: number, data: object, message: string }`
> - 分页列表响应 `data` 结构：`{ rows: array, total: number }`
> - `code === 20000` 表示成功

---

#### A. 大类管理接口

##### API-A1: GetClassificationList — 查询大类列表
| 项目 | 值 |
|------|-----|
| 前端函数 | `GetClassificationList(data)` |
| 后端路径 | `POST /api/Protocol/GetSysClassifyList` |
| 调用页面 | classificationManage, devicetypeManage(级联), modbusProtocolList(级联) |

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

---

##### API-A2: AddSysClassify — 新增大类
| 项目 | 值 |
|------|-----|
| 前端函数 | `AddSysClassify(data)` |
| 后端路径 | `POST /api/Protocol/AddSysClassify` |
| 调用页面 | classificationManage |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | number | 否 | 默认 -1 |
| sysName | string | 是 | 大类名称 |

**响应参数：** 标准 `{ code, message }`

---

##### API-A3: DelSysClassify — 删除大类
| 项目 | 值 |
|------|-----|
| 前端函数 | `DelSysClassify(data)` |
| 后端路径 | `POST /api/Protocol/DelSysClassify` |
| 调用页面 | classificationManage |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | number | 是 | 大类ID |
| sysName | string | 是 | 大类名称 |

**响应参数：** 标准 `{ code, message }`

---

##### API-A4: UpdateSysClassify — 更新大类
| 项目 | 值 |
|------|-----|
| 前端函数 | `UpdateSysClassify(data)` |
| 后端路径 | `POST /api/Protocol/UpdateSysClassify` |
| 调用页面 | classificationManage |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | number | 是 | 大类ID |
| sysName | string | 是 | 大类名称 |

**响应参数：** 标准 `{ code, message }`

---

#### B. 设备类型管理接口

##### API-B1: GetProtocolDeviceTypeList — 查询设备类型列表
| 项目 | 值 |
|------|-----|
| 前端函数 | `GetProtocolDeviceTypeList(data)` |
| 后端路径 | `POST /api/Protocol/GetProtocolDeviceTypeList` |
| 调用页面 | devicetypeManage, brandManage(级联), modbusProtocolList(级联) |

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

---

##### API-B2: AddProtocolDeviceType — 新增设备类型
| 项目 | 值 |
|------|-----|
| 前端函数 | `AddProtocolDeviceType(data)` |
| 后端路径 | `POST /api/Protocol/AddProtocolDeviceType` |
| 调用页面 | devicetypeManage |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| deviceTypeName | string | 是 | 类型名称 |
| deviceTypeCode | string | 是 | 类型编码（纯数字） |
| sysId | number | 是 | 所属大类ID |

**响应参数：** 标准 `{ code, message }`

---

##### API-B3: DelProtocolDeviceType — 删除设备类型
| 项目 | 值 |
|------|-----|
| 前端函数 | `DelProtocolDeviceType(data)` |
| 后端路径 | `POST /api/Protocol/DelProtocolDeviceType` |
| 调用页面 | devicetypeManage |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | number | 是 | 记录ID |

**响应参数：** 标准 `{ code, message }`

---

##### API-B4: UpdateProtocolDeviceType — 更新设备类型
| 项目 | 值 |
|------|-----|
| 前端函数 | `UpdateProtocolDeviceType(data)` |
| 后端路径 | `POST /api/Protocol/UpdateProtocolDeviceType` |
| 调用页面 | devicetypeManage |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | number | 是 | 记录ID |
| deviceTypeName | string | 是 | 类型名称 |
| deviceTypeCode | string | 是 | 类型编码 |
| sysId | number | 是 | 所属大类ID |

**响应参数：** 标准 `{ code, message }`

---

#### C. 品牌管理接口

##### API-C1: GetProtocolBrandList — 查询品牌列表
| 项目 | 值 |
|------|-----|
| 前端函数 | `GetProtocolBrandList(data)` |
| 后端路径 | `POST /api/Protocol/GetSysBrandList` |
| 调用页面 | brandManage, protocolModelManage(级联), modbusProtocolList(级联) |

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

---

##### API-C2: AddSysBrand — 新增品牌
| 项目 | 值 |
|------|-----|
| 前端函数 | `AddSysBrand(data)` |
| 后端路径 | `POST /api/Protocol/AddSysBrand` |
| 调用页面 | brandManage |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| nameCN | string | 是 | 品牌名称-中文 |
| name | string | 是 | 品牌名称-英文（禁止中文） |
| code | string | 是 | 品牌编码 |
| deviceTypeId | number | 是 | 所属设备类型ID |

**响应参数：** 标准 `{ code, message }`

---

##### API-C3: DelSysBrand — 删除品牌
| 项目 | 值 |
|------|-----|
| 前端函数 | `DelSysBrand(data)` |
| 后端路径 | `POST /api/Protocol/DelSysBrand` |
| 调用页面 | brandManage |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | number | 是 | 记录ID |
| name | string | 是 | 品牌名称-英文 |
| code | string | 是 | 品牌编码 |

**响应参数：** 标准 `{ code, message }`

---

##### API-C4: UpdateSysBrand — 更新品牌
| 项目 | 值 |
|------|-----|
| 前端函数 | `UpdateSysBrand(data)` |
| 后端路径 | `POST /api/Protocol/UpdateSysBrand` |
| 调用页面 | brandManage |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | number | 是 | 记录ID |
| nameCN | string | 是 | 品牌名称-中文 |
| name | string | 是 | 品牌名称-英文 |
| code | string | 是 | 品牌编码 |
| deviceTypeId | number | 是 | 所属设备类型ID |

**响应参数：** 标准 `{ code, message }`

---

#### D. 型号管理接口

##### API-D1: GetProtocolModelList — 查询型号列表
| 项目 | 值 |
|------|-----|
| 前端函数 | `GetProtocolModelList(data)` |
| 后端路径 | `POST /api/Protocol/GetProtocolModelList` |
| 调用页面 | protocolModelManage, modbusProtocolList(级联) |

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

---

##### API-D2: AddProtocolMode — 新增型号
| 项目 | 值 |
|------|-----|
| 前端函数 | `AddProtocolMode(data)` |
| 后端路径 | `POST /api/Protocol/AddProtocolModel` |
| 调用页面 | protocolModelManage |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 是 | 型号名称 |
| brandId | number | 是 | 所属品牌ID |

**响应参数：** 标准 `{ code, message }`

---

##### API-D3: DelProtocolMode — 删除型号
| 项目 | 值 |
|------|-----|
| 前端函数 | `DelProtocolMode(data)` |
| 后端路径 | `POST /api/Protocol/DelProtocolModel` |
| 调用页面 | protocolModelManage |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | number | 是 | 记录ID |

**响应参数：** 标准 `{ code, message }`

---

##### API-D4: UpdateProtocolMode — 更新型号
| 项目 | 值 |
|------|-----|
| 前端函数 | `UpdateProtocolMode(data)` |
| 后端路径 | `POST /api/Protocol/UpdateProtocolModel` |
| 调用页面 | protocolModelManage |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | number | 是 | 记录ID |
| name | string | 是 | 型号名称 |
| brandId | number | 是 | 所属品牌ID |

**响应参数：** 标准 `{ code, message }`

---

##### API-D5: ExportModelData — 导出型号统计数据
| 项目 | 值 |
|------|-----|
| 前端函数 | `ExportModelData(data)` |
| 后端路径 | `POST /api/Protocol/ExportModelData` |
| 调用页面 | protocolModelManage |
| 响应类型 | `blob`（二进制文件流） |

**请求参数：** 无业务参数（传空对象 `{}`）

**响应参数：** Excel 文件二进制流（Blob），前端通过 `URL.createObjectURL` 下载

---

#### E. 规约信息接口

##### API-E1: GetProtocolInfos — 查询规约列表
| 项目 | 值 |
|------|-----|
| 前端函数 | `GetProtocolInfos(data)` |
| 后端路径 | `POST /api/Protocol/GetProtocolInfos` |
| 调用页面 | modbusProtocolList |

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

---

##### API-E2: AddProtocolInfo — 新增规约
| 项目 | 值 |
|------|-----|
| 前端函数 | `AddProtocolInfo(data)` |
| 后端路径 | `POST /api/Protocol/AddProtocolInfo` |
| 调用页面 | modbusProtocolList |

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

**响应参数：** 标准 `{ code, message }`

---

##### API-E3: DelProtocolInfo — 删除规约
| 项目 | 值 |
|------|-----|
| 前端函数 | `DelProtocolInfo(data)` |
| 后端路径 | `POST /api/Protocol/DelProtocolInfo` |
| 调用页面 | modbusProtocolList |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | number | 是 | 规约ID |
| protocolName | string | 是 | 规约名称 |

**响应参数：** 标准 `{ code, message }`

---

##### API-E4: UpdateProtocol — 更新规约
| 项目 | 值 |
|------|-----|
| 前端函数 | `UpdateProtocol(data)` |
| 后端路径 | `POST /api/Protocol/UpdateProtocol` |
| 调用页面 | modbusProtocolList |

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

**响应参数：** 标准 `{ code, message }`

---

##### API-E5: DeleteProtocolFile — 删除规约文档文件
| 项目 | 值 |
|------|-----|
| 前端函数 | `DeleteProtocolFile(data)` |
| 后端路径 | `POST /api/Protocol/DeleteProtocolFile` |
| 调用页面 | modbusProtocolList |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| fileId | number | 是 | 文件ID |

**响应参数：** 标准 `{ code, message }`

---

##### API-E6: GetProtocolDataItemList — 查询协议数据项列表
| 项目 | 值 |
|------|-----|
| 前端函数 | `GetProtocolDataItemList(data)` |
| 后端路径 | `POST /api/ProtocolDataItem/GetProtocolDataItemList` |
| 调用页面 | modbusProtocolList（数据项配置子组件使用） |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| protocolId | number | 是 | 规约ID |
| protoType | number | 是 | 规约类型 |
| pageIndex | number | 是 | 当前页码 |
| pageSize | number | 是 | 每页条数 |

**响应参数（data.rows 中每项）：** 协议数据项对象（具体字段由子组件 ModbusPrtlTable / BacnetPrtlTable / OpcuaPrtlTable 消费）

---

##### API-E7: GetDataScriptList — 查询脚本列表
| 项目 | 值 |
|------|-----|
| 前端函数 | `GetDataScriptList(data)` |
| 后端路径 | `POST /api/Protocol/GetDataScriptList` |
| 调用页面 | modbusProtocolList（脚本生成子组件使用） |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| protocolId | number | 是 | 规约ID |
| protoType | number | 是 | 规约类型 |

**响应参数：** 脚本文件列表

---

##### API-E8: ExportData — 导出协议数据项
| 项目 | 值 |
|------|-----|
| 前端函数 | `ExportData(data)` |
| 后端路径 | `POST /api/Protocol/ExportData` |
| 调用页面 | modbusProtocolList |
| 响应类型 | `blob`（二进制文件流） |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| protocolId | number | 是 | 规约ID |

**响应参数：** Excel 文件二进制流

---

##### API-E9: GetDataItemCoeffList — 查询数据项系数列表
| 项目 | 值 |
|------|-----|
| 前端函数 | `GetDataItemCoeffList(data)` |
| 后端路径 | `POST /api/Protocol/GetDataItemCoeffList` |
| 调用页面 | modbusProtocolList（数据项配置子组件使用） |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| protocolId | number | 是 | 规约ID |
| dataItemId | number | 是 | 数据项ID |

**响应参数：** 系数列表

---

##### API-E10: GetProtocoFunctionTypeList — 查询功能项列表
| 项目 | 值 |
|------|-----|
| 前端函数 | `GetProtocoFunctionTypeList(data)` |
| 后端路径 | `POST /api/Protocol/GetProtocoFunctionTypeList` |
| 调用页面 | modbusProtocolList, functionType |

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

---

#### F. 规约类型接口（通用字典）

##### API-F1: GetExceptionTypeListPage — 查询字典项分页列表
| 项目 | 值 |
|------|-----|
| 前端函数 | `GetExceptionTypeListPage(data)` |
| 后端路径 | `POST /api/Dictionary/GetDictionaryListPage` |
| 调用页面 | protocolType, modbusProtocolList(规约类型下拉) |

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

---

##### API-F2: SaveExceptionType — 保存字典项（新增/编辑共用）
| 项目 | 值 |
|------|-----|
| 前端函数 | `SaveExceptionType(data)` |
| 后端路径 | `POST /api/Dictionary/SaveDictionary` |
| 调用页面 | protocolType |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | number | 否 | 字典项ID（新增时为0或空，编辑时必填） |
| name | string | 是 | 字典项名称 |
| dictItemCode | string | 是 | 字典项编码 |
| dictTypeCode | string | 是 | 字典类型编码（固定 `'protocolType'`） |

**响应参数：** 标准 `{ code, message }`

---

##### API-F3: DeleteExceptionType — 删除字典项
| 项目 | 值 |
|------|-----|
| 前端函数 | `DeleteExceptionType(data)` |
| 后端路径 | `POST /api/Dictionary/DeleteDictionary` |
| 调用页面 | protocolType |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | number | 是 | 字典项ID |

**响应参数：** 标准 `{ code, message }`

---

#### G. 功能项管理接口

##### API-G1: SaveFunctionItem — 保存功能项（新增/编辑共用）
| 项目 | 值 |
|------|-----|
| 前端函数 | `SaveFunctionItem(data)` |
| 后端路径 | `POST /api/Protocol/SaveFunctionItem` |
| 调用页面 | functionType |

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

**响应参数：** 标准 `{ code, message }`

---

##### API-G2: DelFunctionItem — 删除功能项
| 项目 | 值 |
|------|-----|
| 前端函数 | `DelFunctionItem(data)` |
| 后端路径 | `POST /api/Protocol/DelFunctionItem` |
| 调用页面 | functionType |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| functionId | number | 是 | 功能项ID |

**响应参数：** 标准 `{ code, message }`

---

## 四、级联数据流

### 4.1 四级分类级联关系

```
┌──────────────────┐
│ 大类(Classify)    │  ← classificationManage 管理
│ API: GetSysClassifyList │
└───────┬──────────┘
        │ sysId
        ▼
┌──────────────────────────┐
│ 设备类型(DeviceType)      │  ← devicetypeManage 管理
│ API: GetProtocolDeviceTypeList │
└───────┬──────────────────┘
        │ deviceTypeId
        ▼
┌──────────────────────────┐
│ 品牌(Brand)              │  ← brandManage 管理
│ API: GetSysBrandList     │
└───────┬──────────────────┘
        │ brandId
        ▼
┌──────────────────────────┐
│ 型号(Model)              │  ← protocolModelManage 管理
│ API: GetProtocolModelList │
└───────┬──────────────────┘
        │ modelId
        ▼
┌──────────────────────────────┐
│ 规约信息(Protocol)            │  ← modbusProtocolList 管理
│ API: GetProtocolInfos         │
│ + 规约类型(字典) + 数据项配置   │
└──────────────────────────────┘
```

### 4.2 级联清空规则

在 `modbusProtocolList.vue` 中：

| 触发变更的字段 | 需要清空的下游字段 | 需要重新加载的选项 |
|---------------|-------------------|-------------------|
| 大类(classifyId) | deviceTypeId, brandId, modelId | 设备类型列表 |
| 设备类型(deviceTypeId) | brandId, modelId | 品牌列表 |
| 品牌(brandId) | modelId | 型号列表 |

---

## 五、文件上传接口

多个页面使用的文件上传接口（非本模块 API 文件定义，直接写 `action` URL）：

| 项目 | 值 |
|------|-----|
| 上传路径 | `POST {baseUrl}/api/file/UploadProtocolFile` |
| 认证 | Header: `token: localStorage.getItem('xl_token')` |
| 请求格式 | `multipart/form-data` |

**额外参数（通过 `data` 传递）：**

| 参数 | 值 | 使用场景 |
|------|-----|---------|
| fileType | `'proto'` | 规约文档上传（modbusProtocolList） |

**响应参数：**

| 字段 | 类型 | 说明 |
|------|------|------|
| code | number | 状态码（20000=成功） |
| data.url | string | 文件访问路径 |
| data.fileId | number | 文件ID |
| data.uploadType | string | 上传类型标识 |
| message | string | 提示信息 |

---

## 六、通用约定

### 6.1 统一响应结构
```json
{
  "code": 20000,       // 20000=成功, 40100=登录失效, 40000=业务异常
  "data": {
    "rows": [],        // 列表数据（分页接口）
    "total": 100       // 总记录数（分页接口）
  },
  "message": "成功"
}
```

### 6.2 权限控制
- 所有操作按钮通过 `v-permission:param="'UUID'"` 指令控制可见性
- UUID 对应后端权限码，在侧边栏初始化时通过 `GetRoleRouters` 获取当前用户权限列表

### 6.3 分页约定
- `pageIndex`：当前页码，从 1 开始
- `pageSize`：每页条数，默认 10
- 查询按钮点击时重置 `pageIndex = 1`
- 空结果时自动重置 `pageIndex = 1`

### 6.4 组件引用
- 所有页面统一使用 `XlTable`（`@/components/Table/Index`）作为表格组件
- 支持分页、序号列、slot 操作列
