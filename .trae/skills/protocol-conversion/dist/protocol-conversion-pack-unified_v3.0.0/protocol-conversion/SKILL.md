---
name: protocol-conversion
description: >
  共享协议映射核心：定义 MQTT 和 HTTP 两种协议转换共用的映射规则引擎。
  包含路径语法、类型系统、数组遍历、生成器、模板替换等统一规则。
  C 引擎 mapper_core.c 为两种协议的统一映射核心，由 mqtt-conversion 和 http-conversion 各自调用。
  本 skill 只负责共享映射部分，协议特有逻辑在各自 skill 中完成。
when_to_use: >
  需要了解共享映射规则（路径语法、类型系统、数组遍历等）时使用。
  mqtt-conversion 或 http-conversion 需要引用共享映射规则时使用。
  需要运行统一映射引擎测试时使用（scripts/protocol_converter.py + test_protocol_converter.py）。
compatibility: "mapper_core.c（统一C映射引擎）；protocol_converter.py（Python镜像，用于测试）"
metadata:
  tags: [mapping-core, shared, mqtt, http, unified]
  order: 1
  author: hub_port_test
  version: "3.0.0"
---

# 共享协议映射核心

> **职责：** 只定义 MQTT 和 HTTP 共用的映射规则。协议特有配置格式在各自 skill 中定义。

## 1. 架构概览

```
protocol-conversion (共享映射核心)
  ├── mapper_core.c / mapper_core.h    ← 统一 C 映射引擎
  ├── protocol_converter.py            ← Python 镜像（测试用）
  └── test_protocol_converter.py       ← 完备测试套件（91 项）
      │
      ├── mqtt-conversion              ← MQTT 特有: platform_name + mappings[]
      │   C 引擎: config_loader.c → mapper_core.c
      │
      └── http-conversion              ← HTTP 特有: base_url + token + apis[]
          C 引擎: vpp_http_config.load.c → mapper_core.c
```

### 引擎归属

| 转换方向 | 配置加载引擎 | 映射执行引擎 | 配置格式 |
|---------|------------|------------|---------|
| MQTT→MQTT | `config_loader.c` | `mapper_core.c` | `platform_name` + `mappings[]` |
| HTTP→MQTT | `vpp_http_config.load.c` | `mapper_core.c` | `base_url` + `token{}` + `apis[]` |

> 两种协议共用 `mapper_core.c` 作为映射执行引擎，差异仅在配置加载和外层包装。

## 2. 共享映射规则

以下规则在 MQTT 和 HTTP 转换中完全通用，由 `mapper_core.c` 统一实现。

### 2.1 映射规则字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `target` | string | 是 | 目标 JSON 路径，支持 `.` `[index]` `@` 锚点 |
| `source_type` | string | 是 | 取值：`path` / `constant` / `generated` / `array_foreach` / `substitute` / `context` |
| `source` | string | 条件必填 | 源路径，支持 `.` `[index]` `[*]` `$item` `$idx`（`path`/`array_foreach` 时） |
| `type` | string | 是 | 值类型：`string` / `double` / `int` / `long` / `bool` / `object` / `substitute` |
| `constant` | any | 条件必填 | 常量值（`source_type = "constant"` 时） |
| `generator` | string | 条件必填 | 生成器名称（`source_type = "generated"` 时） |
| `generator_param` | any | 否 | 生成器参数 |
| `scale` | number | 否 | 数值缩放因子，默认 1.0 |
| `post_process` | string | 否 | 字段级后处理函数名（尽量少用，优先用 scale/constant 实现） |
| `sub_mappings` | array | 否 | 子规则（用于对象嵌套或数组元素映射，递归结构） |
| `preprocess` | string | 否 | 预处理函数名（仅HTTP：如 `url_to_base64`） |
| `item_type` | string | 条件 | `array_foreach` 时必填：`object` / `key_value` |

> **设计原则：差异化的处理函数越少越好。** 优先使用 `scale`（单位换算）、`constant`（固定值）、`substitute`（上下文变量）、`generated`（时间戳/UUID）等声明式字段实现转换，避免依赖 C 引擎中的硬编码 `post_process` 函数。

