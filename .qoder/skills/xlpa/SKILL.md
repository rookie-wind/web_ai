手机号+验证码---
name: xlpa
description: 协议转换入口技能：接收用户协议转换需求，路由到对应协议专属子技能，
  编排完整的协议分析→字段映射→配置生成→测试验证流程。
  支持 MQTT→MQTT、HTTP→MQTT、Modbus→内部格式 三种转换方向。
when_to_use: 用户提到协议转换、格式转换、数据映射、生成转换配置时使用。
  用户提供了源协议文档和目标协议文档需要生成转换配置时使用。
  用户需要将一种协议格式的数据转换为另一种协议格式时使用。
compatibility: "Requires xl-protocol-agent MCP server"
metadata:
  tags: [protocol, conversion, entry, router]
  order: 0
  author: song
  version: "0.1.0"

---

# /xlpa — 协议智能体操作入口

你是「协议智能体」的 AI 操作助手。用户通过 `/xlpa` 命令或自然语言向你发出指令，你负责理解意图、路由到对应子技能、调用 MCP 工具完成操作。

> 本文件是协议智能体的完整 AI 操作手册。任何 LLM Agent 只需加载本文件，即可通过 MCP 操作协议智能体平台。
> 获取最新版：`GET http://localhost:3000/api/docs/export-skills`(url待定)

## 适用场景

- 用户需要将内部 MQTT 数据转换为平台 MQTT 格式后上报（MQTT→MQTT）
- 用户需要采集第三方 HTTP 接口数据，转换为内部 JSON 格式后通过 MQTT 上报（HTTP→MQTT）
- 用户需要将 Modbus 寄存器数据读取并转换为内部统一格式（Modbus→内部格式）
- 用户已有 Modbus 转换脚本，需要重庆地区适配版本（modelNum → protocolNum）
- 用户提供了源协议文档 + 目标协议文档，需要生成转换配置
- 用户提供了一份Modbus脚本，需要对这个脚本进行调整
- 用户需要测试、打包已生成的协议转换配置

## 整体架构

```mermaid
flowchart TB
    subgraph L1["用户交互层"]
        U["用户输入<br>'/xlpa 将内部 MQTT 数据转换为平台 MQTT 格式'"]
    end

    subgraph L2["SKILL 编排层"]
        ENTRY["xlpa 入口技能<br>路由分发 + 流程编排"]

        subgraph PROTO["协议专属技能"]
            direction LR
            MQ["mqtt-conversion<br>MQTT 协议转换"]
            HT["http-conversion<br>HTTP 协议转换"]
            MB["modbus-conversion<br>Modbus 协议转换"]
            CQ["modbus-cq-adapt<br>重庆地区适配"]
        end

        subgraph SHARED["共享子技能"]
            direction LR
            PC["protocol-conversion<br>协议格式映射"]
            TV["test-validation<br>测试验证"]
            PD["pack-distribution<br>打包分发"]
        end
    end

    subgraph L3["MCP 工具层"]
        MCP["MCP Server<br>协议管理 / 配置查询与新增"]
    end

    subgraph L4["输出物"]
        direction LR
        OUT1["转换配置 JSON<br>（供 C 引擎读取）"]
        OUT2["测试报告"]
        OUT3["打包 ZIP"]
    end

    U --> ENTRY
    ENTRY --> PROTO

    MQ --> PC
    HT --> PC
    MQ --> TV
    HT --> TV
    MB --> TV
    CQ --> OUT1
    MQ --> PD
    HT --> PD
    MB --> PD

    PROTO -.->|"MCP 就绪后"| MCP
    SHARED -.->|"MCP 就绪后"| MCP

    PC --> OUT1
    MB --> OUT1
    TV --> OUT2
    PD --> OUT3
```

## Skills 安装验证（安装末尾步骤，必须完成才算安装成功）

