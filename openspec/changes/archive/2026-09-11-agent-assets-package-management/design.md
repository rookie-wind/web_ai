## Context

当前服务端通过 `mcp_server/server.py` 的 `_create_skills_zip()` 动态压缩 `.trae/skills/` 目录，并通过 `/api/docs/export-skills-package` 提供 ZIP 下载；接入页 `mcp_server/static/access.html` 生成 MCP 配置和 Skills 安装说明；`/pca` 入口 Skill 在 `.trae/skills/pca/SKILL.md` 中描述安装验证、前置检查和更新流程。

现状的分发根仍是 `.trae/skills/`，这对兼容已有接入流程是有利的；问题在于文档和校验语义过度聚焦 `SKILL.md`，没有把同目录下的 `agents/`、`tools/`、模板、校验器、参考资料等视为同一个版本化资源单元。

## Goals / Non-Goals

**Goals:**
- 保持现有 ZIP 下载接口和 `.trae/skills/` 目录结构兼容。
- 将交付概念升级为 Agent 资源包，允许每个 Skill 携带多类型配套资源。
- 使用 manifest 管理必需文件、可选文件、版本和更新校验，后续新增文件类型只需要调整 manifest。
- 让首次接入和后续更新共享同一套“下载资源包 → 解压/覆盖 → manifest 校验 → 重载提示”语义。
- 将 `pca/tools/mcp_client.py` 纳入分发，并作为原生 MCP 调用失败时的备用通道。

**Non-Goals:**
- 不引入新的打包系统、数据库或第三方依赖。
- 不要求安装后自动执行 Python 脚本。
- 不改变 MCP 工具协议、后端业务 API 参数或鉴权 Token 分层模型。
- 不移除现有 `/api/docs/export-skills-package` 和 `/api/docs/export-skills` 端点。

## Decisions

### Decision 1: 继续以 `.trae/skills/` 作为资源包主体

采用现有 `.trae/skills/` 作为 ZIP 的主打包根目录，每个 Skill 的配套资源放在自身目录下，例如：

```text
.trae/skills/pca/
├── SKILL.md
├── agents/openai.yaml
├── tools/mcp_client.py
├── templates/
├── validators/
├── references/
└── manifest.json
```

Rationale:
- 当前服务端已经稳定打包 `.trae/skills/`，改动小且兼容现有用户。
- Skill 与其工具、模板、校验器放在同一目录下，更新边界清晰。
- 后续新增文件类型无需修改服务器目录扫描逻辑，只需要写入 Skill 目录并更新 manifest。

Alternatives considered:
- 新增独立 `.trae/assets/` 根目录：结构更清晰，但会破坏当前只解压 `.trae/skills/` 的用户流程。
- 将工具放在 `mcp_server/`：适合服务端本机使用，但不会随 Skills 包分发到用户侧。

### Decision 2: 引入包级和 Skill 级 manifest

建议使用两层 manifest：

- 包级：`.trae/pca-package-manifest.json` 或打包时内嵌到 ZIP 根部，用于描述整体包版本、资源包名称、所有 Skill、全局必需文件。
- Skill 级：`.trae/skills/<skill>/manifest.json`，用于描述该 Skill 的版本、必需文件、可选文件和入口文件。

推荐字段：

```json
{
  "name": "pca",
  "version": "0.3.0",
  "kind": "skill-assets",
  "required": [
    "SKILL.md",
    "agents/openai.yaml",
    "tools/mcp_client.py"
  ],
  "optional": [
    "templates/",
    "validators/",
    "references/"
  ]
}
```

Rationale:
- 包级 manifest 适合接入页和全量更新展示整体版本。
- Skill 级 manifest 让每个 Skill 自己声明资源边界，便于后续单独扩展。
- manifest 是 JSON，当前项目可用标准库读写，无需新增依赖。

Alternatives considered:
- 只依赖目录扫描：无法区分必需和可选文件，更新后很难给出明确缺失项。
- 只维护包级 manifest：集中管理简单，但每个 Skill 扩展资源时容易形成冲突和大文件维护成本。