### 2.2 路径语法

| 语法 | 说明 | 示例 |
|------|------|------|
| `.` | 访问对象属性 | `data.deviceId` |
| `[index]` | 访问特定索引 | `itemBody[0]` |
| `[*]` | 遍历数组所有元素 | `itemBody[*]` |
| `@` | 目标数组锚点（仅 array_foreach 的 target） | `data.devices.@` |
| `$item` | 当前遍历的源数组元素（MQTT） | `$item.commAddr` |
| `$idx` | 当前遍历索引从0开始（MQTT） | `devices[$idx].name` |
| `.` (单独) | 返回根对象（HTTP） | `source: "."` |

### 2.3 类型系统

| 目标类型 | 源值处理 | 缩放 |
|----------|----------|------|
| `string` | 直接取值，数字转为字符串，bool 转为 "true"/"false" | 否 |
| `double` | 取数字，非数字则取0 | 是（乘以 `scale`） |
| `int` | 取整数部分，非数字则取0 | 是 |
| `long` | 取长整型，非数字则取0 | 是 |
| `bool` | 布尔值或非零数字转为 true/false | 否 |
| `object` | 复制源对象或根据 `sub_mappings` 构建 | 否 |
| `substitute` | 对 `constant` 值执行模板变量替换 | 否 |

### 2.4 数组遍历判断准则

| 目标字段类型 | 源数据情况 | 处理方式 |
|-------------|----------|---------|
| Array | 源有对应数组 | `array_foreach` + `@` 遍历 |
| Array | 源无对应数组 | `[0]` 固定索引，创建单元素数组 |
| Object | 源有数组 | 取源数组第一个元素 `[0]` |
| Object | 源无数组 | 直接路径取值 |

#### item_type 两种模式

| item_type | 说明 | 适用场景 |
|-----------|------|---------|
| `object` | 每个源元素生成一个目标对象 | 通用，MQTT/HTTP 均可 |
| `key_value` | 每个源元素的每个 sub_mapping 生成一个独立对象 | HTTP 特有（如键值对列表） |

### 2.5 生成器清单

| generator | 说明 | 协议适用 |
|-----------|------|---------|
| `uuid` | UUID v4 | 通用 |
| `current_timestamp` | 当前时间戳（秒） | MQTT |
| `current_timestamp_ms` | 当前毫秒时间戳 | MQTT |
| `timestamp_sec` | 当前时间戳（秒） | HTTP |
| `timestamp_ms` | 当前毫秒时间戳 | HTTP |
| `datetime_compact` | 紧凑日期时间（yyyyMMddHHmmss） | 通用 |
| `datetime_str` | 标准日期时间（yyyy-MM-dd HH:MM:SS） | HTTP |
| `random_string` | 随机字符串 | 通用 |
| `md5_sign` | MD5 签名 | 通用 |
| `batch_id` | 批次 ID | 通用 |
| `sequence` | 自增序列号 | 通用 |

> 统一引擎中 MQTT 和 HTTP 的生成器名称都能识别，配置时按各自引擎习惯使用即可。

### 2.6 模板变量替换（substitute）

`substitute` 用于将 `constant` 中的模板变量 `$变量名$` 替换为运行时上下文值：

```json
{
  "target": "devId",
  "source_type": "substitute",
  "type": "substitute",
  "constant": "$ssl_mqtt_server.gatewayID$"
}
```

> `source_type` 和 `type` 必须同时为 `substitute`。支持嵌套路径如 `$ssl_mqtt_server.gatewayID$`。

### 2.7 source_type 分类

| source_type | 说明 | 协议适用 |
|-------------|------|---------|
| `path` | 从源 JSON 路径取值 | 通用 |
| `constant` | 固定常量值 | 通用 |
| `generated` | 调用生成器 | 通用 |
| `array_foreach` | 数组遍历 | 通用 |
| `substitute` | 模板变量替换 | MQTT |
| `context` | 运行时上下文变量 | HTTP |

