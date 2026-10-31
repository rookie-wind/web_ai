# C1 运维建议（非本变更强制执行项）

> 生成时间：2026-10-28（C1 实施期）

## 1. git 历史中的凭据轮换建议（移交需求方决策）

本变更已通过 `git rm --cached` 停止跟踪 `mcp_server/.env` 与
`mcp_server/.token_registry.json`，但两文件的历史提交仍含真实凭据：

- 历史提交范围：自首次跟踪起至 C1 实施基线（`git log --all --oneline --
  mcp_server/.env mcp_server/.token_registry.json` 可查）；
- 建议动作（按需选择）：
  1. 轮换 `.env` 中的 `MCP_AUTH_TOKEN`（服务端环境变量，重启生效）；
  2. 轮换 `.token_registry.json` 中已签发的接入 Token（现有客户端需
     重新接入，注意 IDE 侧影响面）；
  3. 如需彻底清除历史，需 `git filter-repo` 重写历史并强制推送——
     属破坏性操作，须单独评估与审批，不在本变更范围。
- 风险定级：仓库为内网私有仓库时风险可控；若后续对外共享，必须先完成
  轮换或历史重写。

## 2. 其他已发现待决策项（C1 范围外记录）

- `mcp_server/__pycache__/*.pyc` ×3 仍被 git 跟踪（服务目录，非技能目录）；
- `.qoder/skills/http-conversion/references/~$原子标签定义.docx`（Word 锁
  文件）被 git 跟踪（本地部署副本目录）。
  两者均属本地部署态文件误入版本库，建议在后续变更中一并
  `git rm --cached` 处理；本变更按 spec 范围仅治理 `agent_assets/skills/`
  分发源。

## 3. 4.2/4.3 演练中发现的事项（2026-10-28）

- **cq skill 字段名自相矛盾（文档缺陷）**：
  `modbus-cq-adapt/SKILL.md` 的 frontmatter/输出示例写 `protocolNum`，
  而 Step 2/约束表写 `prtlcode`。演练中按权威输出示例采用 `protocolNum`。
  属技能内容语义问题（非 C1 落位治理范围），建议在 C6（转换执行工具
  改写 SKILL.md）时一并统一，或经批准后在 C1 内做小修复。
- **维大师品牌/型号平台不存在**：`get_brand_list`/`get_model_list` 均
  empty，modelNum 用占位 999；正式同步前需先新增品牌+型号（业务事项，
  非本变更缺陷）。
- **平台 classify id 与本地文档数值不一致**（本地风冷热泵=15，平台=23）：
  以服务端回执为准，属既有语义约定，无需处理。
- 登录验证码错码拒绝（6413 报错）/正码通过（9413，角色 super）：行为正常。