### Decision 3: 更新流程采用备份后全量覆盖，再执行 manifest 校验

更新流程保持简单可恢复：

1. 探测 MCP 连接和远端资源包信息。
2. 备份当前 `.trae/skills` 到 `.trae/skills_backup_{timestamp}/`。
3. 下载资源包 ZIP。
4. 解压覆盖 `.trae/skills` 管理范围。
5. 读取包级和 Skill 级 manifest。
6. 校验 manifest 中声明的必需文件。
7. 输出更新结果和重载提示。

Rationale:
- 当前没有复杂包管理器或 lockfile，全量覆盖比增量 patch 更可预测。
- 备份目录提供回滚路径。
- manifest 校验能覆盖 `SKILL.md` 之外的资源文件。

Alternatives considered:
- 增量更新：可减少覆盖范围，但需要版本差异计算、删除文件处理和冲突合并策略，超出当前项目复杂度。
- 只提示用户手工复制：风险低但不可验证，无法保证资源一致性。

### Decision 4: 备用 MCP 客户端随 pca Skill 分发，但不自动运行

`pca/tools/mcp_client.py` 作为 `pca` Skill 的配套工具进入资源包。`/pca` Skill 的调用策略为：

1. 优先使用 IDE 原生 MCP 调用。
2. 如果原生 MCP 调用失败，检查 `pca/tools/mcp_client.py` 是否存在。
3. 存在时可作为备用通道调用 `list_mcp_tools` 或具体 MCP 工具。
4. 不在安装完成后无条件自动执行 Python 脚本。

Rationale:
- 保持用户环境安全，避免安装即执行脚本。
- 解决 IDE MCP 连接未加载或 Token 失效时的可恢复性。
- 用户侧下载资源包后也拥有备用通道，不再依赖服务端本机文件。

Alternatives considered:
- 只保留服务端 `mcp_server/mcp_client.py`：无法解决远程用户侧 fallback。
- 安装后自动运行验证脚本：环境差异大，且可能触发用户对自动执行代码的安全担忧。

## Risks / Trade-offs

- [Risk] manifest 与实际文件列表漂移 → Mitigation: 更新任务中加入 manifest 校验，并在接入页安装说明中要求校验必需文件。
- [Risk] 用户环境没有 Python 或缺少 `mcp` 依赖，备用客户端不可运行 → Mitigation: 将备用客户端定位为 fallback；默认路径仍是 IDE 原生 MCP 调用，并在错误提示中说明依赖要求。
- [Risk] 全量覆盖可能覆盖用户自定义 Skill 修改 → Mitigation: 更新前强制备份 `.trae/skills`，并在更新说明中展示备份路径。
- [Risk] 新旧接入文案混用导致用户以为只需复制 `SKILL.md` → Mitigation: 接入页和 `/pca` Skill 统一使用“Agent 资源包”术语。
- [Risk] 包级 manifest 放在 `.trae/` 时不在当前 ZIP 内 → Mitigation: 实施时要么将包级 manifest 放入 `.trae/skills/package-manifest.json`，要么扩展打包逻辑把 `.trae/pca-package-manifest.json` 写入 ZIP 根部；保持旧端点路径不变。

## Migration Plan

1. 新增资源 manifest 文件和 `pca/tools/mcp_client.py` 到 `.trae/skills/` 管理范围。
2. 扩展或保持 `_create_skills_zip()`，确保 ZIP 包包含 manifest 和工具文件。
3. 更新接入页文案，从 Skills 包安装切换为 Agent 资源包安装，并加入 manifest 校验和备用客户端说明。
4. 更新 `/pca` Skill 的前置检查与更新流程，覆盖 manifest 声明的所有资源。
5. 使用 ZIP 内容检查、manifest 校验和 `list_mcp_tools` 探测验证首次安装与更新流程。

Rollback:
- 如果新资源包流程异常，保留旧 `/api/docs/export-skills-package` 端点和 `.trae/skills` 结构，可从 `.trae/skills_backup_{timestamp}/` 恢复原目录。

## Open Questions

无。