> 统一引擎 `mapper_core.c` 支持所有 source_type。MQTT 引擎不使用 `context`，HTTP 引擎不使用 `substitute`，但核心逻辑统一处理。

## 3. 统一 C 映射引擎 (mapper_core)

### 3.1 核心函数

| 函数 | 说明 | 对应原引擎函数 |
|------|------|--------------|
| `get_value_by_path` | 按 JSON 路径取值 | MQTT: get_value_by_path / HTTP: http_get_json_by_path |
| `ensure_path` | 确保目标路径存在 | MQTT: ensure_path / HTTP: http_ensure_path |
| `add_value_to_parent` | 类型转换并添加到父对象 | MQTT: add_value_to_parent / HTTP: http_add_value_to_parent |
| `generate_value` | 调用生成器 | MQTT: generate_value / HTTP: http_generate_value |
| `template_substitute` | 模板变量替换 | MQTT: template_substitute |
| `process_rule` | 统一规则处理入口 | MQTT: process_rule / HTTP: http_process_rule |
| `process_array_foreach` | 数组遍历处理 | MQTT + HTTP 合并 |
| `process_normal_field` | 普通字段处理 | MQTT + HTTP 合并 |
| `get_flat_array_from_path` | 嵌套 [*] 展平 | MQTT 特有 |

### 3.2 数据结构 (mapper_core.h)

```c
typedef struct MappingRule {
    char                target_path[256];
    char                source_path[256];
    char                source_type[32];     /* path / constant / generated / array_foreach / substitute / context */
    char                value_type[16];       /* string / int / double / long / bool / object / substitute */
    char                constant_value[256];
    char                generator[64];
    char                generator_param[128];
    double              scale_factor;
    char                post_process[64];
    char                preprocess[64];
    char                item_type[16];        /* object / key_value */
    int                 is_array_foreach;
    struct MappingRule* sub_mappings;
    int                 sub_mapping_count;
} MappingRule;
```

### 3.3 Python 测试镜像

`protocol_converter.py` 是 `mapper_core.c` 的 Python 镜像实现，用于本地测试验证：

```python
from protocol_converter import MapperCore

# MQTT 转换
result = MapperCore.transform_mqtt(source_json, mqtt_config, ctx)

# HTTP 转换
result = MapperCore.transform_http(source_json, http_config, ctx)
```

## 4. 测试套件

`test_protocol_converter.py` 包含 91 项测试，覆盖：

| 测试类 | 测试数 | 覆盖内容 |
|--------|--------|---------|
| TestPathResolution | 12 | 基本路径、嵌套、数组索引、通配符、"."路径、缺失路径 |
| TestEnsurePath | 5 | 简单/嵌套/数组路径创建 |
| TestTypeConversion | 20 | 7种类型 × 各种源值组合 |
| TestGenerators | 12 | 所有生成器类型 |
| TestTemplateSubstitute | 5 | 简单/嵌套/多变量/无匹配 |
| TestArrayForeach | 6 | object/key_value/嵌套/dot路径/展平 |
| TestMQTTTransform | 6 | MQTT 真实配置完整转换 |
| TestHTTPTransform | 7 | HTTP 真实配置完整转换 |
| TestEngineDifferences | 4 | MQTT不支持context / HTTP不支持substitute |
| TestEdgeCases | 7 | 空数组/缺失字段/缩放/深层嵌套 |
| TestRealConfigs | 2 | 真实配置文件集成测试 |
| TestUnifiedCodeConsistency | 4 | 统一引擎一致性验证 |

运行测试：

```bash
cd .trae/skills/protocol-conversion/scripts
python -m unittest test_protocol_converter -v
```

## 5. 默认内部协议

当 MCP 更新后本地仍无参考文件时，使用 `defaults/` 目录下的默认配置。

### 内部MQTT源格式（MQTT→MQTT 的源 / HTTP→MQTT 的目标）

内部 MQTT 即 businessObjList 结构：

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

