## Context

当前项目包含两条相关但尚未打通的资料线：

- `.trae/skills/modbus-conversion/SKILL.md` 已定义现有 MODBUS 协议转换流程：分析协议文档、查找 `modelNum`、查找 `classNum`、匹配原子标签、填充 `labelList`、生成本地 JSON。
- `规约管理MCP服务化Spec.md` 已规划将规约管理后端 API 封装为 MCP 原子工具，工具覆盖大类、设备类型、品牌、型号、规约信息、数据项、脚本等管理能力。

本设计只生成规划工件，不实现代码。后续实现必须优先保证可验证：不能把查询失败当作不存在，不能自动编造参数，不能在用户未确认时执行写入或平台同步。

## Goals / Non-Goals

**Goals:**
- 让 MODBUS Skill 在现有流程中使用规约管理 MCP 原子工具获取参数。
- 明确 MCP 查询、本地 references、用户输入三类参数来源的优先级和展示方式。
- 明确普通用户只读、系统级用户写入前确认的权限交互。
- 明确本地 JSON 生成与平台同步是两个阶段。
- 明确代码生成时需要改哪些文件、加哪些工具、每类工具如何验证。

**Non-Goals:**
- 不实现 HTTP/MQTT 协议转换 Skill 的 MCP 编排。
- 不实现 HTTP/MQTT 的工具白名单或独立权限策略。
- 不把 MODBUS 寄存器完整采集配置写入平台数据项。
- 不让 MODBUS Skill 调用删除类 MCP 工具。
- 不迁移 Vue MCP 接入配置页。

## Decisions

### Decision 1: 保留 MODBUS 现有流程，用 MCP 原子工具替换参数查询来源

MODBUS Skill 的主流程继续使用现有 6 步：

```text
协议文档分析
--> 查找 modelNum
--> 查找 classNum
--> 确定采集数据项 / 原子标签
--> 填充 read/write/convert 配置
--> 生成本地 JSON
```

MCP 工具只负责补齐流程中的平台参数，不负责替代协议文档分析、JSON 结构生成和本地文件保存逻辑。

替代方案：新增 `analyze_modbus_protocol`、`generate_modbus_config` 等高阶工具。拒绝原因：这会把流程编排塞回 MCP 工具内部，违背“原子工具 + Skill 编排”的已确认原则。

### Decision 2: 工具按阶段分组，MODBUS 首期只使用最小集合

建议 MODBUS Skill 使用以下工具集合：

| 阶段 | 工具 | 类型 | 用途 |
|------|------|------|------|
| 探测 | `list_mcp_tools` | 探测 | 获取 MCP 可用工具、权限级别、连接有效性 |
| 登录 | `login` | 登录 | 使用 `phoneNum/code` 获取后端业务 Token |
| 大类 | `get_classify_list` | 只读 | 查询大类，获取 `classNum` 所需的大类编号和 `classifyId` |
| 大类 | `add_classify` | 条件写入 | 查询不到时，由系统级用户确认后新增基础信息 |
| 设备类型 | `get_device_type_list` | 只读 | 查询设备类型，获取 `modelNum=deviceTypeCode` 和 `deviceTypeId` |
| 设备类型 | `add_device_type` | 条件写入 | 查询不到时，由系统级用户确认后新增基础信息 |
| 品牌 | `get_brand_list` | 只读 | 查询品牌，获取 `brandId` |
| 品牌 | `add_brand` | 条件写入 | 查询不到时，由系统级用户确认后新增基础信息 |
| 型号 | `get_model_list` | 只读 | 查询型号，获取 `modelId` |
| 型号 | `add_model` | 条件写入 | 查询不到时，由系统级用户确认后新增基础信息 |
| 数据项 | `get_data_item_list` | 只读 | 查询数据项/原子标签候选 |
| 数据项 | `add_data_item` | 条件写入 | 查询不到时，仅新增基础信息 |
| 规约 | `get_protocol_info_list` | 只读 | 平台同步前检查规约是否已存在 |
| 同步 | `upload_protocol_file` | 平台同步写入 | 用户确认同步平台后上传本地 JSON 或规约文件 |
| 同步 | `add_protocol_info` | 平台同步写入 | 用户确认同步平台后新增规约信息 |
| 同步 | `gen_script` | 平台同步写入 | 用户确认同步平台后触发脚本生成 |

删除类工具不得进入 MODBUS 首期 Skill 调用计划。

### Decision 3: 登录是启动交互，但未登录允许本地流程继续

Skill 启动时询问 `login(phoneNum, code)`。验证码不会过期，用户可以直接提供。

- 用户提供登录信息：调用 `login`，后续可调用需要业务 Token 的查询工具。
- 用户不提供登录信息：明确提示“后续所有参数来源仅使用本地 references 目录”，不调用后端 API 类 MCP 工具。

MCP 接入 Token 与后端业务 Token 分离：

