# 边缘设备参数保存接口探测报告

> 探测日期：2026-09-23
> 探测方式：Playwright 浏览器自动化 + Network 面板抓包
> 目标系统：智慧能源单元（前端 8081 / 后端 7500）
> 目的：为 MCP 工具链补全「参数设置保存」能力提供接口依据

---

## 一、背景

### 1.1 当前 MCP 工具链覆盖范围

| MCP 工具 | 作用 | 写入位置 |
|---|---|---|
| `edge_upsert_device` | 创建/更新设备档案 | 服务端档案数据库（modifyDevice） |
| `edge_mount_device` | 挂载设备到父节点 | 服务端档案数据库（updateDeviceParent） |
| `edge_set_device_param` | 下发抄表参数到设备（模板会话按填报值；免模板直连会话逐台实时读当前参数回推） | 设备本地运行时（itemId=20200002） |
| `edge_call_device_data` | 召测设备数据 | 只读 |
| `edge_call_clock` | 召测时钟 | 只读 |

### 1.2 缺失环节

Web UI「参数设置」tab 中的「保存」按钮将参数写入**边缘设备本地运行时**，该操作**没有对应的 MCP 工具**。

当前建档流程只完成了「服务端档案写入」，缺少「设备本地参数保存」步骤。

---

## 二、接口一：网关 — 通讯地址保存

### 2.1 基本信息

| 项目 | 值 |
|---|---|
| **URL** | `POST /devArchManager/doc/set/modifyDeviceParam/v1` |
| **完整地址** | `http://10.0.11.175:7500/devArchManager/doc/set/modifyDeviceParam/v1` |
| **Content-Type** | `application/json;charset=utf-8` |
| **UI 位置** | 参数设置 tab → 通讯地址区域 → 蓝色「保存」按钮 |

### 2.2 请求头（业务相关字段）

| Header | 值 | 说明 |
|---|---|---|
| `appCode` | `5000` | 应用编码（固定） |
| `token` | 登录后返回 | 用户会话 token |
| `tokenEncrypt` | MD5 加密值 | token 校验 |
| `dateTime` | 毫秒时间戳 | 请求时间 |
| `userId` | `1` | 用户 ID |
| `ForwardPort` | `7500` | 转发端口 |
| `ForwardType` | `SmartUnit` | 转发类型 |

### 2.3 请求体

```json
{
  "deviceId": "6000001715117126",
  "parentId": "-1",
  "params": [
    {
      "deviceId": "6000001715117126",
      "itemId": "20100024",
      "itemBody": {
        "commAddr": "435600000200",
        "identifier": "224356000200"
      }
    }
  ]
}
```

### 2.4 字段说明

| 字段 | 说明 | 取值规则 |
|---|---|---|
| `deviceId` | 网关设备 ID | 建档返回的 deviceId |
| `parentId` | 父设备 ID | 网关固定为 `-1` |
| `params[].itemId` | 参数项 ID | `20100024` = 通讯地址 |
| `params[].itemBody.commAddr` | 通讯地址 | 条码转换：去第1/2/7位补3个0 |
| `params[].itemBody.identifier` | 设备条码 | 原始 12 位条码 |

### 2.5 成功响应

```json
{
  "rtnCode": 0,
  "rtnData": "操作成功",
  "rtnMsg": ""
}
```

### 2.6 其他已知 itemId（待补充）

| itemId | 参数类型 | UI 位置 | 状态 |
|---|---|---|---|
| `20100024` | 通讯地址 | 通讯地址区域 | **已确认** |
| 待探测 | 上行通讯参数 | 上行通讯参数区域 | 未探测 |
| 待探测 | 时钟 | 时钟区域 | 未探测 |

---

## 三、接口二：监测点 — 基本参数保存

### 3.1 基本信息

| 项目 | 值 |
|---|---|
| **URL** | `POST /devArchManager/doc/set/modifyDevice/v1` |
| **完整地址** | `http://10.0.11.175:7500/devArchManager/doc/set/modifyDevice/v1` |
| **Content-Type** | `application/json;charset=utf-8` |
| **UI 位置** | 参数设置 tab → 基本参数区域 → 蓝色「保存」按钮 |

### 3.2 请求体

