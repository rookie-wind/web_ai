---
name: test-validation
description: >
  协议转换配置测试验证：对生成的 JSON 转换配置进行冒烟测试，
  验证字段映射正确性、数据类型转换、边界条件处理、错误恢复能力。
  适用于 MQTT/HTTP/Modbus 所有协议类型的转换配置。
when_to_use: >
  转换配置生成完成后，需要验证配置正确性时使用。
  用户要求测试转换结果、检查映射是否正确时使用。
  打包发布前的质量门控验证。
compatibility: "Requires xl-protocol-agent MCP server (待开发)"
metadata:
  tags: [test, validation, smoke-test]
  order: 4
  author: hub_port_test
  version: "0.1.0"
---

# 协议转换配置测试验证

> **目标：** 对生成的 JSON 转换配置进行冒烟测试，验证字段映射正确性、数据类型转换、边界条件处理。

## 适用场景

- 转换配置生成完成后的验收测试
- 打包发布前的质量门控
- 修改配置后的回归测试
- 故障排查：快速定位哪些映射项异常

## 测试策略矩阵

### 通用测试策略

| 测试维度 | 方法 | 通过标准 | 失败条件 |
|---------|------|---------|---------|
| 配置格式 | JSON 语法校验 + 字段完整性 | 所有必填字段存在 | 缺少必填字段或 JSON 语法错误 |
| 字段映射 | 构造模拟输入 → 检查输出字段 | 所有目标字段有值且类型匹配 | 目标字段缺失或类型不匹配 |
| 类型转换 | 构造边界值输入 → 检查转换结果 | 转换结果正确 | 转换错误或精度丢失 |
| 数组遍历 | 构造数组输入 → 检查遍历结果 | 所有元素正确映射 | 遍历遗漏或重复 |
| 常量字段 | 检查所有 constant 字段 | 值正确且类型匹配 | 值错误或类型不匹配 |
| 生成器 | 检查 generated 字段 | 格式正确且唯一性 | 格式错误或重复 |
| 钩子函数 | 检查 preProcess/postProcess | 钩子正确执行 | 钩子未执行或错误 |

### MQTT 专项测试

| 测试项 | 方法 | 通过标准 |
|--------|------|---------|
| Topic 订阅 | 检查 source.topics 配置 | 所有源 Topic 存在且格式正确 |
| 消息格式 | 构造模拟 MQTT 消息 | 正确解析并映射 |
| QoS 配置 | 检查 QoS 值 | QoS 在 0/1/2 范围内 |
| 状态上报 | 检查 statusReport 配置 | interval 和字段配置正确 |
| 批处理 | 构造超限数据 | 正确拆包且 batchId 一致 |

### HTTP 专项测试

| 测试项 | 方法 | 通过标准 |
|--------|------|---------|
| 接口路径 | 检查 path 配置 | 路径格式正确，占位符有效 |
| 认证配置 | 检查 auth 配置 | token 路径/header/expiresIn 正确 |
| 请求体构造 | 构造模拟请求 | bodyParams 完整且类型正确 |
| 响应映射 | 构造模拟响应 | dataMappings 正确提取 |
| Token 刷新 | 检查 expiresIn | 过期时间合理（>0） |
| 链式调用 | 检查 nextApi | 链式 API 顺序正确 |

### Modbus 专项测试

| 测试项 | 方法 | 通过标准 |
|--------|------|---------|
| 寄存器地址 | 检查 address 配置 | 地址在有效范围（0-65535） |
| 功能码 | 检查 functionCode | 功能码在 1/2/3/4/5/6/16 范围内 |
| 数据布局 | 检查 byteOrder/wordOrder/bitOrder | 与文档一致，非默认值 |
| 比例系数 | 构造已知寄存器值 | scale 转换结果正确 |
| 位域提取 | 构造已知状态字 | 各 bit 提取正确 |
| 读块合并 | 检查 readPlan | 读块数合理，无过多碎片 |
| 轮询分组 | 检查 polling 分组 | fast/slow/event 分配合理 |

## 操作流程

