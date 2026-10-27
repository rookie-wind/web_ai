---
name: protocol-conversion
description: >
  共享协议映射核心：定义 MQTT 和 HTTP 两种协议转换共用的映射规则。
  被 mqtt-conversion 和 http-conversion 在需要 JSON 脚本映射时加载引用。
  本 skill 不直接面向用户，不包含协议分析流程，只定义源到目标的映射规则。
when_to_use: >
  mqtt-conversion 或 http-conversion 执行到映射步骤时加载本 skill 获取映射规则。
  需要查阅映射规则字段定义、路径语法、类型系统、数组遍历准则、生成器清单时使用。
  需要运行统一映射引擎测试时使用（scripts/protocol_converter.py + test_protocol_converter.py）。
compatibility: "mapper_core.c（统一C映射引擎）；protocol_converter.py（Python镜像，用于测试）"
metadata:
  tags: [mapping-core, shared, mqtt, http, unified]
  order: 1
  author: song
  version: "1.4.0"
---

# 共享协议映射核心

> **角色：** 本 skill 是 mqtt-conversion 和 http-conversion 的共享映射规则库。不直接面向用户，不包含协议分析流程。mqtt-conversion 和 http-conversion 在执行到「映射步骤」时加载本 skill，按此处的规则设计字段映射。

## 1. 引擎归属

| 转换方向      | 配置加载引擎                   | 映射执行引擎          | 外层配置格式                            |
| --------- | ------------------------ | --------------- | --------------------------------- |
| MQTT→MQTT | `config_loader.c`        | `mapper_core.c` | `platform_name` + `mappings[]`    |
| HTTP→MQTT | `vpp_http_config.load.c` | `mapper_core.c` | `base_url` + `token{}` + `apis[]` |

两种协议共用 `mapper_core.c` 作为映射执行引擎，差异仅在配置加载方式和外层包装。外层格式定义在各自的 skill 中：

- MQTT 格式 → 见 `mqtt-conversion` 的「配置格式」章节
- HTTP 格式 → 见 `http-conversion` 的「配置格式」章节

本 skill 只定义 `mappings[]` / `data_mappings[]` / `body_params[]` 内部的映射规则。

## 2. 映射规则字段

每条映射规则支持以下字段：

| 字段                | 类型     | 必填  | 说明                                                                                | 协议适用                             |
| ----------------- | ------ | --- | --------------------------------------------------------------------------------- | -------------------------------- |
| `target`          | string | 是   | 目标 JSON 路径，支持 `.` `[index]` `@` 锚点                                                | 通用                               |
| `source_type`     | string | 是   | 取值：`path` / `constant` / `generated` / `array_foreach` / `context` | 通用                               |
| `source`          | string | 条件  | 源路径，支持 `.` `[index]` `[*]` `$item` `$idx`（`path`/`array_foreach` 时必填）             | 通用                               |
| `type`            | string | 是   | 值类型：`string` / `double` / `int` / `long` / `bool` / `object` / `substitute`       | 通用                               |
| `constant`        | any    | 条件  | 常量值（`source_type = "constant"` 时必填）                                               | 通用                               |
| `generator`       | string | 条件  | 生成器名称（`source_type = "generated"` 时必填）                                            | 通用                               |
| `generator_param` | any    | 否   | 生成器参数                                                                             | 通用                               |
| `scale`           | number | 否   | 数值缩放因子，默认 1.0                                                                     | 通用                               |
| `post_process`    | string | 否   | 字段级后处理函数名。**当前 C 引擎实现待完成**（见 `mapper_core.c` TODO）                              | 通用                               |
| `preprocess`      | string | 否   | 预处理函数名（如 `url_to_base64`）。**当前 C 引擎实现待完成**（见 `mapper_core.c` TODO）              | 通用                               |
| `item_type`       | string | 条件  | `array_foreach` 时必填：`object` / `key_value`                                        | 通用                               |
| `sub_mappings`    | array  | 否   | 子规则（对象嵌套或数组元素映射，递归结构）                                                             | 通用                               |

> **设计原则：** 优先使用 `scale`（单位换算）、`constant`（固定值）、`substitute`（上下文变量）、`generated`（时间戳/UUID）等声明式字段，减少对 `post_process` 硬编码函数的依赖。

