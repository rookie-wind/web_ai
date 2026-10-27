# 完善档案流程：无模板直连按 IP 查询/删除设备（技能层）

## Context（背景与目标）

现有 `xlpa-device-archiving` 技能是**纯模板驱动**（阶段零~五：生成模板→读模板→dry-run→建档→下发/召测→报告），
需要 Excel 任务模板才能操作边缘设备。

但存在一个真实场景缺口：**新会话、无缓存、无模板**时，用户直接给出目标 IP（10/20 网段）与设备名，
要求查询或删除，例如「帮我删除 20.2.96.2 上的 AI_test4\AI_test5\AI_test6」。

经核对代码，MCP 边缘工具**已具备**支撑该直连流程的全部能力，无需改服务端代码：
- `edge_get_token(ip, username, password, port=7500)` — 无模板独立登录，10.\* 直连、20.\* 自动走门户代理（需服务端已配置 `PORTAL_PROXY_API_URL`）
- `edge_get_device_tree(task_id)` — 返回完整设备树（节点含 `id`/`name`），可供按名解析 deviceId
- `edge_get_device_list(task_id, device_id, recursive=True)` — 单设备档案详情
- `edge_delete_device(task_id, device_id, confirm)` — `confirm=false` 仅返回待删预览（叶子优先），`confirm=true` 才真正递归删除

因此本次目标：**只在技能层补齐「无模板直连查询/删除」流程文档**，把以上编排方式规范化、框定参数与安全边界。
服务端候选优化（编排工具、批量删除、凭据存储、会话持久化、审计报告、树 name 过滤）本次**全部不纳入**（用户已确认）。

### 硬约束
- **禁止影响现有功能**：不修改任何 `mcp_server/` 代码，不改变现有工具行为，只做技能层增量文档。
- **禁止引入新问题**：纯文档增量，不改逻辑、不加依赖。
- **禁止瞎编**：参数、工具签名、编排顺序均以实读代码为准；手机号/验证码明确标为**边缘登录不需要**。

## 已核实的工具契约（据此书写，不臆造）
| 工具 | 签名 | 要点 |
|---|---|---|
| edge_get_token | `(ip, username, password, port=7500)` | `ip.startswith("20.")` → proxy_mode，缺 `PORTAL_PROXY_API_URL` 则返回错误；返回 `task_id` |
| edge_get_device_tree | `(task_id)` | 返回完整树，节点含 `id`(deviceId)、`name`(设备名) |
| edge_get_device_list | `(task_id, device_id, recursive=True)` | recursive=True 走 `getDeviceListByPId` 返回自身+递归后代 |
| edge_delete_device | `(task_id, device_id, confirm=False)` | `confirm=false` 返回 `delete_order` 预览（叶子优先）；未在树中找到则报错，不删除 |

> 说明：边缘登录（`EdgeDeviceClient.login`）请求体只含 `loginName`/`password`/`keyName`/`symmetricKey`，
> **不使用手机号/验证码**。因此直连获取 token 只需 **IP + 账号 + 密码（端口默认 7500）**；手机号/验证码属于云端平台登录（`login` 工具），与此流程无关。

## 需要修改的文件（均为技能层增量）
1. `agent_assets/skills/xlpa-device-archiving/SKILL.md`
   - `when_to_use` 补充直连场景触发条件。
   - 顶部 `description`/编排总述补一句：除模板建档外，支持无模板直连（按 IP 查询/删除既有设备）。
   - 新增独立小节「无模板直连：按 IP 查询/删除设备」（放在「权限与凭据边界」之后、阶段零之前），含：参数清单、编排步骤、安全护栏、指向参考文档。
2. 新建 `agent_assets/skills/xlpa-device-archiving/references/direct-edge-operation.md`
   - 详细 Playbook：参数校验表、Mermaid 流程、查询编排、删除编排（两阶段确认）、边界与失败处理。
   - 在 SKILL.md「参考文档」清单中登记该文件。
3. `agent_assets/skills/package-manifest.json`
   - 在 `requiredFiles` 追加 `skills/xlpa-device-archiving/references/direct-edge-operation.md`（增量、保证资源包完整）。

（基线为纯文档；后续如需走服务端能力，另开会话评估，本次不做。）

## 新增流程内容要点（写入参考文档）
### 参数清单（缺一即向用户索要，绝不凭空捏造）
| 参数 | 必填 | 说明 |
|---|---|---|
| target_ip | ✓ | 如 `20.2.96.2`；20.\* 需服务端已配 `PORTAL_PROXY_API_URL`，10.\* 直连 |
| username | ✓ | 该边缘后端登录账号 |
| password | ✓ | 该边缘后端登录密码 |
| port | 可选 | 默认 7500 |
| device_names | ✓ | 待操作设备名，支持一次多个（分隔符按用户输入，如 `\`、`、`、逗号） |
| action | ✓ | `query` 或 `delete` |
| confirm | 删除时 ✓ | 删除前须二次确认 |

### 查询编排
1. `task_id = edge_get_token(ip, username, password, port)`（参数不足先补齐）
2. `tree = edge_get_device_tree(task_id)`
3. 按 `name` 字段**精确匹配**每个目标名 → 汇总 deviceId（=节点 `id`）、找到/未找到
4. 命中项可选 `edge_get_device_list(task_id, device_id, recursive=True)` 查档案详情
5. 未命中必须如实报告「未找到」，不得臆测已存在

### 删除编排（两阶段，禁止一步到位）
1. 复用查询 1–3，先确认每个名字均已命中
2. 对每个命中 deviceId 调 `edge_delete_device(task_id, device_id, confirm=False)` → 得 `delete_order` 预览（含其递归子设备、叶子优先）
3. 呈现完整预览给用户，明确可逆性
4. 用户明确确认后，`edge_delete_device(task_id, device_id, confirm=True)` 真正删除
5. 逐设备汇总 成功/失败；任一失败即停并报告，不假装全部删除

### 安全护栏（写死到文档，防止误删）
- 登录凭据缺失 → 要求补齐，不臆造账号/密码/端口
- 不使用「参考边缘 XLPA_REFERENCE_EDGE_*」凭据操作现场目标（隔离设计）
- 删除前必须 `confirm=false` 预览 + 用户确认
- 名字未命中 → 如实报告，不得声称已删
- password/token/登录响应一律脱敏

## 验证方式（纯文档改动）
1. `python -c "import json,io; json.load(open('<repo>/agent_assets/skills/package-manifest.json',encoding='utf-8')); print('manifest json ok')"` — 确认 manifest 仍为合法 JSON。
2. 确认新增参考文件与 manifest 中声明的 `requiredFiles` 路径实际存在（`Test-Path` 或 Glob）。
3. 确认本次**未改动** `mcp_server/` 目录任意 `.py`——技能文档不触达服务端逻辑。
4. 可选：重新加载技能包（`pack-distribution`/验证流程）确保资源包可加载；现有 353 项 pytest 不受影响（无服务端代码变更），可跑一次确认零回归。
5. 人工通读「直连操作」小节，核对每条案例与上表工具契约一致，无臆造参数。