### Phase 1 — 配置格式校验

```
用户："测试这份 MQTT 转换配置"
```

**步骤：**

1. 读取 config.json
2. JSON 语法校验（确保可解析）
3. 必填字段完整性检查
4. 字段类型校验（int/float/string/bool/object/array）
5. 输出格式校验报告

### Phase 2 — 构造测试数据

根据源协议规格构造模拟输入数据：

| 数据类型 | 构造方式 |
|---------|---------|
| 正常数据 | 基于文档示例构造 |
| 边界数据 | 空值/最大值/最小值 |
| 异常数据 | 缺少字段/类型错误/格式错误 |
| 数组数据 | 单元素/多元素/空数组/超限数组 |
| 特殊字符 | Unicode/特殊符号/超长字符串 |

### Phase 3 — 执行模拟转换

```mermaid
flowchart LR
    INPUT["模拟输入数据"] --> PARSE["解析输入 JSON"]
    PARSE --> MAP["按映射配置转换"]
    MAP --> GEN["执行生成器"]
    GEN --> OUT["模拟输出 JSON"]
    OUT --> CHECK["验证输出格式"]
```

> **注意：** 当前无 C 引擎可执行，AI 根据映射配置手动模拟转换逻辑。
> MCP 就绪后，调用 `execute_conversion_test` 工具在沙箱中执行。

### Phase 4 — 验证输出

逐项检查输出：

| 检查项 | 方法 |
|--------|------|
| 字段完整性 | 所有目标字段都存在 |
| 类型正确性 | 值类型与配置 type 一致 |
| 值正确性 | 转换结果与预期一致 |
| 数组遍历 | 元素数量正确，每项映射正确 |
| 常量值 | constant 字段值正确 |
| 生成器格式 | UUID/时间戳/批次ID 格式正确 |
| 嵌套结构 | 嵌套层级和路径正确 |

### Phase 5 — 生成测试报告

```json
{
  "testId": "test_20260817_001",
  "configFile": "config.json",
  "conversionType": "mqtt_to_mqtt",
  "totalTests": 15,
  "passed": 13,
  "failed": 1,
  "skipped": 1,
  "results": [
    {
      "name": "配置格式校验",
      "status": "passed",
      "details": "JSON 语法正确，所有必填字段存在"
    },
    {
      "name": "字段映射 roadNo→deviceId",
      "status": "passed",
      "details": "roadNo=1 → G30_ROAD_1，格式正确"
    },
    {
      "name": "时间戳转换 dataTime→ts",
      "status": "passed",
      "details": "20260604142400 → 1780583040000，正确"
    },
    {
      "name": "数组遍历 metrics 映射",
      "status": "failed",
      "details": "缺少 vSig 字段映射，item.Ua 未映射到 vSig"
    }
  ],
  "summary": "13/15 通过，1 项失败需修复，1 项跳过"
}
```

## 调用的 MCP 工具（MCP 就绪后）

| 工具 | 用途 | 当前替代方案 |
|------|------|------------|
| `validate_config_format` | 校验配置 JSON 格式和字段完整性 | AI 人工检查 |
| `generate_test_data` | 根据协议规格生成模拟测试数据 | AI 手动构造 |
| `execute_conversion_test` | 在沙箱中执行转换并返回结果 | AI 手动模拟转换 |
| `get_test_report` | 获取测试报告 | AI 输出报告 |
| `save_conversion_config` | 保存修正后的配置 | AI 输出 JSON |

## 约束规则

| 规则 | 说明 |
|------|------|
| 安全设计 | Modbus setpoint 类型仅读取不写入，避免影响设备 |
| 全量测试 | 所有字段映射项必须有对应测试用例 |
| 边界覆盖 | 必须包含空值/最大值/最小值/异常格式测试 |
| 报告格式 | 测试报告必须包含通过/失败/跳过数量和每项详情 |
| 修复重测 | 失败项修复后必须重测，不跳过 |
| MCP 兼容 | MCP 未就绪时 AI 手动模拟，就绪后调用沙箱执行 |