## 3. 路径语法

| 语法        | 说明                                       | 示例                   |
| --------- | ---------------------------------------- | -------------------- |
| `.`       | 访问对象属性                                   | `data.deviceId`      |
| `[index]` | 访问特定索引                                   | `itemBody[0]`        |
| `[*]`     | 遍历数组所有元素（支持多层嵌套 `a[*].b[*]`）             | `itemBody[*]`        |
| `@`       | 目标数组锚点（仅 `array_foreach` 的 `target` 中使用） | `data.devices.@`     |
| `$item`   | 当前遍历的源数组元素（`array_foreach` 子映射中，可省略）     | `$item.commAddr`     |
| `$idx`    | 当前遍历索引，从 0 开始（字符串替换）                    | `devices[$idx].name` |
| `.` (单独)  | 返回根对象（HTTP 的 `source: "."`）              | `source: "."`        |

### $item 省略写法

在 `array_foreach` 的子映射中，`$item` 可省略，引擎自动将当前遍历元素作为源上下文：

```json
// 显式写法
{ "source": "$item.commAddr" }
// 省略写法（等价，推荐）
{ "source": "commAddr" }
```

## 4. 类型系统

| 目标类型         | 源值处理                                | 缩放            | 说明                 |
| ------------ | ----------------------------------- | ------------- | ------------------ |
| `string`     | 直接取值，数字转为字符串，bool 转为 "true"/"false" | 否             | —                  |
| `double`     | 取数字，非数字则取 0                         | 是（乘以 `scale`） | —                  |
| `int`        | 取整数部分，非数字则取 0                       | 是             | —                  |
| `long`       | 取长整型，非数字则取 0                        | 是             | —                  |
| `bool`       | 布尔值或非零数字转为 true/false               | 否             | —                  |
| `object`     | 复制源对象或根据 `sub_mappings` 构建          | 否             | 需配合 `sub_mappings` |
| `substitute` | 对 `constant` 值执行模板变量替换              | 否             | —                  |

### object + sub_mappings 递归构建

当源数据中已有完整对象结构，且目标需保持相似结构时：

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

引擎执行：在目标位置创建空 `cJSON_Object` → 根据 `source` 获取源对象作为新上下文 → 递归处理 `sub_mappings` → 添加到目标父节点。

## 5. source_type 分类

| source_type     | 说明                            | 协议适用 |
| --------------- | ----------------------------- | ---- |
| `path`          | 从源 JSON 路径取值                  | 通用   |
| `constant`      | 固定常量值（含模板变量字符串，由 `type: "substitute"` 触发替换） | 通用   |
| `generated`     | 调用生成器                         | 通用   |
| `array_foreach` | 数组遍历                          | 通用   |
| `context`       | 运行时上下文变量（如 startTime/endTime） | 通用（HTTP 常用） |

> `mapper_core.c` 统一支持以上 5 种 source_type，不区分协议。
>
> **设计说明**：模板变量替换（`$var$` 语法）不再作为独立的 `source_type`，而是通过 `source_type: "constant"` + `type: "substitute"` 组合实现。`constant` 字段存放含 `$var$` 的模板字符串，`value_type` 为 `substitute` 时由 `add_value_to_parent` 调用 `template_substitute` 执行替换。

## 6. 数组遍历准则

**核心原则：遍历数组的首要判断依据是目标格式要求，而非源数据是否有数组。**

| 目标字段类型     | 源数据情况  | 处理方式                                  | 示例                                                  |
| ---------- | ------ | ------------------------------------- | --------------------------------------------------- |
| **Array**  | 源有对应数组 | `array_foreach` + `@` 遍历              | `target: "data.devices.@"`, `source: "itemBody[*]"` |
| **Array**  | 源无对应数组 | `[0]` 固定索引，引擎 `ensure_path` 自动创建单元素数组 | `target: "devices[0].deviceId"`                     |
| **Object** | 源有数组   | 取源数组第一个元素 `[0]`，不遍历                   | `source: "item[0].field"`                           |
| **Object** | 源无数组   | 直接路径取值                                | `source: "item.field"`                              |

### ensure_path 自动建路径