```json
{
  "deviceId": "6000001540759336",
  "parentId": "6000001715117126",
  "collectorAddress": "",
  "proxyCommPort": "1",
  "measuredPointNum": "200",
  "protocolNumber": "200",
  "agentNum": "200",
  "deviceAddress": "001002003200",
  "baudRate": "6",
  "extInfos": [
    {"propertyCode": "authParam", "propertyValue": ",,,,"},
    {"propertyCode": "feeNum", "propertyValue": 195},
    {"propertyCode": "userSmallNo", "propertyValue": "1"},
    {"propertyCode": "cT", "propertyValue": "100"},
    {"propertyCode": "pT", "propertyValue": "10"},
    {"propertyCode": "ratedVoltage", "propertyValue": ""},
    {"propertyCode": "ratedCurrent", "propertyValue": ""},
    {"propertyCode": "lineType", "propertyValue": ""},
    {"propertyCode": "userBigNo", "propertyValue": "11"},
    {"propertyCode": "decimalNum", "propertyValue": "11"},
    {"propertyCode": "aCommAddr", "propertyValue": ""},
    {"propertyCode": "integerNum", "propertyValue": ""},
    {"propertyCode": "brand", "propertyValue": "1"},
    {"propertyCode": "brandName", "propertyValue": "安科瑞"},
    {"propertyCode": "decimalNumName", "propertyValue": "ADW300"}
  ]
}
```

### 3.3 字段说明

#### 顶层字段

| 字段 | 说明 | 来源 |
|---|---|---|
| `deviceId` | 监测点设备 ID | 建档返回 |
| `parentId` | 父网关设备 ID | 挂载后回读 |
| `collectorAddress` | 采集器地址 | 工程输入（可为空） |
| `proxyCommPort` | 通信端口号（1=RS485-1） | 工程输入 |
| `measuredPointNum` | 测量点号 | 工程输入 |
| `protocolNumber` | 协议代号（200=新联MQTT） | 映射表 |
| `agentNum` | 分路号/代理号 | 挂载后回读（可能被服务端修正） |
| `deviceAddress` | 设备条码 | 工程输入 |
| `baudRate` | 波特率编码（6=9600） | 映射表 |

#### extInfos 属性

| propertyCode | 说明 | 示例值 | 来源 |
|---|---|---|---|
| `brand` | 品牌编码 | `1` | 映射表 |
| `brandName` | 品牌名称 | `安科瑞` | 映射表 |
| `decimalNum` | 型号编码 | `11` | 映射表 |
| `decimalNumName` | 型号名称 | `ADW300` | 映射表 |
| `userBigNo` | 用户大分类号 | `11`（电表类） | 映射表 |
| `userSmallNo` | 抄表间隔编码 | `1`（1分钟） | 映射表 |
| `cT` | 电流变比 | `100` | 工程输入 |
| `pT` | 电压变比 | `10` | 工程输入 |
| `feeNum` | 费率数 | `195` | 服务端默认 |
| `authParam` | 认证参数 | `,,,,` | 服务端默认 |
| `ratedVoltage` | 额定电压 | 空 | 工程输入 |
| `ratedCurrent` | 额定电流 | 空 | 工程输入 |
| `lineType` | 接线方式 | 空 | 工程输入 |
| `aCommAddr` | 备用通讯地址 | 空 | 预留 |
| `integerNum` | 整数位 | 空 | 预留 |

### 3.4 成功响应

```json
{
  "rtnCode": 0,
  "rtnData": {"devicesStatus": "0"},
  "rtnMsg": "请求成功"
}
```

---

## 四、两个接口的对比

| 对比项 | 网关通讯地址保存 | 监测点基本参数保存 |
|---|---|---|
| **接口路径** | `modifyDeviceParam/v1` | `modifyDevice/v1` |
| **参数组织** | `params[].itemId` + `itemBody` | 扁平字段 + `extInfos` 数组 |
| **参数标识** | 通过 `itemId` 区分类型 | 直接字段名 |
| **parentId** | `-1`（自身） | 实际父设备 ID |
| **写入位置** | 设备本地运行时 | 设备本地运行时 |
| **与建档接口关系** | 不同接口 | 路径相同但参数结构不同 |

