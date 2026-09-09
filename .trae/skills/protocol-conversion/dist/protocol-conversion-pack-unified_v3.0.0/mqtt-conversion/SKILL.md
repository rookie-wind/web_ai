---
name: mqtt-conversion
description: >
  MQTT 协议转换配置生成：分析内部 MQTT 源协议和平台 MQTT 目标协议，
  设计字段映射关系，生成供 C 引擎读取的 JSON 配置文件。
  共享映射规则由 protocol-conversion 定义，本 skill 只负责 MQTT 特有逻辑。
  C 引擎：config_loader.c 加载配置 → mapper_core.c 执行映射。
  MQTT 特有功能：substitute 模板变量、$idx/$item 数组变量、嵌套 [*] 展平。
when_to_use: >
  用户提供了内部 MQTT 源协议文档和平台 MQTT 目标协议文档，需要生成 MQTT 协议转换配置时使用。
  用户需要将内部 MQTT 消息数据转换为平台要求的 MQTT 格式后上报时使用。
  用户描述了 MQTT broker、topic、publish/subscribe、json_mapper 等关键词时使用。
compatibility: "mapper_core.c（统一映射核心）；config_loader.c（配置加载）；protocol-converter MCP server（待开发）"
metadata:
  tags: [mqtt, conversion, config-gen, mapper_core]
  order: 1
  author: hub_port_test
  version: "2.0.0"
---

# MQTT 协议转换配置生成

> **职责：** 处理 MQTT 特有的配置格式和逻辑。共享映射规则（路径语法、类型系统、数组遍历等）见 `protocol-conversion`。

## 1. 概述

本 skill 用于生成驱动 `mapper_core.c` 引擎的 JSON 配置文件，将内部 MQTT 协议数据转换为平台 MQTT 格式后上报。

### 引擎链路

```
config_loader.c (加载JSON配置) → mapper_core.c (执行映射) → 输出平台MQTT消息
```

### MQTT 特有功能

| 功能 | 说明 | 共享/特有 |
|------|------|-----------|
| `substitute` source_type | 模板变量 `$var$` 替换 | **MQTT 特有** |
| `$item` 引用 | 当前遍历的源数组元素 | **MQTT 特有** |
| `$idx` 变量 | 当前遍历索引 | **MQTT 特有** |
| 嵌套 `[*]` 展平 | `a[*].b[*]` 自动扁平化 | **MQTT 特有** |
| `post_process` | 字段级/全局后处理函数 | MQTT 常用 |

> 以下功能由共享核心 `mapper_core.c` 统一实现，详见 `protocol-conversion`：
> 路径语法(`.`/`[index]`)、类型系统(string/int/double/long/bool/object)、数组遍历(`array_foreach`+`@`)、生成器、`constant`/`generated`/`path` source_type。

## 2. MQTT 配置格式

> **引擎**：`config_loader.c` 加载配置 → `mapper_core.c` 执行映射

### 2.1 根对象

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `platform_name` | string | 否 | 平台标识（仅元数据） |
| `topic_pattern` | string | 否 | MQTT Topic 模板，支持 `{field}` 占位符 |
| `post_process` | string | 否 | 全局后处理函数名 |
| `mappings` | array | 是 | 映射规则列表（使用共享映射规则） |

### 2.2 配置示例

```json
{
  "platform_name": "ywnyems",
  "mappings": [
    { "target": "action", "source_type": "constant", "constant": "devData", "type": "string" },
    { "target": "msgId", "source_type": "generated", "generator": "uuid", "type": "string" },
    { "target": "msgTime", "source_type": "generated", "generator": "current_timestamp", "type": "string" },
    { "target": "devId", "source_type": "substitute", "type": "substitute", "constant": "$ssl_mqtt_server.gatewayID$" },
    {
      "target": "data.terdata[0].terdata.@",
      "source": "businessObjList[0].dataObj.dataItemList[0].itemBody[*]",
      "source_type": "array_foreach",
      "sub_mappings": [
        { "target": "devId", "source": "commAddr", "type": "string" },
        {
          "target": "terdata.@",
          "source": "item[*]",
          "source_type": "array_foreach",
          "sub_mappings": [
            { "target": "Ua", "source": "voltageA", "type": "double" },
            { "target": "dataTime", "source": "timeStamp", "type": "string" }
          ]
        }
      ]
    }
  ]
}
```