当目标路径含 `[0]`（如 `devices[0].services[0].eventTime`）时，`ensure_path` 逐级检查路径，不存在则自动创建：

- 遇到 `[index]` → 确保该字段是数组 → 确保数组有足够元素（不足则补 `cJSON_CreateObject()`）
- 一条规则即可自动创建多层嵌套数组与对象

### 边界场景：源无数组但目标要求数组

源数据是纯对象（无任何数组），但目标协议要求 `devices`、`services` 等数组字段时，使用 `[0]` 固定索引，脚本以扁平化规则列表呈现：

```json
{
  "mappings": [
    { "target": "devices[0].deviceId", "source": "roadNo", "source_type": "path", "type": "string" },
    { "target": "devices[0].services[0].eventTime", "source": "dataTime", "source_type": "path", "type": "string" }
  ]
}
```

### item_type 模式

`array_foreach` 必填 `item_type` 字段：

| item_type   | 说明                            | 协议适用 |
| ----------- | ----------------------------- | ---- |
| `object`    | 每个源元素生成一个目标对象                 | 通用   |
| `key_value` | 每个源元素的每个 sub_mapping 生成一个独立对象 | 通用   |

### 多层嵌套 @ 锚点

外层 `array_foreach` 的 `target` 可含 `@`，其 `sub_mappings` 中又可使用 `@` 创建更深层级数组，每层独立创建数组。

## 7. 模板变量替换（substitute）

`substitute` 将 `constant` 中的模板变量 `$变量名$` 替换为运行时上下文值：

```json
{
  "target": "devId",
  "source_type": "constant",
  "type": "substitute",
  "constant": "$ssl_mqtt_server.gatewayID$"
}
```

> `source_type: "constant"` 提供模板字符串，`type: "substitute"` 触发模板替换执行。

### template_vars.def 已注册变量

| 变量名                         | 说明     |
| --------------------------- | ------ |
| `ssl_mqtt_server.gatewayID` | 网关 ID  |
| `ssl_mqtt_server.clientID`  | 客户端 ID |
| `ssl_mqtt_server.username`  | 用户名    |
| `ssl_mqtt_server.password`  | 密码     |

引擎从 `template_vars.def` 查找变量定义，将 `$变量名$` 替换为实际值。支持嵌套路径如 `$ssl_mqtt_server.gatewayID$`。

## 8. 生成器清单

| generator              | 说明                          | 协议适用 |
| ---------------------- | --------------------------- | ---- |
| `uuid`                 | UUID v4                     | 通用   |
| `current_timestamp`    | 当前时间戳（秒）                    | 通用   |
| `current_timestamp_ms` | 当前毫秒时间戳                     | 通用   |
| `timestamp_sec`        | 当前时间戳（秒）                    | 通用   |
| `timestamp_ms`         | 当前毫秒时间戳                     | 通用   |
| `datetime_compact`     | 紧凑日期时间（yyyyMMddHHmmss）      | 通用   |
| `datetime_str`         | 标准日期时间（yyyy-MM-dd HH:MM:SS） | 通用   |
| `random_string`        | 随机字符串                       | 通用   |
| `md5_sign`             | MD5 签名                      | 通用   |
| `batch_id`             | 批次 ID                       | 通用   |
| `sequence`             | 自增序列号                       | 通用   |

> `mapper_core.c` 统一识别所有生成器名称。MQTT 和 HTTP 可按各自引擎习惯使用。

## 9. scale 缩放

数值类型（`double`/`int`/`long`）支持 `scale` 字段进行单位换算：

```json
{ "target": "Ua", "source": "voltageA", "type": "double", "scale": 10.0 }
```

引擎执行：`目标值 = 源值 × scale`。

> 优先使用 `scale` 而非 `post_process` 实现单位换算。

## 10. post_process 后处理

> **⚠ 当前 C 引擎实现待完成：** `mapper_core.c` 中 `post_process` 字段已定义但执行逻辑未实现（仅有 TODO 注释）。以下为配置规范，待引擎补全后生效。

### 字段级后处理

```json
{ "target": "Ua", "source": "voltageA", "type": "double", "post_process": "trim" }
```

### 全局后处理

在根对象中定义 `post_process`，对整个转换后的输出对象执行：