> **注意**：监测点的 `modifyDevice/v1`（参数设置保存）与建档时的 `modifyDevice`（服务端档案写入）路径相同，但请求体结构不同。参数设置版本包含 `baudRate`、`extInfos` 等运行时字段，建档版本包含 `deviceTypeId`、`deviceAddress` 等档案字段。

---

## 五、完整建档流程（建议）

```
阶段一：服务端档案
  1. edge_upsert_device    → 创建设备档案（服务端数据库）
  2. edge_mount_device     → 挂载到父节点（服务端数据库）

阶段二：设备本地参数保存  ← 当前缺失，需新增 MCP 工具
  3. 网关通讯地址保存      → modifyDeviceParam/v1 (itemId=20100024)
  4. 监测点基本参数保存    → modifyDevice/v1 (参数设置版)

阶段三：下发与验证
  5. edge_set_device_param → 下发抄表参数到设备（itemId=20200002）
  6. edge_call_clock      → 召测网关时钟，成功即判网关可达
  7. edge_call_device_data  → 召测验证
```

---

## 六、MCP 工具优化建议

### 6.1 新增工具：`edge_save_device_parameters`

**用途**：对应 Web UI「参数设置 → 保存」按钮，将参数写入设备本地运行时。

**建议接口设计**：

```json
{
  "name": "edge_save_device_parameters",
  "description": "保存设备参数到本地运行时（对应 UI 参数设置 tab 的保存按钮）",
  "inputSchema": {
    "properties": {
      "task_id": { "type": "string", "description": "会话 ID" },
      "node_key": { "type": "string", "description": "拓扑节点键" },
      "plan_id": { "type": "string", "description": "计划 ID" },
      "confirm": { "type": "boolean", "description": "用户确认" }
    },
    "required": ["task_id", "node_key"]
  }
}
```

**内部逻辑**：
- 根据 `node_key` 判断设备类型
- 网关 → 调用 `modifyDeviceParam/v1`（itemId=20100024）
- 监测点 → 调用 `modifyDevice/v1`（参数设置版，含 baudRate/extInfos）
- 从 plan 上下文获取 deviceId、parentId、参数映射值

### 6.2 需要确认的事项

| 事项 | 说明 | 优先级 |
|---|---|---|
| `edge_set_device_param` 与「保存」按钮的关系 | 确认是同一接口还是不同接口 | 高 |
| 网关上行通讯参数的 itemId | 需要额外抓包确认 | 中 |
| 网关时钟参数的 itemId | 需要额外抓包确认 | 中 |
| 监测点 `modifyDevice/v1` 与建档 `modifyDevice` 的区分 | 路径相同，参数结构不同，服务端如何区分 | 高 |
| `stopDigit`/`checkDigit`/`dataDigit` 字段 | 监测点保存请求中未出现这些字段，可能由服务端从 baudRate 推导 | 中 |

### 6.3 风险提示

- **`modifyDevice/v1` 路径复用**：建档和参数设置共用同一 URL，但请求体结构不同。MCP Server 需要根据上下文（是否有 `deviceTypeId` vs 是否有 `baudRate`）判断调用意图
- **挂载后代理号修正**：`edge_mount_device` 返回 `agent_num_fixed=true` 时，服务端会修正代理号/分路号，参数保存必须使用挂载后回读的实际值
- **token 时效**：UI 请求携带 `token` + `tokenEncrypt` + `dateTime`，MCP 工具需要复用边缘后端的登录会话

---

## 七、附录：实测数据

### 7.1 网关 AI_test4 实测

| 项目 | 值 |
|---|---|
| deviceId | `6000001715117126` |
| 条码 | `224356000200` |
| 通讯地址 | `435600000200` |
| proxyCommType | `13`（MQTT） |
| 保存结果 | rtnCode=0 |

### 7.2 监测点200 实测

| 项目 | 值 |
|---|---|
| deviceId | `6000001540759336` |
| parentId | `6000001715117126` |
| 条码 | `001002003200` |
| 品牌 | 安科瑞（brand=1） |
| 型号 | ADW300（decimalNum=11） |
| 波特率 | 9600（baudRate=6） |
| 抄表间隔 | 1分钟（userSmallNo=1） |
| CT/PT | 100/10 |
| 保存结果 | rtnCode=0 |