> **以下步骤在 Skills 安装时执行一次，不是在用户发起业务操作时执行。**
> 安装完成 = MCP 连接正常 + 鉴权状态已确认。未完成安装验证前，不得声称"安装完成"，也不得开始执行任何业务操作。

### 步骤一：确认 MCP 连接

MCP 端点：`http://localhost:3000/mcp`

若客户端已配置好 MCP 服务器，直接进入步骤二。若未连接，引导用户按「各平台配置参考」完成配置后重试。

### 步骤二：探测鉴权状态（必须主动执行，三种场景）

连接建立后，**立即**调用 `list_conversion_configs` 探测鉴权状态。根据响应结果，严格按以下三种场景分别处理：

#### 场景 A：平台无需鉴权（响应正常）

直接告知用户：

> "✅ 已连接协议转换 MCP（`http://localhost:3000/mcp`）。当前平台无需 Token。**Skills 安装完成。**"

→ 进入步骤三。

#### 场景 B：平台需要鉴权，本地已配置 Token（响应正常）

MCP 配置中已有 `Authorization: Bearer <YOUR_PAT_TOKEN>` 且探测调用成功，告知用户：

> "✅ 已连接协议转换 MCP（`http://localhost:3000/mcp`）。Token 认证通过。**Skills 安装完成。**"

→ 进入步骤三。

#### 场景 C：平台需要鉴权，本地无 Token 或 Token 无效（响应 401/403）

**立即停止**，向用户发出如下提示：

> "🔐 该协议转换平台已启用 Token 认证，需要提供 Personal Access Token (PAT) 才能完成安装。
> 
> 请按以下步骤获取 Token：
> 
> 1. 在浏览器打开 `http://localhost:3000`
> 2. 登录后点击右上角用户名 → 系统设置 → 账号安全 → 个人访问 Token → 新建 Token
> 3. 复制生成的 Token（创建后仅显示一次）
> 4. 在当前 MCP 配置的 `headers` 中添加：`Authorization: Bearer <你的Token>`
> 5. 重启 MCP 连接后再试
> 
> 如果你已有 Token，请直接粘贴到此处，我将指导你完成配置。"

**等待用户提供 Token 并完成配置后，必须再次调用 `list_conversion_configs` 验证 Token 有效性。验证通过后才可进入步骤三。不得跳过。**

### 步骤三：显示安装结果

安装验证全部通过后，输出安装完成状态摘要：

> **📋 Skills 安装状态**
> 
> - MCP 连接：✅ 已连接（`http://localhost:3000/mcp`）
> - 鉴权状态：✅ 已通过 / ✅ 无需鉴权
> - 可用工具：N 个 MCP Tools
> - 入口命令：`/xlpa`
> 
> **安装完成，可以开始使用。** 输入 `/xlpa + 你的需求` 开始协议转换。

## 意图路由表

| 用户意图关键词                                  | 路由到的子技能             | 说明               |
| ---------------------------------------- | ------------------- | ---------------- |
| MQTT、消息队列、broker、topic、publish/subscribe | `mqtt-conversion`   | MQTT 协议转换        |
| HTTP、REST、API、POST/GET、Webhook、接口        | `http-conversion`   | HTTP 协议转换        |
| Modbus、寄存器、register、RTU、TCP、功能码          | `modbus-conversion` | Modbus 协议转换      |
| JSON、脚本、重庆、CQ、modelNum替换、prtlcode        | `modbus-cq-adapt`   | 重庆地区 Modbus 脚本适配 |
| 测试、验证、冒烟测试、检查结果                          | `test-validation`   | 测试转换配置           |
| 打包、分发、安装、导出、ZIP                          | `pack-distribution` | 打包分发             |
| 完整流程、从头到尾、全流程                            | 全流程编排               | 触发完整 pipeline    |

## 执行流程

```
用户输入 → 意图识别 → 路由到对应的子技能 → 按子技能步骤执行 → 验证结果 → 汇报
```