```json
{
  "platform_name": "ywnyems",
  "post_process": "ywnyems_data_report",
  "mappings": [...]
}
```

> 尽量少用 `post_process`，优先用 `scale`/`constant`/`substitute`/`generated` 等声明式字段。

## 11. preprocess 预处理

> **⚠ 当前 C 引擎实现待完成：** `mapper_core.c` 中 `preprocess` 字段已定义但执行逻辑未实现。以下为配置规范，待引擎补全后生效。

`preprocess` 在取值前对源数据执行预处理函数：

```json
{ "target": "cImageContent", "source": "photo", "preprocess": "url_to_base64", "type": "string" }
```

| preprocess 函数   | 说明                    |
| --------------- | --------------------- |
| `url_to_base64` | 将 URL 内容转换为 base64 编码 |

> 字段名含 `photo`/`image`/`url` 时默认加入 `preprocess: url_to_base64`。

## 12. mapper_core.c 核心函数

| 函数                         | 说明                           |
| -------------------------- | ---------------------------- |
| `get_value_by_path`        | 按 JSON 路径取值                  |
| `ensure_path`              | 确保目标路径存在（含 `[index]` 自动创建数组） |
| `add_value_to_parent`      | 类型转换并添加到父对象                  |
| `generate_value`           | 调用生成器                        |
| `template_substitute`      | 模板变量替换                       |
| `process_rule`             | 统一规则处理入口                     |
| `process_array_foreach`    | 数组遍历处理                       |
| `process_normal_field`     | 普通字段处理                       |
| `get_flat_array_from_path` | 嵌套 `[*]` 展平                         |

### 数据结构 (mapper_core.h)

```c
typedef struct MappingRule {
    char target_path[256];
    char source_path[256];
    char source_type[32];     /* path / constant / generated / array_foreach / context */
    char value_type[16];      /* string / int / double / long / bool / object / substitute */
    char constant_value[256];
    char generator[64];
    char generator_param[128];
    double scale_factor;
    char post_process[64];
    char preprocess[64];
    char item_type[16];      /* object / key_value */
    int is_array_foreach;
    struct MappingRule* sub_mappings;
    int sub_mapping_count;
} MappingRule;
```

## 13. Python 测试镜像

`protocol_converter.py` 是 `mapper_core.c` 的 Python 镜像实现，用于本地测试验证：

```python
from protocol_converter import MapperCore

# MQTT 转换
result = MapperCore.transform_mqtt(source_json, mqtt_config, ctx)

# HTTP 转换
result = MapperCore.transform_http(source_json, http_config, ctx)
```

### 测试套件

`test_protocol_converter.py` 包含 91 项测试：

| 测试类                        | 测试数 | 覆盖内容                         |
| -------------------------- | --- | ---------------------------- |
| TestPathResolution         | 12  | 基本路径、嵌套、数组索引、通配符、"."路径、缺失路径  |
| TestEnsurePath             | 5   | 简单/嵌套/数组路径创建                 |
| TestTypeConversion         | 20  | 7种类型 × 各种源值组合                |
| TestGenerators             | 12  | 所有生成器类型                      |
| TestTemplateSubstitute     | 5   | 简单/嵌套/多变量/无匹配                |
| TestArrayForeach           | 6   | object/key_value/嵌套/dot路径/展平 |
| TestMQTTTransform          | 6   | MQTT 真实配置完整转换                |
| TestHTTPTransform          | 7   | HTTP 真实配置完整转换                |
| TestEdgeCases              | 7   | 空数组/缺失字段/缩放/深层嵌套             |
| TestRealConfigs            | 2   | 真实配置文件集成测试                   |
| TestUnifiedCodeConsistency | 4   | 统一引擎一致性验证                    |

运行测试：

```bash
cd <当前客户端技能目录>/protocol-conversion/scripts
python -m unittest test_protocol_converter -v
```

> 技能目录按客户端而定：Qoder 为 `.qoder/skills`，Trae 为 `.trae/skills`。
> 执行前先用实际存在的那个路径；不得将测试产物或 `__pycache__` 依赖当作技能目录输出位置。

## 14. 结构确认报告模板

