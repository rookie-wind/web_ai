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
compatibility: "Requires xl-protocol-agent MCP server"
metadata:
  tags: [test, validation, smoke-test]
  order: 4
  author: hub_port_test
  version: "0.2.0"
---

# 协议转换配置测试验证

> **目标：** 对生成的 JSON 转换配置进行冒烟测试，验证字段映射正确性、数据类型转换、边界条件处理。

> **目录只读约束**：技能目录为只读母本，作业中间产物写
> `<会话工作区>/xlpa-tmp/`，最终产物写 `<会话工作区>/xlpa-output/`
> （或用户指定目录），禁止向技能目录写入任何文件。

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
| JSON 契约 | 检查 prtlType/modelNum/classNum/taskList/labelList | 根字段保留；read 必填，write/convert 可选 |
| 寄存器地址 | 检查 addr_base、addr_exprs 及寄存器跨度 | Hex/Dec 一致；实际起止地址在 0-65535 内，多路偏移有依据 |
| 功能码 | 检查 func_code 及协议来源 | read=3/4，write=6/16；不将平台 functionCode 当作功能码 |
| 数据类型 | 检查 data_type | [UINT16]/[SINT16]/[UINT32]/[SINT32]/[FLOAT]/[UBCD16]/[SBCD16] 或具体位范围，跨度与协议一致 |
| 字节序 | 检查 data_order 及协议依据 | 两字节 AB/BA；四字节 ABCD/DCBA/BADC/CDAB，不设默认值 |
| 位域提取 | 检查 BITS 的实际起止位 | 最终写 [0:3] 等具体范围，不写未指定范围的 [BITS]；保留 [8:15]/[0:7] 和原位号，不误判为不足一个寄存器 |
| BCD 依据 | 检查 SBCD16/UBCD16 的编码说明 | 不臆造符号位置、符号码及异常编码，不按二进制补码解码；不明则待确认 |
| 精度与单位 | 检查源单位、目标单位、协议精度/原公式及其输出单位、单位换算关系、最终 data_exprs、来源、验证样例 | 先解码及还原精度/符号/一次二次侧，再换算到目标单位；不重复缩放或乘 PT/CT |
| 单位门控 | 核对单位未知、冲突、随设备配置变化、不同物理量或复杂关系无公式 | 未确认点位阻断；明确无量纲/枚举不因无物理单位误阻断 |
| 标签依赖 | 检查 data_exprs 的 `$'label_name'` 与 taskList 顺序 | 依赖存在且先采集；保留动态精度和 PQ 整寄存器按位运算，位提取与按位运算互斥 |
| 空表达式 | 检查 addr_exprs/data_exprs | 确认不需转换时填 `""`，不能省略；同单位但仍需协议精度时保留原公式 |
| 写配置与枚举 | 独立检查 write.data_exprs 和 convert 的 org/reg | 不复制读取公式；不可逆、舍入或写语义不明阻断未确认写配置；不自动新增 write，不向设备写入 |

以上单位核对列是分析记录，不新增引擎 JSON 字段；不要求不存在的 `readPlan`、`polling`、`scale` 字段，也不扩展现有采集功能码范围。

MODBUS 最小离线算例（以 `modbus-conversion` 的核心表为准）：
- 字节排列：`0x12 34` 的 AB=`12 34`、BA=`34 12`；`0x12 34 56 78` 的 ABCD=`12 34 56 78`、DCBA=`78 56 34 12`、BADC=`34 12 78 56`、CDAB=`56 78 12 34`。
- 位范围：`0xAB` 的 `[0:3]` 为 11；`0x1234` 的 `[8:15]` 为 18、`[0:7]` 为 52。
- 单位：1500 W→1.5 kW（`$D/1000`）；1.5 kW→1500 W（`$D*1000`）；15000 个 0.1 W→1.5 kW（`$D/10/1000`）；覆盖负值、零值、同单位、已有换算不得重复缩放。
- 阻断：源/目标单位未知或冲突、W 与 kWh 直接换算、无依据复杂公式；单独核对无量纲量及枚举，不将其误判为单位缺失。

MODBUS 验证必须分别报告静态契约检查、离线算例、真实引擎测试、现场测试。当前无实际引擎时仅报告前两类；BCD 符号/异常编码与真实解码、字节序现场兼容性列为未验证。下文占位 MCP 测试工具不是当前可用能力，未实际执行不得宣称引擎或现场通过；不自动迁移存量配置，不为新校验改动无关历史样例。

## 操作流程

### Phase 1 — 配置格式校验

```
用户："测试这份 MQTT 转换配置"
```

**步骤：**

1. 读取 config.json
2. 调用 `validate_config_format(conversion_type, config)` 做结构校验
3. 输出校验报告（ok 与逐条错误：路径 + 原因）
4. 校验失败则先修复，不进入后续执行

### Phase 2 — 构造测试数据

调用 `generate_test_data(conversion_type, config)` 生成 normal/boundary/abnormal
三组测试输入；也可根据源协议规格手工补充测试用例（含 expected 预期输出）。

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

> **执行：** 调用 `execute_conversion_test(conversion_type, config, test_cases)`
> 在沙箱中执行（MQTT→MQTT / HTTP→MQTT）；有 expected 则深度对比，无 expected
> 仅返回实际输出。Modbus 方向不支持沙箱执行，维持静态契约校验 + 离线算例。

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

## 调用的 MCP 工具（已就绪）

| 工具 | 用途 | 说明 |
|------|------|------------|
| `validate_config_format` | 校验配置 JSON 格式和字段完整性 | MQTT/HTTP/Modbus 三契约结构校验 |
| `generate_test_data` | 根据映射结构生成模拟测试数据 | normal/boundary/abnormal 三组 |
| `execute_conversion_test` | 在沙箱中执行转换并返回结果 | MQTT/HTTP 方向，Modbus 不支持 |
| `get_test_report` | 获取测试报告 | 按 test_run_id 查询 |
| `save_conversion_config` | 保存修正后的配置 | 校验通过才存，30 天 TTL |

## 约束规则

| 规则 | 说明 |
|------|------|
| 安全设计 | Modbus 测试不向设备执行写入；可离线核对用户已要求的 write/convert 配置，避免影响设备 |
| 全量测试 | 所有字段映射项必须有对应测试用例 |
| 边界覆盖 | 必须包含空值/最大值/最小值/异常格式测试 |
| 报告格式 | 测试报告必须包含通过/失败/跳过数量和每项详情 |
| 修复重测 | 失败项修复后必须重测，不跳过 |
| MCP 兼容 | 通过 MCP 工具（validate / generate / execute / get_report / save）完成校验、测试与保存 |
