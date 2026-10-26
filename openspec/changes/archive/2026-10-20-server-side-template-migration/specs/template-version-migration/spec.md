## Purpose

为服务端提供显式的建档模板版本迁移能力：当模板结构因新增设备类型 sheet 而演进后，
允许客户端将旧版本文件提交到服务端，由服务端确定性地升级为当前版本并产出新的文件
引用，消除客户端本地结构处理的差异化风险。

## ADDED Requirements

### Requirement: 迁移工具接受旧版本模板
系统 SHALL 提供一个名为 `migrate_device_archive_template` 的 MCP 工具，接受一个
已上传的模板 `file_id` 作为输入，由服务端判断该模板版本与当前版本的关系，并在版本
落后时产出迁移后的当前版本模板。

#### Scenario: 旧版本文件成功迁移
- **WHEN** 客户端调用 `migrate_device_archive_template(file_id=旧文件ID)`，且该
  文件版本标签低于当前服务端要求的 `TEMPLATE_VERSION`
- **THEN** 系统返回 `ok=true`，附带新的 `file_id`（`new_file_id`），该新文件可被
  `read_device_archive_template` 正常解析且 `template.ok=true`（无版本错误）

#### Scenario: 已是当前版本无需迁移
- **WHEN** 客户端调用迁移工具，且该文件版本标签等于当前 `TEMPLATE_VERSION`
- **THEN** 系统返回 `ok=true`，`new_file_id` 等于原 `file_id`（no-op），
  附带 `from_version` 和 `to_version` 相同、`added_sheets` 为空列表

#### Scenario: 文件版本高于服务端
- **WHEN** 客户端调用迁移工具，且该文件版本标签高于当前 `TEMPLATE_VERSION`
- **THEN** 系统返回 `ok=false`，附带错误信息提示"服务端版本较旧，请升级服务端"，
  不产出新文件

### Requirement: 归属与有效期校验
迁移工具 SHALL 在执行任何操作前验证 `file_id` 的归属身份与有效期，与
`read_device_archive_template` 使用相同的校验逻辑。

#### Scenario: 归属不匹配被拒
- **WHEN** 调用者 Token 派生的 owner_id 与 file_id 存储记录不一致
- **THEN** 系统返回 `ok=false`，错误信息为"模板不可用"类提示，不泄露文件内容

#### Scenario: 文件不存在被拒
- **WHEN** 传入的 `file_id` 在快照存储中不存在
- **THEN** 系统返回 `ok=false`，附带原因

### Requirement: 已有数据完整保留
迁移产出的新文件 SHALL 对旧文件中已存在且当前版本也存在的同名 sheet 保留全部
已填写数据行，不做删减、重排或类型变更。

#### Scenario: 网关与监测点数据行搬入新文件
- **WHEN** 旧文件的 `网关·8163` sheet 有 N 行数据、`监测点·XLBA` 有 M 行数据，
  当前版本仍包含这两张 sheet
- **THEN** 迁移后的新文件中，对应 sheet 包含相同数量且内容一致的数据行

#### Scenario: 旧文件中多余 sheet 被忽略
- **WHEN** 旧文件含有一张在当前版本 sheet 契约中不存在的 sheet（已废弃的旧类型表）
- **THEN** 迁移产出的新文件中不包含该 sheet；旧数据不迁移到当前不存在的表中

### Requirement: 新增 sheet 以空骨架形式补入
迁移产出的新文件 SHALL 包含当前版本模板的全部 sheet（包括旧文件中不存在的
新增类型表），新增 sheet 只有表头行和数据验证规则，无数据行。

#### Scenario: 新增监测点类型表补入
- **WHEN** 当前版本相比旧文件多了一张 `监测点·新风` sheet，旧文件中无此表
- **THEN** 迁移产出的新文件包含 `监测点·新风`，其中只有表头行（设备名称、分路号
  等列定义），零行数据

### Requirement: 版本标签与快照元数据更新
迁移产出的新文件 SHALL 将 `系统连接` sheet 中的 `__template_version` 更新为
当前 `TEMPLATE_VERSION`，并生成新的快照记录（独立 `file_id`），不覆盖原文件。

#### Scenario: 版本标签正确
- **WHEN** 迁移完成
- **THEN** 新文件的 `__template_version` 值等于 `TEMPLATE_VERSION` 常量

#### Scenario: 原文件不被修改
- **WHEN** 迁移完成
- **THEN** 原 `file_id` 指向的文件内容不变（仍为旧版本），`new_file_id` 是独立的
  新存储记录

### Requirement: 迁移结果可审计
迁移工具返回值 SHALL 包含 `from_version`（旧文件版本标签）、`to_version`（目标版本，
即当前 `TEMPLATE_VERSION`）和 `added_sheets`（本次新增补入的 sheet 名列表），供
调用方记录与验证。

#### Scenario: 返回值字段齐全
- **WHEN** 一次迁移成功执行
- **THEN** 返回字典包含 `ok`、`new_file_id`、`from_version`、`to_version`、
  `added_sheets` 五个字段，且 `added_sheets` 为新增 sheet 名称的列表

### Requirement: 纯服务端执行无客户端处理
整个迁移逻辑 MUST 在服务端进程内完成。客户端的职责止于"上传旧文件 + 调用迁移
工具 + 使用返回的 new_file_id 继续流程"，不在客户端执行任何 Excel 结构变更、
sheet 补入或版本标签修改。

#### Scenario: 客户端仅调用工具
- **WHEN** 客户端需要将 v15 文件升级到 v16
- **THEN** 客户端只做：上传(v15 文件) → 调用 migrate(file_id) → 得到 new_file_id
  → 调用 read(new_file_id)；全程无本地文件修改
