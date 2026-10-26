## Context

当前服务端模板结构由 `archiving/field_contract.py` 的 `SHEET_SPECS` 注册表驱动，
generator 据此产出含全部 sheet（正确表头、数据验证、__template_version 元数据）的
空白模板。reader 按注册表枚举 sheet 并解析数据。版本门采用精确相等校验。

当未来 `SHEET_SPECS` 新增一张类型表（如 `监测点·新风`）时，`TEMPLATE_VERSION` 随之
递增，旧版上传的文件因版本标签不匹配被 reader 拒绝。本设计在 reader 不改的前提下，
提供一条服务端"旧→新"结构桥接。

参见 proposal.md - Why 了解动机，specs 了解需求约束。

## Goals / Non-Goals

**Goals:**
- 服务端确定性地把旧版文件升级为当前版，保留已有数据
- 逻辑集中在一个可独立单测的模块（`template_migrator.py`）
- 不修改 reader、generator 核心或版本门——仅复用它们的输出
- 提供审计字段（from/to version + added_sheets）

**Non-Goals:**
- 不支持"客户端比 server 新"（方向唯一：只有旧→新）
- 不处理旧版有"已废弃 sheet"需要数据搬迁的场景（多余的旧 sheet 直接忽略）
- 不做列级兼容（前提保证：已有 sheet 列布局不变）
- 不自动把旧文件重新走 read/plan（迁移只产出 file_id，后续流程由客户端决定）

## Decisions

### D1：Sheet 级拷贝 vs 模型级重建

**选择：Sheet 级拷贝。**

理由：
- 旧文件的列布局保证不变（用户决策"只新增 sheet，不动现有列"），所以按表名匹配、
  按行逐格拷贝即可，无需通过 reader 解析到 ArchiveTemplate 模型再回写。
- 不依赖 reader（reader 对旧版本会拒绝），无绕过逻辑。
- 保留 Excel 格式细节（合并单元格、数据验证下拉）——只需在 generator 骨架上
  覆盖 data rows。

备选：模型级 = 旧 bytes → 绕过版本门解析 → 从模型调 generator 重建。缺点：
需绕过 reader 版本校验或给 reader 加"不校验版本"模式，增加复杂度且偏离"版本门
不变"的约束。

### D2：迁移算法——以 generator 骨架为基底

```
1. new_bytes = _generate_template_bytes()    # 当前版全骨架
2. 打开 new_bytes (openpyxl)                 → new_wb
3. 打开 old_bytes (openpyxl, data_only)      → old_wb
4. 对 old_wb 每张 sheet：
   a. 跳过系统 sheet 元数据行（__前缀键保留骨架的，不覆盖）
   b. 取 new_wb 中同名 sheet；若不存在（旧多余 sheet），跳过
   c. 按表头行匹配列位置；逐行 copy old → new（从第 2 行起）
5. 保存 new_wb → migrated_bytes
```

`系统连接` 特殊处理：该 sheet 为 key-value 两列布局。迁移时只搬运 **非 `__` 前缀**
的数据行（用户填的连接参数），`__template_version` / `__field_contract_version` 等
元数据键保留骨架（generator）的值。

### D3：版本高低判定

不用字符串大小比较（"v15" < "v16" 不可靠），而用 **已注册版本列表**：

```python
SUPPORTED_MIGRATIONS: list[str] = ["v14-engineer", "v15-engineer"]  # 从旧到新
# 当前 TEMPLATE_VERSION 必须是列表最后一项
```

判定逻辑：
- `file_version == TEMPLATE_VERSION` → no-op
- `file_version in SUPPORTED_MIGRATIONS`（且不是最新） → 可迁移
- 否则（未知或高于列表末项）→ 拒绝

### D4：存储策略

迁移产物通过现有 `template_store.save()` 写入，使用独立的 `snapshot_id`（`new_file_id`），
原文件不受影响。复用 owner_id 绑定。有效期沿用 store 默认过期策略。

### D5：注册为 MCP 工具

在 `edge_tools.py` 中 `@mcp.tool()` 注册 `migrate_device_archive_template`，参数仅
`file_id: str`，返回值遵循项目现有 `{"ok": bool, ...}` 模式。权限与 read 同级（需
有效 session token + 正确 owner）。

## Risks / Trade-offs

- **[风险] generator 骨架 sheet 名或列顺序未来被改动**（虽不在本期范围，但后续若
  重构 sheet 名则本迁移逻辑失效）→ **缓解**：迁移模块只依赖 `SHEET_SPECS`
  注册表的 `sheet_name` + `header` 做匹配，不硬编码表名。
- **[风险] 旧文件 sheet 被用户手动加了自定义列（非契约列）** → **缓解**：拷贝时按
  新骨架的表头列映射取值，多余列不搬（安全丢弃）；reader 本身也把未知列只视为
  warning。
- **[代价] 多一步工具调用**（客户端须先 migrate 再 read）→ 可接受，与"显式可控、
  可审计"的需求一致；后续可考虑 read 内部自动提示"建议先迁移"。
- **[限制] 不处理数据校验（如 IP 格式、必填项为空）** → 由后续 read/plan 负责；
  迁移工具只管结构，不管业务值正确性。