## 3. MQTT 特有功能详解

### 3.1 模板变量替换（substitute）

`substitute` 用于将 `constant` 字段中的模板变量 `$变量名$` 替换为运行时上下文值，适用于引用外部上下文（如网关ID、客户端ID）。

**工作原理**：
1. `source_type: "substitute"` → 引擎取 `constant` 字段作为模板字符串
2. `type: "substitute"` → `add_value_to_parent` 调用 `template_substitute()` 进行替换
3. `template_substitute()` 从 `template_vars.def` 查找变量定义，将 `$变量名$` 替换为实际值

**已注册变量**：

```c
TEMPLATE_VAR("ssl_mqtt_server.gatewayID", ssl_mqtt_server.gatewayID)
TEMPLATE_VAR("ssl_mqtt_server.clientID",  ssl_mqtt_server.clientID)
TEMPLATE_VAR("ssl_mqtt_server.username",  ssl_mqtt_server.username)
TEMPLATE_VAR("ssl_mqtt_server.password",  ssl_mqtt_server.password)
```

**配置示例**：

```json
{
  "target": "devId",
  "source_type": "substitute",
  "type": "substitute",
  "constant": "$ssl_mqtt_server.gatewayID$"
}
```

> **注意**：`substitute` 同时作为 `source_type` 和 `type` 的值，两者缺一不可。支持嵌套路径如 `$ssl_mqtt_server.gatewayID$`。

### 3.2 当前数组元素引用（$item）

在 `array_foreach` 的子映射中使用，表示当前遍历到的源数组元素。可省略——引擎会将当前遍历的数组元素作为源上下文：

```json
// 显式写法
{ "source": "$item.commAddr" }
// 省略写法（推荐）
{ "source": "commAddr" }
```

### 3.3 数组索引变量（$idx）

在 `array_foreach` 的子映射中，`$idx` 会被替换为当前遍历索引（从 0 开始）：

```json
{ "target": "index", "source": "$idx", "type": "int" }
{ "target": "name", "source": "devices[$idx].name", "type": "string" }
```

### 3.4 嵌套 [*] 展平

MQTT 引擎支持多层嵌套 `[*]` 语法，自动将嵌套数组展平为一维数组：

```json
// 先遍历 itemBody 数组，再遍历每个元素下的 item 数组
{ "source": "itemBody[*].item[*]" }
// 结果：所有 itemBody 下所有 item 元素的扁平数组
```

### 3.5 后处理函数

#### 全局后处理

```json
{
  "platform_name": "ywnyems",
  "post_process": "ywnyems_data_report",
  "mappings": [...]
}
```

#### 字段级后处理

```json
{
  "target": "Ua",
  "source": "voltageA",
  "type": "double",
  "post_process": "trim"
}
```

### 3.6 对象整体引用

当源数据中已有完整对象结构时，使用 `type: "object"` 配合 `sub_mappings`：

```json
{
  "target": "metrics",
  "source": "item[0]",
  "source_type": "path",
  "type": "object",
  "sub_mappings": [
    { "target": "temp", "source": "temperature", "type": "string" },
    { "target": "vSig", "source": "voltage", "type": "string" }
  ]
}
```

## 4. 工作流程

```
Step 0: 文档预处理（条件步骤）
        若源/目标以 PDF/DOCX 提供，先转 Markdown
        工具：mcp_pandoc 或 Python pypdf
              ↓
Step 1: 分析源数据结构
        识别源 JSON 中的数组层级、字段名称、数据类型
              ↓
Step 2: 分析目标协议结构
        识别目标协议中的字段类型（Array/Object）
              ↓
Step 3: 输出结构确认报告（8项确认清单）
        列出源字段到目标字段的映射关系
        明确遍历策略和固定索引位置
              ↓
Step 4: 等待用户确认
        必须等待用户明确回复"确认"等
              ↓
Step 5: 生成映射脚本
        根据确认后的结构生成完整 JSON 配置
        输出到 scripts/，命名 mqtt_mapper_YYYYMMDDHHMM.json
```

**严禁跳过结构确认步骤直接生成脚本！**

## 5. 数组遍历判断准则

