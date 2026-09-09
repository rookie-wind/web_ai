---
name: pc
description: >
  协议转换入口技能：接收用户协议转换需求，路由到对应协议专属子技能，
  编排完整的协议分析→字段映射→配置生成→测试验证流程。
  支持 MQTT→MQTT、HTTP→MQTT、Modbus→内部格式 三种转换方向。
when_to_use: >
  用户提到协议转换、格式转换、数据映射、生成转换配置时使用。
  用户提供了源协议文档和目标协议文档需要生成转换配置时使用。
  用户需要将一种协议格式的数据转换为另一种协议格式时使用。
compatibility: "Requires protocol-converter MCP server (待开发)"
metadata:
  tags: [protocol, conversion, entry, router]
  order: 0
  author: hub_port_test
  version: "0.1.0"
---

# 协议转换入口技能

> **目标：** 接收用户的协议转换需求，路由到对应的协议专属子技能，编排完整的转换流程。

## 适用场景

- 用户需要将内部 MQTT 数据转换为平台 MQTT 格式后上报（MQTT→MQTT）
- 用户需要采集第三方 HTTP 接口数据，转换为内部 JSON 格式后通过 MQTT 上报（HTTP→MQTT）
- 用户需要将 Modbus 寄存器数据读取并转换为内部统一格式（Modbus→内部格式）
- 用户提供了源协议文档 + 目标协议文档，需要生成转换配置
- 用户需要测试、打包已生成的协议转换配置

## 整体架构

```mermaid
flowchart TB
    subgraph L1["用户交互层"]
        U["用户输入\n'/pc 将内部 MQTT 数据转换为平台 MQTT 格式'"]
    end

    subgraph L2["SKILL 编排层"]
        ENTRY["pc 入口技能\n路由分发 + 流程编排"]

        subgraph PROTO["协议专属技能"]
            PC2["protocol-conversion\n共享映射核心"]
            MQTT["mqtt-conversion\nMQTT 特有逻辑"]
            HTTP["http-conversion\nHTTP 特有逻辑"]
            MB["modbus-conversion\nModbus 协议转换"]
        end

        subgraph SHARED["共享子技能"]
            TV["test-validation\n测试验证"]
            PD["pack-distribution\n打包分发"]
        end
    end

    subgraph L3["MCP 工具层（待开发）"]
        MCP["MCP Server\n协议管理/配置管理/测试/打包"]
    end

    subgraph L4["输出物"]
        OUT1["转换配置 JSON\n(供 C 引擎读取)"]
        OUT2["测试报告"]
        OUT3["打包 ZIP"]
    end

    U --> ENTRY
    ENTRY --> PROTO
    PROTO --> SHARED
    SHARED -.->|"MCP 就绪后"| MCP
    PROTO --> OUT1
    SHARED --> OUT2
    SHARED --> OUT3
```

## 意图路由表

| 用户意图关键词 | 路由到的子技能 | 说明 |
|---------------|--------------|------|
| MQTT、消息队列、broker、topic、publish/subscribe | `mqtt-conversion` | MQTT→MQTT 协议转换（引用 protocol-conversion 共享规则） |
| HTTP、REST、API、POST/GET、Webhook、接口 | `http-conversion` | HTTP→MQTT 协议转换（引用 protocol-conversion 共享规则） |
| Modbus、寄存器、register、RTU、TCP、功能码 | `modbus-conversion` | Modbus 协议转换 |
| 测试、验证、冒烟测试、检查结果 | `test-validation` | 测试转换配置 |
| 打包、分发、安装、导出、ZIP | `pack-distribution` | 打包分发 |
| 完整流程、端到端、从头到尾 | 全流程编排 | 触发完整 pipeline |

## 执行流程

### 全流程编排

当用户描述完整的转换需求时（如"将内部 MQTT 数据转为平台 MQTT 格式"），触发全流程：