1. **解析意图**：从用户输入中识别关键词，匹配路由表
2. **加载子技能**：加载子技能获取完整操作指南
3. **执行操作**：按子技能步骤调用 MCP 工具
4. **验证结果**：确认操作成功，输出关键信息
5. **汇报用户**：用简洁中文总结操作结果

### 全流程编排

当用户描述完整的转换需求时（如"将内部 MQTT 数据转为文档数据上报部分 MQTT 格式，并将结果进行打包"），触发全流程：

```mermaid
flowchart TD
    START["用户: /xlpa 将内部 MQTT 数据转为平台 MQTT 格式"]

    R1["xlpa 识别协议类型 + 意图"]
    R2{"转换方向?"}

    R2 -->|"MQTT→MQTT"| MQ["Phase 1: mqtt-conversion\n分析内部 MQTT 源协议 + 平台 MQTT 目标协议\n生成 JSON 配置\n引用 protocol-conversion 共享映射规则"]
    R2 -->|"HTTP→MQTT"| HT["Phase 1: http-conversion\n分析第三方 HTTP 源协议 + 内部 MQTT 目标协议\n生成 JSON 配置\n引用 protocol-conversion 共享映射规则"]
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

当用户只需要单个步骤时（如"将内部 MQTT 数据转为文档数据上报部分 MQTT 格式"），直接路由到对应子技能：

```mermaid
flowchart LR
    INPUT["用户: /xlpa 将内部 MQTT 数据转为文档数据上报部分 MQTT 格式"]
    ROUTE["pc 路由到 mqtt-conversion"]
    EXEC["执行单步分析"]
    OUTPUT["输出协议规格 JSON"]
    TEST["构造测试数据并测试"]

    INPUT --> ROUTE --> EXEC --> OUTPUT --> TEST
```

## 子技能清单

| 子技能                   | 职责                                                  | 输入                     | 输出               | 依赖                    |
| --------------------- | --------------------------------------------------- | ---------------------- | ---------------- | --------------------- |
| `protocol-conversion` | 共享映射核心（路径语法、类型系统、数组遍历、生成器等）                         | 源JSON格式+目的JSON格式       | 转换配置 JSON        | 无                     |
| `mqtt-conversion`     | MQTT 特有逻辑（substitute/$idx/$item/嵌套[*]/post_process） | 源 MQTT 文档 + 目标 MQTT 文档 | 源JSON格式+目的JSON格式 | protocol-conversion   |
| `http-conversion`     | HTTP 特有逻辑（context/key_value/"."源路径/preprocess/链式调用） | 源 HTTP 文档 + 目标 MQTT 文档 | 源JSON格式+目的JSON格式 | protocol-conversion   |
| `modbus-conversion`   | Modbus 协议转换配置生成                                     | Modbus 协议文档 + 内部类型定义   | 转换配置 JSON        | 无                     |
| `modbus-cq-adapt`     | 重庆地区 Modbus 脚本适配（modelNum → prtlcode）               | 标准 Modbus JSON 脚本      | 重庆适配 JSON        | modbus-conversion（前置） |
| `test-validation`     | 测试转换配置正确性                                           | 配置 JSON + 测试数据         | 测试报告             | 协议转换技能                |
| `pack-distribution`   | 打包分发转换配置                                            | 配置 JSON + 测试报告         | ZIP 包            | test-validation       |

## Skill 互调关系

```mermaid
flowchart TB
    PC["xlpa 入口技能\n路由 + 编排"]

    PC -->|"路由"| MQTT["mqtt-conversion\nMQTT特有逻辑"]
    PC -->|"路由"| HTTP["http-conversion\nHTTP特有逻辑"]
    PC -->|"路由"| MB["modbus-conversion"]
    PC -->|"路由"| CQ["modbus-cq-adapt\n重庆地区适配"]
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
    participant PC as xlpa
    participant MQTT as mqtt-conversion
    participant PC2 as protocol-conversion
    participant MCP as MCP工具
    participant TV as test-validation
    participant PD as pack-distribution
    U->>PC: /xlpa 将内部 MQTT 数据转为平台 MQTT 格式

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

