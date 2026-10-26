## 1. 模块骨架与版本注册表

- [x] 1.1 在 `mcp_server/archiving/` 下新建 `template_migrator.py`，模块 docstring 说明职责，定义 `SUPPORTED_MIGRATIONS: list[str]`（含当前所有已知版本号，从旧到新排列，最后一项 = `TEMPLATE_VERSION`）并验证列表末项与 `field_contract.TEMPLATE_VERSION` 一致

## 2. 核心迁移算法

- [x] 2.1 实现 `migrate_template(old_bytes: bytes) -> MigrateResult`：打开 old_bytes → 读取 `__template_version` → 判定（no-op / 可迁移 / 拒绝），返回包含 `status`、`from_version`、`to_version`、`migrated_bytes`（可迁移时非空）、`added_sheets` 的结果对象
- [x] 2.2 在 `migrate_template` 中实现迁移路径：调 `_generate_template_bytes()` 取得当前版骨架，以 openpyxl 打开骨架和旧文件，遍历旧文件 sheets 并按设计 D2 的逐表拷贝算法（表头映射、跳过 `__` 元数据行、忽略新骨架不存在的多余旧 sheet）将数据行写入骨架，保存为 `migrated_bytes`
- [x] 2.3 计算 `added_sheets`：骨架 sheet 集合减去旧文件 sheet 集合（排除非数据 sheet 如"说明"），填入结果

## 3. MCP 工具注册

- [x] 3.1 在 `edge_tools.py` 注册 `@mcp.tool() def migrate_device_archive_template(file_id: str) -> dict`：校验 file_id 归属与有效期（复用 read 同款 `template_store.read_template_bytes`），调用 `migrate_template`，将 `migrated_bytes` 存入 `template_store.save()`（新 snapshot_id + 同 owner_id），返回 `{"ok", "new_file_id", "from_version", "to_version", "added_sheets"}` 或错误
- [x] 3.2 处理 no-op 分支（版本已是当前）：直接返回原 `file_id`、`added_sheets=[]`；处理拒绝分支（高于当前）：返回 `ok=false` 并说明原因

## 4. 单元测试

- [x] 4.1 新建 `mcp_server/tests/test_template_migrator.py`：构造一份旧版 fixture（从当前 `_generate_template_bytes()` 取骨架、删掉一张监测点 sheet、把 `__template_version` 改为前一个版本号），调用 `migrate_template`，断言 `status=OK`、`migrated_bytes` 可被 `read_archive_template` 正常解析（`template.ok=true`、无版本错误）、`added_sheets` 包含被删的表名
- [x] 4.2 数据保留测试：fixture 的 `网关·8163` 和 `监测点·XLBA` 有已知数据行，断言迁移后对应 sheet 行数和内容一致
- [x] 4.3 no-op 测试：传入当前版本文件，断言返回 status=ALREADY_CURRENT、不产出新 bytes
- [x] 4.4 拒绝测试：传入高于当前版本的标签（如 "v99-engineer"），断言返回 status=REJECTED、`migrated_bytes` 为 None
- [x] 4.5 多余旧 sheet 忽略测试：fixture 加一张不存在的 sheet（如 "已废弃·旧类型"），断言迁移产物不含该 sheet

## 5. 集成验证与文档

- [x] 5.1 全量 pytest 通过（`cd mcp_server; python -m pytest tests/ -x`），确认新增测试全绿且不影响已有测试
- [x] 5.2 在 `agent_assets/skills/xlpa-device-archiving/SKILL.md` 的工具列表中补充 `migrate_device_archive_template` 说明（用途、参数、返回值、与 read 的前后关系）
- [x] 5.3 `openspec validate --change "server-side-template-migration"` 通过
