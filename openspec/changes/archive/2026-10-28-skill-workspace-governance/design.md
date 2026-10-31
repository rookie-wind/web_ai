## Context

见 proposal.md（Why）。当前可实测的状态：

- `output/` 仅为 SKILL.md 文字引用（`modbus-conversion` 7 处：目录树
  L42-44、中间产物约束注 L47-50、mermaid 流程 L137、步骤 6 L325、
  平台同步 L603、约束表 L1011；`modbus-cq-adapt` 7 处：目录树 L34-35、
  输入来源 L59、输出目录 L76、Step 4 L131、约束表 L157、用例 L178/L184），
  物理目录不存在；
- `modbus-conversion` 已有"中间产物落 `<会话工作区>/xlpa-tmp/`"约束
  （L47-50），本设计将最终产物纳入同一体系的统一约定；
- 技能目录残留：`__pycache__/` ×3（`protocol-conversion/scripts/`、
  `xlpa/tools/`）、Word 锁文件 `~$原子标签定义.docx` ×1
  （`http-conversion/references/`）；
- `git ls-files` 确认 `mcp_server/.env` 与 `.token_registry.json` 被
  跟踪；`.gitignore` 缺 `mcp_server/.env` 条目（其余已有）。

## Goals / Non-Goals

**Goals:**

- 14 处 `output/` 引用全部改写为会话工作区落位，跨技能交接路径明确；
- 9 个 SKILL.md 统一携带"目录只读"约定段；
- 分发源残留清零、凭据文件退出版本跟踪、资源包升版 0.25.0。

**Non-Goals:**

- 不迁移 `scripts/`（`protocol_converter.py`、`mapper_core.c` 等留在
  技能目录，属只读母本内容；其执行能力由 C6 变更转为服务端工具）；
- 不实现写入拦截 Hook（属 C4 路径白名单范围）；
- 不清理 `validation/quarantine/` 隔离区（上轮已处理，保持可回滚）；
- 不做仓库历史中的凭据轮换（列为运维建议，见 Risks）。

## Decisions

### D1 落位路径约定：工作区下两个固定子目录

```
<会话工作区>/
├── xlpa-tmp/      # 中间产物（PDF 逐页文本、页面图、临时 Markdown）——沿用既有约定
└── xlpa-output/   # 最终产物（转换配置 JSON、测试报告、_cq.json 等）
```

- 用户显式指定目录时优先用户指定，否则用 `<会话工作区>/xlpa-output/`；
- 命名规则不变（`{品牌}_{设备类型}_{YYYYMMDDHHMMSS}.json`、
  `{原文件名}_cq.json`）；
- cq 适配产物落**源文件同目录**（用户从哪读就写回哪），默认即
  `xlpa-output/`——交接语义从"modbus 的 output/ 目录"改为"上一技能的
  产物所在目录（会话工作区）"。

*理由*：沿用既有 `xlpa-tmp/` 心智模型扩一个 `xlpa-output/`，IDE 与 Web
两种会话可套同一约定（Web 会话工作区由 C3 定义，本变更只约定相对结构）。
*替代方案*（否决）：产物直接落工作区根目录——多技能产物混在工作区根部，
用户难以辨认归属，也不利于 C5 的产物发现与保留期分类。

### D2 统一只读约定段：一句话模板插入各 SKILL.md

9 个 SKILL.md 的"目录结构"小节（无该小节的放文首约束区）统一插入：

> 技能目录为只读母本：作业中间产物写 `<会话工作区>/xlpa-tmp/`，
> 最终产物写 `<会话工作区>/xlpa-output/`（或用户指定目录），
> 禁止向技能目录写入任何文件。

`modbus-conversion` 已有的 L47-50 约束块随之改写（删除"暂仍沿用"注，
`output/` 目录树条目移除）。

### D3 残留清理按跟踪状态分两种处理

- `__pycache__/`：先 `git ls-files` 探测是否被跟踪——被跟踪则
  `git rm -r`，未跟踪直接物理删除（`.gitignore` 已覆盖，不会再现于
  版本库）；
- Word 锁文件 `~$*.docx`：`.gitignore` 已覆盖，直接删除；删除前探测
  句柄，仍被占用则记录到 tasks 的跟进项，不阻塞其余工作。

### D4 `__pycache__` 物理再生的控制方式（验证方法决策）

技能目录内的 `.py`（`xlpa/tools/mcp_client.py`、
`protocol-conversion/scripts/*.py`）被 Python 导入时必然再生
`__pycache__`。本变更**不移动脚本**（Non-Goal），通过验证方法控制：
执行通过标准第 2 条的演练与跑测试时，环境设
`PYTHONDONTWRITEBYTECODE=1`；判据表述为"除 Python 字节码缓存外零新增，
且 `git status` 对技能目录无任何未忽略改动"。

### D5 凭据退出跟踪：`git rm --cached` + 补一条 .gitignore

- `git rm --cached mcp_server/.env mcp_server/.token_registry.json`
  （工作副本保留）；
- `.gitignore` 补 `mcp_server/.env`（`.token_registry.json` 及其
  tmp/backup 变体已有条目）；
- 不动 `proxy_config.json`（内网代理地址，非凭据，保持现状）。

### D6 资源包升版：仅升 `package-manifest.json` 0.24.0 → 0.25.0

`requiredFiles` 清单不变（SKILL.md 均已在列）；实施时核对 9 个技能级
`manifest.json` 是否含自身 version 字段，含则同步升 0.25.0（语义为
"落位约定变更"，统一版本号便于排查混布）。

## Risks / Trade-offs

- [旧版资源包（≤0.24.0）用户继续写技能目录] → 本变更无运行时拦截
  （属 C4）；以接入页升级提示与 0.25.0 版本号识别，风险窗口明确记录。
- [Word 锁文件删除失败] → D3 探测 + 记录跟进项，不阻塞；该文件已被
  `.gitignore` 覆盖，不影响版本库判据。
- [git 历史中已存在凭据] → 本变更只切断未来跟踪；轮换凭据列为运维
  建议移交需求方决策（`mcp_server/.env` 的 Token 与 registry 内凭据）。
- [SKILL.md 文本改写遗漏引用] → 通过标准第 3 条用 grep 全量断言
  （`output/`、技能目录内 `temp/` 指引为零），逐处 diff 人工复核。

## Migration Plan

1. 改写 `modbus-conversion` 与 `modbus-cq-adapt` SKILL.md（14 处）；
2. 其余 7 个 SKILL.md 插入统一只读约定段；
3. 残留清理（D3）→ 凭据退出跟踪（D5）→ manifest 升版（D6）；
4. 回归：pytest 全绿（`PYTHONDONTWRITEBYTECODE=1`）+ grep 断言 +
   `git ls-files` 断言 + 一轮"modbus 转换 → cq 适配"真实演练取证。

回滚：全部改动收敛为一次提交，`git revert` 即可整体回退；
`git rm --cached` 的回滚为 `git add` 重新跟踪（内容无损失）。

## Open Questions

（无——D1 的 `xlpa-output/` 目录名为设计决策，若需求方希望换名可在
实施前提出，不影响 spec 与任务结构。）
