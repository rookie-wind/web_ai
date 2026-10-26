## Context

当前实现集中在 `mcp_server/server.py`：`TokenManager` 以 IP 绑定 Token，并通过 localhost / 本机网卡 IP 将访问者提升为 `system`；`AuthMiddleware` 将 `access_level` 写入 contextvars；云端写工具通过 `_check_write_permission()` 判断 `access_level == "system"`。`list_mcp_tools` 中 MCP Server 版本仍硬编码为 `0.1.0`，资源包版本来自 `.trae/skills/package-manifest.json`。

现有 `.trae/skills/pca` 是入口 Skill，`mcp_server/mcp_client.py` 也硬编码转发到 `.trae/skills/pca/tools/mcp_client.py`。当前没有 `EdgeDeviceClient` 或自动建档模块；`api_client.ProtocolApiClient` 仅对接云端规约平台 `:18091`，不应承载边缘 `:7500` RSA 登录和五头签名逻辑。

Path B 已验证边缘建档后端的核心 API：RSA 登录、`modifyDevice`、`updateDeviceParent`、`deleteDevice`、`getDeviceTree`、`getDeviceListByPId`、`setDeviceParam`、`getDeviceOnlineStatus` 和 `callDeviceData`。关键约束包括：网关 `proxyCommType` 必填、`deviceAddress` 必须 12 位、联通类接口存在秒拒/超时/成功三态、下发写审计日志。

## Goals / Non-Goals

**Goals:**
- 将入口从 PCA 一刀切迁移为 XLPA，不保留 `/pca` wrapper。
- 将 MCP 接入 Token 降级为 user-only 接入凭据，云端写权限改由业务登录账号 + 超级账号配置判定。
- 迁移 `.token_registry.json` 到 v2 user-only registry，并提供旧文件备份和损坏回退。
- 将版本信息外置到明确事实源，避免服务端版本硬编码。
- 建立 XLPA 自动建档骨架：Excel 任务模板、边缘客户端、设备 profile、原子 MCP 工具、Skill 编排、dry-run、补偿清理和 XLBA 首期类型。
- 确保资源包更新、产物清理和自动建档流程只删除不可复用临时产物。

**Non-Goals:**
- 不在首期实现虚拟网关或任意设备类型的完整 profile。
- 不把边缘 `:7500` 登录凭据并入云端业务登录或 MCP 接入 Token。
- 不实现自动静默回滚；补偿清理必须由用户确认。
- 不复用 `ProtocolApiClient` 调边缘后端。

## Decisions

### 1. XLPA 改名一刀切

所有入口资源从 `pca` 改为 `xlpa`，包括 Skill 目录、package manifest、备用 MCP 客户端路径、OpenSpec 能力命名、入口文案、接入页/showcase 中用户可见名称。

- Rationale: 当前仍处开发阶段，保留 `/pca` wrapper 会制造双入口和文档漂移。
- Alternative rejected: 保留 `/pca` wrapper 一个版本周期。该方案更兼容，但与用户选择的一刀切策略不一致。

### 2. MCP Token Registry v2 为 user-only

`.token_registry.json` 迁移为 v2 schema，只表示 MCP 接入身份，不再承载 system 权限。迁移时备份旧 registry，有效未撤销 token 均迁移为 user；旧的 localhost/system/admin 字段被忽略或归档为 legacy 元数据。

Suggested shape:

```json
{
  "schema_version": 2,
  "entries": {
    "<source-key>": {
      "token": "metam_pat_...",
      "accessLevel": "user",
      "createdAt": 0,
      "lastSeenAt": 0,
      "revoked": false,
      "legacyMigrated": true
    }
  }
}
```

- Rationale: 兼容现有 access-info/token 体验，同时切断 localhost 自动写权限。
- Alternative rejected: 完全删除 registry。会破坏远程用户重启后 token 复用体验。

### 3. 云端平台写权限由业务账号 + 超级账号配置决定

新增本地超级账号配置（如 `mcp_server/permissions.json` 或环境指定路径），`login(phoneNum, code)` 成功后根据返回账号标识匹配超级账号表。云端只读只需要有效业务 Token；云端写入需要业务 Token + 超级账号命中 + 用户逐项确认。

- Rationale: 将接入鉴权、业务认证、写授权拆开，避免 Token 混用。
- Alternative rejected: 用 MCP `access_level` 控制写权限。旧模型已被明确废弃。

### 4. 边缘建档凭据来自 Excel 任务模板

自动建档 Excel 的任务配置 sheet 持有 `edge_base_url`、`loginName`、`password`、超时和允许下发/召测开关。password 不加密，但工具和报告必须脱敏。

- Rationale: 每个现场 IP 和账号可能不同，任务自包含便于复跑和交接。
- Alternative rejected: 将边缘账号缓存到服务端。会让多现场任务和凭据生命周期更难治理。

### 5. 自动建档采用引擎 + profile 插件

实现 `archiving` 模块，核心对象分为模板解析、计划、执行、补偿和设备 profile。首期 profile：8163 网关、XLBA 电表；虚拟网关仅保留注册扩展位置。

Recommended structure:

```text
mcp_server/
  edge_client.py
  archiving/
    models.py
    converter.py
    excel_reader.py
    engine.py
    compensation.py
    profiles/
      base.py
      registry.py
      gateway_8163.py
      meter_xlba.py
    templates/
      generator.py
```

- Rationale: 新增设备类型时扩展 profile，不改引擎。
- Alternative rejected: 写 XLBA 专用脚本。短期快，但会阻塞二期类型扩展。

### 6. MCP 工具采用原子工具 + Skill 编排