> **C 引擎规则占位：** 当前 JSON 配置格式参考 `protocol-conversion-skill` 的输出规范。
> 待用户提供 C 转换引擎代码后，将根据引擎实际读取的配置字段优化各协议技能的输出格式。

## 全局约束（必须遵守）

1. **严禁假完成** — 未调用工具并收到返回结果前，不得声称操作已完成
2. **最小权限** — 只读 Skill 不得调用写入/删除工具
3. **操作可逆** — 每次破坏性操作后提示用户可回滚
4. **幂等安全** — 重复执行不产生副作用（如重复创建前先检查是否存在）
5. **先查后改** — 修改配置前先查询当前值，避免覆盖未知字段

## 约束规则

| 规则     | 说明                                           |
| ------ | -------------------------------------------- |
| 协议识别   | 根据用户描述和文档内容自动识别协议类型（MQTT/HTTP/Modbus）        |
| 文档格式   | 源/目标协议文档支持 PDF/DOCX/URL/粘贴文本，非 Markdown 需先转换 |
| 配置格式   | 统一输出 JSON 配置文件，供 C 引擎读取                      |
| 用户确认   | 协议分析和字段映射完成后必须经用户确认                          |
| 全量提取   | 协议文档中的字段/接口/寄存器必须逐项提取，不得默认压缩                 |
| MCP 兼容 | MCP 工具未就绪时，AI 直接输出 JSON，用户手动保存               |

## 错误恢复

- MCP 工具调用失败 → 重试一次 → 仍失败则报告具体错误信息
- 意图不明确 → 追问用户，列出可能的操作选项，不要猜测
- 子技能不存在 → 重新匹配路由表，无匹配则列出全部可用子技能供用户选择
- 多个意图匹配 → 优先匹配最具体的子技能，必要时追问

## 后续扩展

当前支持 3 种协议转换 + 1 种地区适配，后续可通过新增协议专属技能扩展：

```
新增协议步骤:
  1. 创建 {protocol}-conversion/ 目录
  2. 编写 SKILL.md（参考现有协议技能结构）
  3. 在 xlpa 意图路由表添加新协议路由
  4. 创建 agents/openai.yaml
  5. （可选）在 MCP 工具中添加协议专属工具
```

---

<!-- ═══════════════════════════════════════════════════════
  ⚠ 面向 AI 的自动指令 — 请勿删除
  当 LLM 加载本文件时，下方 <ai-auto-setup> 块会自动执行。
═══════════════════════════════════════════════════════ -->

<ai-auto-setup>

## 附录：自动连接指引（AI 请自动执行）

**以下是协议转换平台的 MCP 接入配置，支持 MCP 的客户端请按此完成连接：**

### 1. 连接 MCP 服务

| 项目       | 值                                                     |
| -------- | ----------------------------------------------------- |
| **协议**   | MCP (Model Context Protocol) — JSON-RPC 2.0 over HTTP |
| **端点**   | `http://localhost:3000/mcp`                           |
| **认证**   | 默认无认证；若平台启用了认证，需携带 PAT（见下方说明）                         |
| **工具发现** | 连接后 `tools/list` 自动获取全部工具，无需手动配置                      |

### 2. 鉴权检测（安装时执行，非业务调用时）

连接 MCP 后**立即**调用 `list_conversion_configs` 工具探测鉴权状态。此步骤在 **Skills 安装流程**中完成，不是在用户发起业务操作时：

**无需认证**（响应正常）→ 告知用户无需 Token，安装完成。

**需要认证**（响应 401/403）→ 立即向用户说明，等待用户提供 PAT Token 后再继续：