```text
MCP 接入 Token -> 连接 /mcp 的 Authorization: Bearer
后端业务 Token -> login 返回，用于后端 API 的 Token 请求头
```

### Decision 4: 查询结果分三类处理

查询结果必须分为：

```text
命中：使用 MCP 结果作为候选，进入确认表。
为空：允许本地 references 推荐或用户提供。
失败：展示错误，不得当作不存在，不得进入新增流程。
```

失败包括网络错误、Token 错误、权限错误、参数错误、后端业务错误或非成功业务码。

### Decision 5: 所有最终参数必须带来源

最终确认表中的关键参数必须带来源标记：

```text
MCP:<tool_name>.<field>
references:<file_name>
user
```

关键参数包括：

- 品牌
- 设备类型
- `classNum`
- `modelNum`
- 协议类型
- 采集数据项
- 原子标签
- 寄存器地址
- 功能码
- `data_type`
- `data_order`
- `addr_exprs`
- `data_exprs`
- `convert`

### Decision 6: 字段映射采用已确认规则

`classNum`：来源于大类编号。实现时应优先使用 `get_classify_list` 返回结果中能明确表示大类编号的字段；字段名未在现有文档中完全锁定时，必须在实现中保留校验逻辑，字段缺失或为空时回退本地 references 或询问用户。

`modelNum`：来源于设备类型管理的 `deviceTypeCode` 字段。`get_device_type_list` 返回 `deviceTypeCode`，且基础数据 Spec 明确它是类型编码、纯数字字段。

### Decision 7: 写入是用户确认后的条件动作

所有写入都采用同一交互：

```text
发现缺失项
--> 展示缺失项和候选来源
--> 普通用户：停止并提示系统级用户
--> 系统级用户：展示拟写入计划
--> 用户确认写入
--> 调用写入工具
--> 展示返回值
--> 等待用户决定下一步
```

写入失败后不自动重试，不自动补偿，不自动换参数再写。

### Decision 8: 数据项只新增基础信息

首期 `add_data_item` 只用于补充数据项/原子标签基础信息。完整 MODBUS 采集配置仍保存在本地 JSON 中，不通过 `add_data_item` 写入：

- 寄存器地址
- 功能码
- 数据类型
- 字节序
- 地址表达式
- 数据表达式
- 枚举映射

若后续平台数据模型支持完整采集配置，可另开变更扩展。

### Decision 9: 本地 JSON 与平台同步分阶段

默认阶段一只生成本地 JSON。生成前必须展示最终确认表，存在缺失项时不得生成。

阶段二为可选平台同步：用户确认本地 JSON 后，Skill 再询问是否同步平台。未明确确认同步时不得调用平台写入工具。确认同步后仍要展示同步计划，再调用写入工具。

## Implementation Plan

### 1. MCP Server 工具实现

#### 1.1 新增 `mcp_server/api_client.py`

实现异步后端 API 客户端：

```text
ProtocolApiClient
- base_url 从环境变量读取，默认 https://18091.chinadny.com
- 使用 httpx.AsyncClient
- 统一发送 JSON 或文件请求
- 统一设置 headers: Token + Content-Type
- 统一处理 code === 20000、40100、40000、HTTP 错误、网络错误
```

必须提供统一返回结构：

```json
{
  "error": false,
  "code": 20000,
  "message": "成功",
  "data": {},
  "raw": {}
}
```

错误示例：

```json
{
  "error": true,
  "code": "API_ERROR",
  "message": "后端返回的业务错误信息",
  "raw": {}
}
```

#### 1.2 更新 `mcp_server/requirements.txt`

新增：

```text
httpx>=0.27.0
```

#### 1.3 改造 `mcp_server/server.py`

- 保留 `list_mcp_tools`。
- 新增 `login`。
- 按 `规约管理MCP服务化Spec.md` 注册规约管理原子工具。
- 工具定义中标注工具类型：`probe`、`login`、`read`、`write`。
- 写入类工具统一调用权限校验。
- 普通用户调用写入类工具时返回 `FORBIDDEN`。
- 删除类工具可以在 MCP Server 中实现，但 MODBUS Skill 首期不得调用。

写入类判断应覆盖：

```text
add_*
update_*
del_*
save_*
upload_protocol_file
gen_script
```

#### 1.4 查询为空与查询失败的返回约定

只读查询工具应让 Skill 能区分：

```json
{
  "error": false,
  "code": 20000,
  "message": "成功",
  "data": {"rows": []},
  "empty": true,
  "raw": {}
}
```

和：

```json
{
  "error": true,
  "code": "NETWORK_ERROR",
  "message": "网络请求失败: ...",
  "raw": {}
}
```

### 2. MODBUS Skill 文档改造

更新 `.trae/skills/modbus-conversion/SKILL.md`：

#### 2.1 新增启动前置交互

```text
询问用户是否提供 login(phoneNum, code)。
如果提供，调用 login 并使用后端业务 Token 查询平台参数。
如果未提供，声明后续参数来源仅为本地 references。
```

