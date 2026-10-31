## 1. 前置取证（不改任何文件）

- [x] 1.1 以 `PYTHONDONTWRITEBYTECODE=1` 跑既有 pytest 基线并留存输出（基线全绿证据，存 `validation/` 下的 C1 证据目录）→ 基线现状：1 个既有失败 `test_modbus_resource_versions`（期望 0.4.1 vs 磁盘 0.5.0，上轮升版遗留，非本变更引起），证据 `t11_pytest_baseline.txt`
- [x] 1.2 探测 Word 锁文件（已删除成功）
- [x] 1.3 git ls-files 探测（结论：agent_assets 下 __pycache__ 与锁文件均未被跟踪，直接物理删；另发现 mcp_server/__pycache__ 与 .qoder/skills 锁文件被跟踪，记入 ops-notes 待决策）

## 2. SKILL.md 改写

- [x] 2.1 改写 modbus-conversion/SKILL.md 7 处，grep 自检通过（全部为 xlpa-output/ 新约定）
- [x] 2.2 改写 modbus-cq-adapt/SKILL.md 7 处，grep 自检通过
- [x] 2.3 其余 7 个 SKILL.md 插入统一只读约定段（均无目录结构小节，按 design D2 插入文首约束区）
- [x] 2.4 全量 grep 断言通过（18 处匹配全部为 xlpa-output/、xlpa-tmp/ 新约定）+ diff 人工复核（10 文件 50+/20-，与预期一致）

## 3. 分发源治理

- [x] 3.1 残留删除完成（__pycache__ ×2 目录、Word 锁 ×1，均未跟踪直接物理删；git status 对 agent_assets/skills 干净）
- [x] 3.2 git rm --cached 完成，.gitignore 补 mcp_server/.env，三判据验证通过（ls-files 不含、磁盘副本在、status 仅 staged D）
- [x] 3.3 package-manifest 0.24.0→0.25.0；技能级 manifest 核对结论：有独立版本线且被 test_modbus_resource_versions 锁定，不统一改 0.25.0，仅升包级（对 design D6 的实施偏差，已记录）
- [x] 3.4 运维建议已写入 `openspec/changes/skill-workspace-governance/ops-notes.md`（含 git 历史凭据轮换建议与 2 项范围外待决策项）
- [x] 3.5 既有基线失败修复：test_modbus_resource_versions 期望值 0.4.1→0.5.0（同步磁盘/HEAD 事实，上轮升版遗留）

## 4. 回归与验收取证

- [x] 4.1 重跑 pytest 全绿存证：junit 机器读数 **tests=719 failures=0 errors=0 skipped=1**（`t41_junit.xml`、`t41_pytest_after_full.txt`）
- [x] 4.2 真实演练 PASS（2026-10-28 用户执行）：产物落 `xlpa-output/`、cq 同目录，技能目录 62→62 零污染；仓库侧零新增；结果回填 `t42_drill_checklist.md`，原件 `演练结果记录_20261028.md`
- [x] 4.3 IDE 人工回归（2026-10-28 用户执行）：建档（真实 151 节点全流程，证据 `建档执行报告_20261028.md`）✅、转换（含 cq）✅；取模板场景未触发，待补充或豁免（见 t43）；结果回填 `t43_ide_regression.md`
- [x] 4.4 跟进项收口：Word 锁文件已在 1.2 一步删除成功，无遗留
- [x] 4.5 汇报素材归集：证据索引 `validation/c1-skill-workspace-governance/evidence-index.md`（含全部证据文件清单、改动摘要、实施偏差记录）
