---
name: modbus-cq-adapt
description: >
  重庆地区 Modbus 脚本适配：将标准 Modbus 转换脚本中的 modelNum 字段
  替换为 protocolNum，并重命名文件。仅针对重庆地区使用。
when_to_use: >
  用户提供了已有的 Modbus JSON 脚本，并提到"重庆"关键字时使用。
  用户需要将 modelNum 替换为 prtlcode 时使用。
  用户提供的 JSON 文件格式与标准 Modbus 转换后的 JSON 格式一致时，询问用户是否要转换为重庆格式。
compatibility: "无外部依赖，纯本地 JSON 处理"
metadata:
  tags: [modbus, chongqing, cq, adapt, protocolNum]
  order: 4
  author: song
  version: "1.0.0"
---

# 重庆地区 Modbus 脚本适配

> **目标：** 将标准 Modbus 转换脚本（modbus-conversion 生成的 JSON）中的 `modelNum` 字段替换为 `prtlcode`，并重命名文件，生成重庆地区专用版本。原文件保留不动。

## 适用场景

- 用户已通过 modbus-conversion 生成标准 Modbus 转换脚本，需要重庆地区版本
- 用户提到"重庆"关键字，且提供了 Modbus JSON 脚本
- 用户提供的 JSON 文件格式与标准 Modbus 配置一致，需确认是否为重庆适配

## 目录结构

```
modbus-cq-adapt/
├── agents/
│   └── openai.yaml       # skill 配置信息
└── SKILL.md
```

> **目录只读与产物落位约束**：技能目录是多会话共享的只读分发母本，
> 禁止向本目录写入任何文件。重庆适配产物等**最终产物**写入
> `<会话工作区>/xlpa-output/`（与源文件同目录，用户显式指定目录时从其指定）。
> 写入技能目录会污染其他会话并使资源包升版失效。

## 输入与输出

### 输入

标准 Modbus 转换脚本 JSON（由 modbus-conversion 生成）：

```json
{
  "prtlType": "MODBUS-RTU",
  "modelNum": 440,
  "classNum": 11,
  "taskList": [{ "labels": ["voltageA", "voltageB"] }],
  "labelList": [{ "name": "voltageA", "read": { ... } }]
}
```

来源：

- 用户提供文件路径
- 用户直接粘贴 JSON 内容
- 上一技能（modbus-conversion）落在会话工作区产物目录（如 `<会话工作区>/xlpa-output/`）的产物

### 输出

重庆地区适配脚本 JSON：

```json
{
  "prtlType": "MODBUS-RTU",
  "protocolNum": 440,
  "classNum": 11,
  "taskList": [{ "labels": ["voltageA", "voltageB"] }],
  "labelList": [{ "name": "voltageA", "read": { ... } }]
}
```

- 文件名：`{原文件名}_cq.json`
- 输出目录：与源文件同目录（默认即 `<会话工作区>/xlpa-output/`，用户显式指定目录时从其指定）
- 原文件保留不动

## 执行流程

### Step 1：读取并验证输入 JSON

1. 读取用户提供的 Modbus JSON 脚本
2. 验证 JSON 格式是否为标准 Modbus 配置：

| 校验项                 | 条件                                 |
| ------------------- | ---------------------------------- |
| 必须包含 `prtlType` 字段  | 值为 `"MODBUS-RTU"` 或 `"MODBUS-TCP"` |
| 必须包含 `modelNum` 字段  | 存在且为整数                             |
| 必须包含 `classNum` 字段  | 存在且为整数                             |
| 必须包含 `taskList` 字段  | 存在且为数组                             |
| 必须包含 `labelList` 字段 | 存在且为数组                             |

3. 校验失败时告知用户具体缺失字段，不继续执行

### Step 2：字段替换

1. 将 `"modelNum"` 字段名替换为 `"prtlcode`
2. 字段值保持不变（不修改值，只改字段名）
3. 其余字段（`prtlType`/`classNum`/`taskList`/`labelList`）原样保留
4. **不修改** labelList 内部任何字段

