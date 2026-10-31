## 1. 来源 B：mcp_server file_id 产物桥接

- [x] 1.1 `artifacts.py` 将唯一化落盘辅助 `unique_path` 公共化（导出并更新内部调用），
  供 runtime 回源落盘复用；验证：既有多通道上传测试不受影响。
- [x] 1.2 `runtime.py` 新增来源 B 采集：白名单工具结果含 `file_id` 时，用会话
  `mcp_token` 回源 `/api/archive/templates/<id>?owner=sha256(token)`（或结果自带
  `download_url`），字节落 `xlpa-output/`、登记产物、产 `artifact` 事件；验证 pytest：
  生成模板后出现 artifact 事件且 payload 不含 token/owner/grant。
- [x] 1.3 同一会话同一 `file_id` 只登记一次；回源失败（非 200/超时/超限）产 `error`
  事件且不含 URL/owner/Token；验证 pytest：重复工具结果不重复登记、上游 500 与超时
  路径均出 error 事件且文件不落盘。

## 2. 内置写入受限放行

- [x] 2.1 `grants.py` 新增内置写入裁决：`Write`/`Edit`/`MultiEdit`/`NotebookEdit`
  放行条件为 `resolve()` 后位于 `${workspace}/xlpa-output/` 且扩展名在文本白名单；
  缺 `file_path`、未注入工作区、越界路径、非白名单扩展名一律 deny（confirmable=False）；
  验证 pytest：越界（`../`、绝对外部路径）、缺参、`.docx` 拒绝，`.md/.json` 放行。
- [x] 2.2 `runtime.py` 构造 `WriteGate` 时注入会话工作区；验证 pytest：会话内
  Write 产物目录放行、目录外拒绝，`Bash` 仍拒绝。

## 3. 契约与测试收口

- [x] 3.1 修订 `test_grants.py` 锁定用例（原"Write 带工作区内路径也 MUST deny"改为
  路径/扩展名裁决），新增越界与扩展名用例；验证：用例通过。
- [x] 3.2 新增来源 B 运行时用例（fake mcp_server HTTP 返回模板字节），断言落盘、
  登记、artifact 事件、去重与失败分支。
- [x] 3.3 `webchat/README.md` 更新产物来源说明（来源 A + 来源 B）与内置文档写入边界。
- [x] 3.4 webchat 全量 pytest 与主项目 pytest 基线全绿；`openspec validate --all --strict`
  通过；记录通过数。

## 验证记录

- webchat：`141 passed`（含新增 `tests/test_remote_artifacts.py` 5 项与内置写入裁决用例）。
- 主项目：`770 passed, 1 skipped`。
- `openspec validate --all --strict`：`22 passed, 0 failed`。