| 文件 | 用途 |
|------|------|
| `defaults/internal_mqtt_protocol.json` | 内部MQTT协议格式完整定义 |

## 6. 参考文件机制

```
Step 1: 调用 MCP 工具 update_reference_file 更新本地参考文件
Step 2: 根据标识从本地参考文件读取协议格式
        → 读取成功：使用参考文件中的协议格式
        → 读取失败：使用 defaults/ 默认配置
Step 3: 与默认配置比较，有差异时提示用户确认
```

**MCP工具职责边界**：
- MCP工具：参考文件更新、内部参数查询
- 本地执行：文档解析、映射设计、脚本生成

## 7. 结构确认报告

生成配置前必须输出结构确认报告，等待用户确认。

### 确认清单（8项）

| 序号 | 确认项 | 说明 |
|------|--------|------|
| 1 | 源数据结构分析 | 识别源 JSON 中的数组层级、字段名称、数据类型 |
| 2 | 目标数据结构分析 | 识别目标协议中的字段类型（Array/Object） |
| 3 | 层级对应关系 | 明确源数组与目标数组的对应关系 |
| 4 | 字段映射表 | 列出每个源字段到目标字段的映射 |
| 5 | 遍历策略 | 确定哪些层级需要 `[*]` + `@` 遍历 |
| 6 | 固定索引位置 | 确定哪些位置使用 `[0]` 固定索引 |
| 7 | 常量/生成器清单 | 列出需要的常量值和生成器 |
| 8 | 引擎对齐确认 | 确认配置格式与目标C引擎一致 |

> **严禁跳过结构确认步骤直接生成脚本！**

## 8. 常见错误与解决方案

### 错误1：引擎引用错误

```
错误：MQTT配置引用了 http_json_mapper.c
正确：MQTT → config_loader.c + mapper_core.c
正确：HTTP → vpp_http_config.load.c + mapper_core.c
```

### 错误2：看到数组就遍历，忽略目标类型

```json
// 错误：目标 metrics 是 Object，不是 Array
{ "target": "metrics.@", "source": "item[*]" }
// 正确：目标要求 Object，取第一个元素
{ "target": "metrics.temp", "source": "item[0].temperature" }
```

### 错误3：常量字段使用错误键名

```json
// 错误：使用了 constant_value
{ "source_type": "constant", "constant_value": "value" }
// 正确：JSON 键名是 constant
{ "source_type": "constant", "constant": "value" }
```

### 错误4：substitute 缺少 type 字段

```json
// 错误：只设置 source_type
{ "target": "devId", "source_type": "substitute", "constant": "$var$" }
// 正确：source_type 和 type 同时为 substitute
{ "target": "devId", "source_type": "substitute", "type": "substitute", "constant": "$var$" }
```

### 错误5：过度依赖 post_process 函数

```json
// 不推荐
{ "target": "Ua", "source": "voltageA", "type": "double", "post_process": "custom_multiply_10" }
// 推荐：使用 scale 声明式实现
{ "target": "Ua", "source": "voltageA", "type": "double", "scale": 10.0 }
```

## 9. 约束规则

| 规则 | 说明 |
|------|------|
| 统一映射核心 | MQTT 和 HTTP 共用 mapper_core.c，差异仅在配置外层包装 |
| 共享规则 | 映射规则、路径语法、类型系统在两种方向间通用 |
| 协议特有逻辑 | MQTT 特有逻辑在 mqtt-conversion，HTTP 特有逻辑在 http-conversion |
| 参考文件优先 | 使用前先调用 MCP 更新，无文件时用默认配置 |
| 声明式优先 | 优先用 scale/constant/substitute/generated，减少 post_process 依赖 |
| 用户确认 | 协议分析和字段映射完成后必须经用户确认 |
| 全量提取 | 协议文档中的字段/接口必须逐项提取，不得默认压缩 |

---

**文档版本**：3.0.0
**基于引擎**：mapper_core.c（统一映射核心），config_loader.c（MQTT加载），vpp_http_config.load.c（HTTP加载）