> mqtt-conversion 和 http-conversion 在生成映射脚本前，引用本模板输出结构确认报告。

### 确认清单（8 项）

| 序号  | 确认项      | 说明                            |
| --- | -------- | ----------------------------- |
| 1   | 源数据结构分析  | 识别源 JSON 中的数组层级、字段名称、数据类型     |
| 2   | 目标数据结构分析 | 识别目标协议中的字段类型（Array 还是 Object） |
| 3   | 层级对应关系   | 明确源数组与目标数组的对应关系               |
| 4   | 字段映射表    | 列出每个源字段到目标字段的映射               |
| 5   | 遍历策略     | 确定哪些层级需要 `[*]` + `@` 遍历       |
| 6   | 固定索引位置   | 确定哪些位置使用 `[0]` 固定索引           |
| 7   | 常量/生成器清单 | 列出需要的常量值和生成器                  |
| 8   | 引擎对齐确认   | 确认配置格式与目标 C 引擎一致              |

> **严禁跳过结构确认步骤直接生成脚本！**

## 15. 参考文件机制

```
Step 1: 调用 MCP 工具 update_reference_file 更新本地参考文件
Step 2: 根据标识从本地参考文件读取协议格式
  → 读取成功：使用参考文件中的协议格式
  → 读取失败：使用 defaults/ 默认配置
Step 3: 与默认配置比较，有差异时提示用户确认
```

**MCP 工具职责边界：**

- MCP 工具：参考文件更新、内部参数查询
- 本地执行：文档解析、映射设计、脚本生成

> MCP 未就绪时，直接使用本skill中的的默认内部协议。

### 默认内部协议

源MQTT内部协议格式完整定义（businessObjList 结构）：

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
          "item": [{ "voltageA": 220.1, "timeStamp": "2023-01-17 00:00:00" }]
        }]
      }]
    }
  }],
  "respResult": { "resultCode": 0, "errDesc": "OK" },
  "sender": "iot_agent"
}

```

目标MQTT内部协议格式完整定义：

```json
 {"taskId":8220,"udSign":1,"commObj":{"commAddr":"526502000001"},"timeout":0,"priority":0,"spathId":0,"businessObjList":[{"dataObj":{"timeType":4,"dataItemList":[{"itemBody":[{"roadNo":1,"dataTime":"2026-04-29 11:42:00","taskFlag":1,"item":[{"tolCumulativeFlow":"75701.8"},{"cImageContent":"1F221F21201"}]}],"itemId":"31800003","itemName":"感知数据"}],"collCycle":1440}}],"cmdType":1}

```

## 16. 常见映射错误

### 错误 1：引擎引用错误

```
错误：MQTT 配置引用了 http_json_mapper.c
正确：MQTT → config_loader.c + mapper_core.c
正确：HTTP → vpp_http_config.load.c + mapper_core.c
```

### 错误 2：看到数组就遍历，忽略目标类型

```json
// 错误：目标 metrics 是 Object，不是 Array
{ "target": "metrics.@", "source": "item[*]" }
// 正确：目标要求 Object，取第一个元素
{ "target": "metrics.temp", "source": "item[0].temperature" }
```

### 错误 3：常量字段使用错误键名

```json
// 错误：使用了 constant_value
{ "source_type": "constant", "constant_value": "value" }
// 正确：JSON 键名是 constant
{ "source_type": "constant", "constant": "value" }
```

### 错误 4：substitute 配置错误

```json
// 错误：使用了旧的 substitute source_type
{ "target": "devId", "source_type": "substitute", "type": "substitute", "constant": "$var$" }
// 正确：source_type="constant" + type="substitute"
{ "target": "devId", "source_type": "constant", "type": "substitute", "constant": "$var$" }
```

### 错误 5：过度依赖 post_process

```json
// 不推荐
{ "target": "Ua", "source": "voltageA", "type": "double", "post_process": "custom_multiply_10" }
// 推荐：使用 scale 声明式实现
{ "target": "Ua", "source": "voltageA", "type": "double", "scale": 10.0 }
```

---

**文档版本**：1.3.0
**基于引擎**：mapper_core.c（统一映射核心），config_loader.c（MQTT 加载），vpp_http_config.load.c（HTTP 加载）