新增工具应覆盖：模板解析、dry-run 计划、设备读取、建档/更新、挂载、删除、参数下发、通讯状态、召测、补偿清理。Skill 负责展示计划、请求确认和分阶段调用。

Candidate tools:
- `convert_comm_address`
- `read_device_archive_template`
- `plan_device_archive`
- `edge_upsert_device`
- `edge_mount_device`
- `edge_get_device_tree`
- `edge_get_device_list`
- `edge_set_device_param`
- `edge_get_online_status`
- `edge_call_device_data`
- `edge_apply_compensation_plan`

- Rationale: 写入与下发有副作用，原子化便于审计、重试和用户确认。
- Alternative rejected: `build_device_archive(excel)` 一键全跑。该方式黑盒且不利于失败恢复。

### 7. 幂等以 deviceId + roadNo 优先

模板保留 `节点键` 支持首跑建树，同时允许用户回填 `deviceId`。复跑时以 `deviceId + roadNo` 作为优先匹配键；首次创建后输出节点键到 deviceId 的映射。

- Rationale: roadNo 是 XLBA 下发 itemBody 的分路身份，deviceId 是后端档案的权威 ID。
- Alternative rejected: 名称/通讯地址作为主要匹配键。现场名称和地址可能变更或重复，稳定性不如 deviceId。

### 8. 补偿清理独立确认执行

执行过程记录补偿清单，至少包含本次新建设备。主流程失败不自动回滚；用户确认后可调用补偿工具按叶子到父节点顺序删除本次新建设备，并回读验证。

- Rationale: 避免失败时误删现场既有设备，同时给用户明确清理能力。
- Alternative rejected: 失败即自动删除本次设备。风险较高，不利于人工排查。

### 9. 版本和资源包事实源分离

服务端版本从服务端配置读取（如 `mcp_server/version.json` 或等价配置），资源包版本继续以 `.trae/skills/package-manifest.json` 为事实源。`list_mcp_tools`、接入页、showcase 和 XLPA 前置检查只展示事实源读取结果。

- Rationale: Server 版本和 Agent 资源包版本生命周期不同。
- Alternative rejected: 单一版本号覆盖两者。会掩盖服务端和资源包不一致。

## Risks / Trade-offs

- [Risk] 一刀切改名会让旧 `/pca` 文档或调用失效 → Mitigation: 实现前全量搜索 `pca` 用户可见引用，并在任务中要求同步更新 `.trae`、`.qoder`、manifest、docs 和 OpenSpec。
- [Risk] user-only registry 迁移可能破坏现有本机写入习惯 → Mitigation: 入口能力矩阵明确提示必须业务登录超级账号；迁移前备份旧 registry。
- [Risk] 超级账号配置标识选择错误会导致误授权或无法授权 → Mitigation: 实现时优先使用 login 返回的稳定 userId；若接口缺失稳定 ID，再退回 phone 并在配置中标注。
- [Risk] Excel password 明文存在输入文件 → Mitigation: 输入文件由用户自管；所有派生产物、日志和工具返回必须脱敏。
- [Risk] `proxyCommType=13` 可能不是所有现场默认 → Mitigation: 不在代码静默写死；模板显式填写或任务默认值显式声明。
- [Risk] 联通类接口在无实表时阻塞 → Mitigation: EdgeDeviceClient 支持 per-call timeout，统一返回 NOT_CONFIGURED / OFFLINE_TIMEOUT / OK。
- [Risk] 补偿清理误删 → Mitigation: 仅允许删除补偿清单中本次新建的 deviceId，并要求用户确认，删除后回读验证。
- [Risk] 单个 change 体量大 → Mitigation: 任务拆成入口/权限、资源包、自动建档、Skill 文档、测试验证多个阶段；不在本规划阶段实现。

## Migration Plan

1. 准备版本与配置文件，添加权限配置和业务 Token 缓存路径；确保敏感运行态文件进入 `.gitignore`。
2. 迁移 TokenManager：启动时读取旧 registry，备份后写入 v2 user-only registry；AuthMiddleware 不再根据 localhost 设置 system。
3. 改造云端写权限检查：从业务登录账号 + 超级账号配置判断，而不是 MCP access_level。
4. 一刀切迁移入口和资源包命名：`pca` Skill、manifest、备用客户端路径、入口文案、showcase/access、OpenSpec 语义改为 XLPA。
5. 新增边缘客户端和自动建档模块；先实现模板解析、转换地址、profile registry 和 dry-run，再实现写入原子工具。
6. 实现补偿清单与确认式清理工具。
7. 更新 MODBUS Skill：在转换完成后可选衔接自动建档 dry-run，云端平台写入按新权限模型判断。
8. 执行单元测试、dry-run 测试、权限矩阵测试、脱敏测试和资源包校验；最后运行 OpenSpec strict validate。

Rollback strategy:
- 代码层面通过正常版本控制回退。
- Token Registry 迁移会生成旧文件备份，可用于诊断或恢复 user token 绑定；恢复后仍不得重新启用 localhost/system 写权限。
- 资源包更新保留备份直到新版 manifest 校验成功且用户确认可用。
- 自动建档执行失败时使用补偿清单按用户确认删除本次新建设备。

## Open Questions

- 超级账号配置最终使用 `phone`、`userId` 还是两者同时支持，取决于 `login(phoneNum, code)` 返回体中稳定字段；实现阶段需要读取并确认当前返回结构。
- XLPA 自动建档模板最终 Excel 样式可在实现阶段根据 profile 生成器微调，但 sheet 语义和必填字段不再改变。