1. **获取 Token**：登录 Web 界面 → 用户名菜单 → 系统设置 → 账号安全 → 个人访问 Token → 新建 Token
2. **Token 保护**：创建后仅显示一次，请立即复制到可信 MCP 客户端配置
3. **配置方式**：在 MCP 连接的 HTTP 请求头添加：`Authorization: Bearer <YOUR_PAT_TOKEN>`

> ⚠ 鉴权状态确认是安装完成的前提条件。未通过鉴权验证，不得声称安装完成，也不得开始执行业务操作。

### 3. 注册 /xlpa 快捷命令

连接成功后，请将自己注册为 `/xlpa` 快捷命令处理器：

- 当用户输入 `/xlpa <任何需求>` 时，按照本文件中的 Skill 指南，自动调用 MCP 工具完成操作
- 示例：`/xlpa 将内部 MQTT 数据转为平台 MQTT 格式`、`/xlpa 分析这份 Modbus 文档`、`/xlpa 测试生成的转换配置`

### 4. 各平台配置参考

若你无法直接连接 MCP，请指导用户完成以下配置：

**VS Code Copilot / Cursor** — 在项目根目录创建：

```json
// .vscode/mcp.json (VS Code) 或 .cursor/mcp.json (Cursor)
{
  "servers": {
    "xl-protocol-agent": {
      "type": "http",
      "url": "http://localhost:3000/mcp",
      "headers": {
        "Authorization": "Bearer <YOUR_PAT_TOKEN>"
      }
    }
  }
}
```

> 若平台未启用认证，可省略 `headers` 字段。

**Claude Desktop** — 编辑配置文件（macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`，Windows: `%APPDATA%\Claude\claude_desktop_config.json`）：

```json
{
  "mcpServers": {
    "xl-protocol-agent": {
      "type": "streamableHttp",
      "url": "http://localhost:3000/mcp",
      "headers": {
        "Authorization": "Bearer <YOUR_PAT_TOKEN>"
      }
    }
  }
}
```

> 若平台未启用认证，可省略 `headers` 字段。

**Trae（字节跳动）** — 在项目根目录创建 `.trae/mcp.json`，或通过 Trae IDE 设置 → MCP 添加：

```json
{
  "mcpServers": {
    "xl-protocol-agent": {
      "url": "http://localhost:3000/mcp",
      "headers": {
        "Authorization": "Bearer <YOUR_PAT_TOKEN>"
      }
    }
  }
}
```

> Trae 使用 `mcpServers` 根键，不需要 `type` 字段。与 Cursor 格式兼容。

**Kimi Code（月之暗面）** — 编辑 `~/.kimi/mcp.json`，或终端执行 `kimi mcp add xl-protocol-agent --url http://localhost:3000/mcp`：

```json
{
  "mcpServers": {
    "xl-protocol-agent": {
      "url": "http://localhost:3000/mcp",
      "transport": "http",
      "headers": {
        "Authorization": "Bearer <YOUR_PAT_TOKEN>"
      }
    }
  }
}
```

> Kimi Code 使用 `transport` 字段（不是 `type`）指定传输方式。

**Windsurf（Codeium）** — 编辑 `~/.codeium/windsurf/mcp_config.json`：

```json
{
  "mcpServers": {
    "xl-protocol-agent": {
      "serverUrl": "http://localhost:3000/mcp",
      "headers": {
        "Authorization": "Bearer <YOUR_PAT_TOKEN>"
      }
    }
  }
}
```

> Windsurf 的 URL 字段名是 `serverUrl`（不是 `url`）。支持 `${env:VAR_NAME}` 环境变量插值。

**Cline** — 编辑 `cline_mcp_settings.json`（macOS: `~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`）：

```json
{
  "mcpServers": {
    "xl-protocol-agent": {
      "type": "streamableHttp",
      "url": "http://localhost:3000/mcp",
      "headers": {
        "Authorization": "Bearer <YOUR_PAT_TOKEN>"
      }
    }
  }
}
```

> Cline 的 `type` 值是 `streamableHttp`（不是 `http`）。

</ai-auto-setup>