```mermaid
flowchart TD
    START["用户: /pc 将内部 MQTT 数据转为平台 MQTT 格式"]

    R1["pc 识别协议类型 + 意图"]
    R2{"转换方向?"}

    R2 -->|"MQTT→MQTT"| MQ["Phase 1: mqtt-conversion\n分析内部 MQTT 源协议 + 平台 MQTT 目标协议\n生成 JSON 配置（config_loader.c + mapper_core.c）\n引用 protocol-conversion 共享映射规则"]
    R2 -->|"HTTP→MQTT"| HT["Phase 1: http-conversion\n分析第三方 HTTP 源协议 + 内部 MQTT 目标协议\n生成 JSON 配置（vpp_http_config.load.c + mapper_core.c）\n引用 protocol-conversion 共享映射规则"]
    R2 -->|"Modbus→内部格式"| MB["Phase 1: modbus-conversion\n分析 Modbus 协议 + 内部类型定义\n生成 JSON 配置"]

    MQ --> TV["Phase 2: test-validation\n构造测试数据 + 验证配置"]
    HT --> TV
    MB --> TV

    TV --> PD["Phase 3: pack-distribution\n打包配置 + 文档"]
    PD --> END["向用户汇总结果"]

    style MQ fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px
    style HT fill:#e3f2fd,stroke:#1565c0,stroke-width:2px
    style MB fill:#fff3e0,stroke:#e65100,stroke-width:2px
```

### 单步执行

当用户只需要单个步骤时（如"分析这份 MQTT 协议文档"），直接路由到对应子技能：

```mermaid
flowchart LR
    INPUT["用户: /pc 分析这份 Modbus 文档"]
    ROUTE["pc 路由到 modbus-conversion"]
    EXEC["执行单步分析"]
    OUTPUT["输出协议规格 JSON"]

    INPUT --> ROUTE --> EXEC --> OUTPUT
```

## 子技能清单

| 子技能 | 职责 | 输入 | 输出 | 依赖 |
|--------|------|------|------|------|
| `protocol-conversion` | 共享映射核心（路径语法、类型系统、数组遍历、生成器等） | — | 映射规则定义 + mapper_core.c | 无 |
| `mqtt-conversion` | MQTT 特有逻辑（substitute/$idx/$item/嵌套[*]/post_process） | 源 MQTT 文档 + 目标 MQTT 文档 | 转换配置 JSON | protocol-conversion |
| `http-conversion` | HTTP 特有逻辑（context/key_value/"."源路径/preprocess/链式调用） | 源 HTTP 文档 + 目标 MQTT 文档 | 转换配置 JSON | protocol-conversion |
| `modbus-conversion` | Modbus 协议转换配置生成 | Modbus 协议文档 + 内部类型定义 | 转换配置 JSON | 无 |
| `test-validation` | 测试转换配置正确性 | 配置 JSON + 测试数据 | 测试报告 | 协议转换技能 |
| `pack-distribution` | 打包分发转换配置 | 配置 JSON + 测试报告 | ZIP 包 | test-validation |

## Skill 互调关系

```mermaid
flowchart TB
    PC["pc 入口技能\n路由 + 编排"]

    PC -->|"路由"| MQTT["mqtt-conversion\nMQTT特有逻辑"]
    PC -->|"路由"| HTTP["http-conversion\nHTTP特有逻辑"]
    PC -->|"路由"| MB["modbus-conversion"]
    PC -->|"路由"| TV["test-validation"]
    PC -->|"路由"| PD["pack-distribution"]

    MQTT -.->|"引用共享规则"| PC2["protocol-conversion\n共享映射核心"]
    HTTP -.->|"引用共享规则"| PC2

    MQTT -->|"输出: 配置 JSON"| TV
    HTTP -->|"输出: 配置 JSON"| TV
    MB -->|"输出: 配置 JSON"| TV

    TV -->|"输出: 测试报告"| PD
    MQTT -->|"输出: 配置 JSON"| PD
    HTTP -->|"输出: 配置 JSON"| PD
    MB -->|"输出: 配置 JSON"| PD

    style PC fill:#e3f2fd,stroke:#1565c0,stroke-width:2px
    style PC2 fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px
    style MQTT fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px
    style HTTP fill:#e3f2fd,stroke:#1565c0,stroke-width:2px
```

### 数据流详解