| 目标字段类型 | 源数据情况 | 处理方式 | 示例 |
|---|---|---|---|
| 目标字段是 **Array** | 源有对应数组 | `array_foreach` + `@` 遍历 | `target: "data.devices.@"` |
| 目标字段是 **Array** | 源无对应数组 | `[0]` 固定索引，创建单元素数组 | `target: "devices[0].deviceId"` |
| 目标字段是 **Object** | 源有数组 | 取源数组第一个元素 `[0]` | `source: "item[0].field"` |
| 目标字段是 **Object** | 源无数组 | 直接路径取值 | `source: "item.field"` |

> **核心原则：遍历数组的首要判断依据是目标格式要求，而非源数据是否有数组。**
> 但 `array_foreach` 必须依赖源数据中存在数组来驱动遍历。如果目标要求 Array 但源数据没有对应数组，则使用 `[0]` 固定索引。

## 6. 真实协议示例

### 源协议：iot_agent 电气量采集数据

```json
{
  "udSign": 1, "taskId": 1, "cmdType": 2, "priority": 2,
  "businessObjList": [{
    "dataObj": {
      "timeType": 0,
      "dataItemList": [{
        "itemId": "38000005", "finshFlag": 0,
        "itemBody": [{
          "commAddr": "1", "businessType": 1, "deviceType": 1,
          "item": [{"voltageA": 220.1, "voltageB": 223.1, "timeStamp": "2023-01-17 00:00:00"}]
        }]
      }]
    }
  }],
  "respResult": {"resultCode": 0, "errDesc": "OK"},
  "sender": "iot_agent"
}
```

### 目标协议：云南配电房协议（ywnyems）

```json
{
  "action": "devData",
  "msgId": "UUID",
  "data": { "terdata": [{ "devId": "1", "terdata": [{ "Ua": 220.1 }] }] }
}
```

### 生成的配置

见 2.2 节配置示例。

## 7. 常见错误

### 错误1：substitute 缺少 type 字段

```json
// 错误
{ "target": "devId", "source_type": "substitute", "constant": "$var$" }
// 正确
{ "target": "devId", "source_type": "substitute", "type": "substitute", "constant": "$var$" }
```

### 错误2：看到数组就遍历，忽略目标类型

```json
// 错误：目标 metrics 是 Object
{ "target": "metrics.@", "source": "item[*]" }
// 正确：取第一个元素
{ "target": "metrics.temp", "source": "item[0].temperature" }
```

### 错误3：常量字段键名错误

```json
// 错误：使用了 constant_value
{ "source_type": "constant", "constant_value": "value" }
// 正确：JSON 键名是 constant
{ "source_type": "constant", "constant": "value" }
```

## 8. 输出文件保存

| 项 | 说明 |
|----|------|
| 主输出 | JSON 配置文件（C 引擎读取） |
| 保存目录 | 本 skill 目录下 `scripts/` 文件夹 |
| 命名规则 | `mqtt_mapper_YYYYMMDDHHMM.json` |

## 9. MCP 工具集成

| 工具 | 用途 | 调用时机 |
|------|------|---------|
| `update_reference_file` | 更新本地参考文件 | 使用参考文件前 |
| `query_internal_protocol` | 查询内部MQTT协议格式 | 单文档/无文档输入时 |

**调用约定**：
- MCP 就绪时优先调用，确保参考文件和参数为最新
- MCP 未就绪时，使用 `defaults/` 目录下的默认配置，并在输出中说明

## 10. 约束规则

| 规则 | 说明 |
|------|------|
| 引擎对齐 | MQTT → config_loader.c + mapper_core.c |
| 共享规则 | 映射规则、路径语法、类型系统见 protocol-conversion |
| MQTT特有 | substitute、$item、$idx、嵌套[*]展平在本 skill 处理 |
| 参考文件优先 | 使用前先调用 MCP 更新，无文件时用默认配置 |
| 声明式优先 | 优先用 scale/constant/substitute/generated，减少 post_process 依赖 |
| 用户确认 | 协议分析和字段映射完成后必须经用户确认 |
| 全量提取 | 协议文档中的字段/接口必须逐项提取 |

---

**文档版本**：2.0.0
**基于引擎**：config_loader.c（加载）+ mapper_core.c（映射）
**共享规则**：见 protocol-conversion/SKILL.md