#### 2.2 替换 MCP 工具章节

删除或标记废弃原有高阶工具示例，新增原子工具映射表。

#### 2.3 修改步骤 2：查找 modelNum

新规则：

```text
优先调用 get_device_type_list 查询设备类型。
命中后取 deviceTypeCode 作为 modelNum。
为空时回退 references/空调协议统计汇总.xlsx 或请求用户提供。
失败时展示错误，不得当作不存在。
```

#### 2.4 修改步骤 3：查找 classNum

新规则：

```text
优先调用 get_classify_list 查询大类。
命中后取大类编号作为 classNum。
为空时回退 references/多类型设备集成系统大类号说明.docx 或请求用户提供。
失败时展示错误，不得当作不存在。
```

#### 2.5 修改步骤 4：查询原子标签/数据项

新规则：

```text
优先调用 get_data_item_list 查询数据项。
命中后进入确认表。
为空时回退 references/原子标签定义.docx 或请求用户提供。
系统级用户可在确认基础信息后选择 add_data_item 新增到平台。
普通用户不得新增。
```

#### 2.6 新增最终确认表

生成 JSON 前展示参数确认表。示例字段：

```text
品牌
设备类型
classNum
modelNum
协议类型
采集数据项
原子标签
寄存器地址
功能码
data_type
data_order
addr_exprs
data_exprs
convert
来源
待确认项
```

#### 2.7 新增本地生成后平台同步询问

```text
先生成 output/{品牌}_{设备类型}_{日期}.json。
用户确认文件内容后，询问是否同步平台。
若不同步，流程结束。
若同步，检查系统级权限，展示同步计划并确认后调用平台同步工具。
```

### 3. 平台同步流程

同步平台属于可选阶段，建议流程：

```text
list_mcp_tools 检查权限
--> get_protocol_info_list 检查规约是否存在
--> upload_protocol_file 上传文件
--> add_protocol_info 新增规约信息
--> 可选 gen_script 触发脚本生成
--> 展示每步返回值
```

如果任一步失败，停止并展示返回值，等待用户决定下一步。

### 4. 验证策略

#### 4.1 文档级验证

- MODBUS Skill 中必须存在原子工具映射表。
- MODBUS Skill 中不得再把 5 个高阶工具作为实际 MCP 工具。
- MODBUS Skill 中必须包含登录、Token 隔离、权限、查询结果分类、写入确认、本地生成和平台同步规则。

#### 4.2 工具级验证

使用 `list_mcp_tools` 验证：

- 工具总表包含 MODBUS 首期需要的只读工具。
- 工具总表包含条件写入和平台同步工具。
- 每个工具标注类型。

#### 4.3 行为级验证

至少覆盖以下手动验证场景：

1. 未提供登录信息：只走本地 references 参数来源。
2. MCP 查询命中：最终确认表标注 MCP 来源。
3. MCP 查询为空：回退本地推荐或请求用户提供。
4. MCP 查询失败：展示错误，不进入新增流程。
5. 普通用户遇到写入：停止并提示系统级用户。
6. 系统级用户写入前：展示计划并要求确认。
7. 写入失败：展示返回值，不自动重试。
8. 本地 JSON 生成后：未确认同步时不调用平台写入工具。
9. 删除类工具：MODBUS Skill 计划中不出现删除工具。

## Risks / Trade-offs

- [Risk] 后端 API 返回字段与文档不一致，尤其是大类编号字段名未完全锁定。→ Mitigation：实现时必须校验字段存在；缺失时回退本地 references 或请求用户提供，不允许推断。
- [Risk] `add_data_item` 的后端字段可能超出“基础信息”范围。→ Mitigation：首期只在用户确认基础信息后调用；完整寄存器采集配置保留在本地 JSON。
- [Risk] Skill 无法可靠识别用户权限。→ Mitigation：通过 `list_mcp_tools` 的 `auth.access_level` 探测当前 MCP 接入权限；写入仍由 MCP Server 二次拦截。
- [Risk] 查询失败被误用为查询为空。→ Mitigation：统一 API 返回结构中显式区分 `error` 与 `empty`。
- [Risk] 平台同步造成非预期数据写入。→ Mitigation：同步前必须二次确认；普通用户不能同步；写入失败不自动重试。

## Migration Plan

1. 先实现 MCP Server 原子工具与统一返回结构。
2. 再更新 MODBUS Skill 文档，使其使用原子工具映射表。
3. 先验证只读查询与本地 JSON 生成流程。
4. 再验证系统级写入确认流程。
5. 最后验证可选平台同步流程。

Rollback：若新 MCP 编排不可用，MODBUS Skill 可临时退回纯本地 references 流程；不得保留部分自动写入平台逻辑。

## Open Questions

无阻塞开放问题。实现时若发现后端实际字段与 Spec 不一致，必须以实际接口响应为准更新文档或在实现中显式报错，不得猜测字段含义。