替换示例：

```
替换前：  "modelNum": 440,
替换后：  "prtlcode": 440,
```

### Step 3：展示 diff 并确认

向用户展示修改前后的差异：

```markdown
## 变更对比

| 修改项 | 修改前 | 修改后 |
|--------|--------|--------|
| 字段名 | modelNum | protocolNum |
| 字段值 | 440 | 440（不变） |
| 文件名 | 美的_水冷机组_20260827100000.json | 美的_水冷机组_20260827100000_cq.json |
| 其余字段 | — | 原样保留 |
```

> 等待用户确认后再写入文件。

### Step 4：保存输出

1. 读取原文件名（不含路径和 `.json` 扩展名）
2. 生成新文件名：`{原文件名}_cq.json`
3. 将修改后的 JSON 写入与源文件同目录（默认即 `<会话工作区>/xlpa-output/`）：`{源文件所在目录}/{原文件名}_cq.json`
4. 原文件保留不动
5. 告知用户输出路径

## 智能识别规则

当用户提供的 JSON 文件格式与标准 Modbus 转换后的 JSON 格式一致（含 `prtlType` + `modelNum` + `classNum` + `taskList` + `labelList`），但**未明确提到"重庆"**时：

1. AI 识别到输入是标准 Modbus 配置
2. 向用户询问：

> 检测到您提供的文件是标准 Modbus 转换脚本（含 `modelNum` 字段）。
> 
> 请问您是否需要将其转换为重庆地区格式（`modelNum` → `prtlcode`）？
> 
> - **是** — 执行重庆适配
> - **否** — 不做处理

3. 用户确认"是"后，按正常流程执行
4. 用户确认"否"后，终止操作

## 约束规则

| 规则     | 说明                                 |
| ------ | ---------------------------------- |
| 仅替换字段名 | 只将 `modelNum` 改为 `prtlcode`，不修改值   |
| 原文件保留  | 原文件不动，新文件写入源文件同目录（会话工作区产物目录） |
| 文件命名   | `{原文件名}_cq.json`                   |
| 必须确认   | 写入前必须展示 diff 给用户确认                 |
| 格式校验   | 输入必须包含 5 个必填字段，否则拒绝执行              |
| 无依赖    | 不依赖 protocol-conversion，不调用 MCP 工具 |
| 纯本地操作  | 所有处理在本地完成，不涉及网络请求                  |

## 与其他 Skill 的关系

| Skill                 | 关系                                                   |
| --------------------- | ---------------------------------------------------- |
| `modbus-conversion`   | 前置：modbus-conversion 生成标准脚本 → modbus-cq-adapt 适配重庆格式 |
| `xlpa`                 | 入口：xlpa 路由到 modbus-cq-adapt                           |
| `protocol-conversion` | 无依赖关系                                                |
| `test-validation`     | 无依赖关系（重庆适配不改变配置语义，无需重新测试）                            |

## 典型用例

### 用例 1：用户明确提到重庆

```
用户：/xlpa 帮我把这个 Modbus 脚本转成重庆格式，文件在 <会话工作区>/xlpa-output/美的_水冷机组_20260827100000.json

→ xlpa 识别"重庆"关键词 → 路由到 modbus-cq-adapt
→ Step 1: 读取并验证 JSON ✅
→ Step 2: modelNum → prtlcode
→ Step 3: 展示 diff → 用户确认
→ Step 4: 保存到 <会话工作区>/xlpa-output/美的_水冷机组_20260827100000_cq.json
```

### 用例 2：用户未提到重庆但提供了标准格式

```
用户：/xlpa 帮我处理这个 JSON 文件

→ xlpa 路由到 modbus-cq-adapt（检测到标准 Modbus 格式）
→ AI 询问：检测到标准 Modbus 脚本，是否需要转换为重庆格式？
→ 用户：是
→ 正常执行 Step 1-4
```