```mermaid
sequenceDiagram
    participant U as 用户
    participant PC as pc
    participant MQTT as mqtt-conversion
    participant PC2 as protocol-conversion
    participant MCP as MCP工具
    participant TV as test-validation
    participant PD as pack-distribution

    U->>PC: /pc 将内部 MQTT 数据转为平台 MQTT 格式

    PC->>PC: 识别协议类型 → mqtt-conversion

    Note over PC,MQTT: Phase 1 — 协议分析 + 配置生成

    PC->>MQTT: 路由到 mqtt-conversion
    MQTT-->>PC: 加载技能指南

    MQTT->>MCP: update_reference_file（更新本地参考文件）
    MCP-->>MQTT: 参考文件已更新

    U->>MQTT: [提供平台 MQTT 目标协议文档]
    MQTT->>MQTT: 分析目标协议 → 提取 Topic/消息格式/字段

    Note over MQTT: 源（内部MQTT）从参考文件/默认配置获取
    Note over MQTT,PC2: 引用 protocol-conversion 共享映射规则

    MQTT->>MQTT: 设计字段映射 → 生成 JSON 配置
    MQTT-->>U: 展示转换配置（确认）
    U->>MQTT: 确认

    Note over PC,TV: Phase 2 — 测试验证

    PC->>TV: 路由到 test-validation
    TV->>TV: 构造测试数据 → 模拟转换 → 验证输出
    TV-->>U: 展示测试报告

    Note over PC,PD: Phase 3 — 打包分发

    PC->>PD: 路由到 pack-distribution
    PD->>PD: 打包配置 + 文档 → ZIP
    PD-->>U: 展示打包结果

    TV-->>U: 全流程完成汇总
```

## 安装验证

```
安装检查流程:
  1. 检查 .trae/skills/pc/SKILL.md 是否存在
  2. 验证子技能完整性：
     - protocol-conversion/SKILL.md（共享映射核心）
     - mqtt-conversion/SKILL.md（MQTT特有逻辑）
     - http-conversion/SKILL.md（HTTP特有逻辑）
     - modbus-conversion/SKILL.md
     - test-validation/SKILL.md
     - pack-distribution/SKILL.md
  3. 检查 protocol-conversion/defaults/internal_mqtt_protocol.json 是否存在
  4. （MCP 就绪后）探测 MCP 连接 → update_reference_file
  5. 根据响应判断鉴权状态（参考 HubPort 三场景模式）
```

### MCP 就绪后的鉴权探测

MCP 服务器开发完成后，安装验证流程：

```mermaid
flowchart TD
    START["调用 list_conversion_configs"] --> CHECK{"响应结果?"}

    CHECK -->|"200 OK + 数据"| SPLIT{"mcp.json 中有 Token?"}
    CHECK -->|"401 / 403"| C["场景 C: Token 无效"]

    SPLIT -->|"无 Token"| A["场景 A: 无需鉴权"]
    SPLIT -->|"有 Token"| B["场景 B: Token 有效"]

    A --> DONE_A["✅ 安装完成，无需 Token"]
    B --> DONE_B["✅ 安装完成，Token 认证通过"]
    C --> GUIDE["🔒 引导用户获取 Token"]
```

> ⚠ 场景 C 下，未获取到有效 Token 前不得声称"安装完成"。

## 配置输出说明

所有协议转换技能的最终输出为 **JSON 配置文件**，该文件将被 C 协议转换引擎读取并执行。

```mermaid
flowchart LR
    subgraph 输入
        A1["源协议文档"]
        A2["目标协议文档"]
    end

    subgraph SKILL层
        S1["协议分析"]
        S2["字段映射设计"]
        S3["JSON 配置生成"]
    end

    subgraph 运行时
        C1["C 协议转换引擎\n(读取 JSON 配置)"]
        C2["实际数据转换"]
    end

    A1 --> S1
    A2 --> S1
    S1 --> S2 --> S3
    S3 -->|"config.json"| C1
    C1 --> C2
```

> **C 引擎规则占位：** 当前 JSON 配置格式参考 `protocol-mapper-skill` 的输出规范。
> 待用户提供 C 转换引擎代码后，将根据引擎实际读取的配置字段优化各协议技能的输出格式。

## 约束规则

| 规则 | 说明 |
|------|------|
| 协议识别 | 根据用户描述和文档内容自动识别协议类型（MQTT/HTTP/Modbus） |
| 文档格式 | 源/目标协议文档支持 PDF/DOCX/URL/粘贴文本，非 Markdown 需先转换 |
| 配置格式 | 统一输出 JSON 配置文件，供 C 引擎读取 |
| 用户确认 | 协议分析和字段映射完成后必须经用户确认 |
| 全量提取 | 协议文档中的字段/接口/寄存器必须逐项提取，不得默认压缩 |
| MCP 兼容 | MCP 工具未就绪时，AI 直接输出 JSON，用户手动保存 |

## 后续扩展

当前支持 3 种协议，后续可通过新增协议专属技能扩展：

```
新增协议步骤:
  1. 创建 {protocol}-conversion/ 目录
  2. 编写 SKILL.md（参考现有协议技能结构）
  3. 在 pc 意图路由表添加新协议路由
  4. 创建 agents/openai.yaml
  5. （可选）在 MCP 工具中添加协议专属工具
```
