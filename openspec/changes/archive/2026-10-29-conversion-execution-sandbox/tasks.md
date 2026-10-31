## 1. 沙箱地基

- [x] 1.1 新增 `mcp_server/conversion/sandbox_runner.py`：stdin 收
  `{mode: mqtt|http, config, input}`，加载分发源引擎（`sys.path` 注入
  `SKILLS_DIR/protocol-conversion/scripts`，路径经环境变量传入避免命令行拼接），
  执行 `MapperCore.transform_mqtt/transform_http`，stdout 回
  `{ok, output | error}`；异常与崩溃捕获为结构化错误；无 shell、无文件写入。
- [x] 1.2 新增 `mcp_server/conversion/executor.py`：`run_sandbox_batch()` ——
  每次 case 独立临时目录（`tempfile.mkdtemp` + try/finally rmtree）、
  `subprocess.run` 参数列表、单 case 超时 20s / 整批 120s、输入上限
  （config 1 MB / 单输入 256 KB / case 数 50）、stdout 上限 2 MB；超时/超限/
  非零退出显式返回失败原因；验证 pytest：正常执行、超时、超限、临时目录清理
  （成功与失败路径均查残留）、引擎缺失显式报错。
- [x] 1.3 启动校验：`server.py` 启动时检查引擎文件存在，缺失打告警日志
  （服务不崩）；验证 pytest：文件缺失时工具返回"引擎不可用"。

## 2. validate_config_format（进程内）

- [x] 2.1 新增 `mcp_server/conversion/validator.py`：MQTT / HTTP / Modbus 三
  契约结构校验（枚举、必填、条件必填、类型），输出
  `{ok, conversion_type, errors: [{path, rule_index?, reason}], checked}`；
  不执行配置；验证 pytest：合法配置通过、逐类必填/枚举错误、Modbus read
  必填、错误含路径与原因。

## 3. generate_test_data（进程内）

- [x] 3.1 新增 `mcp_server/conversion/testdata.py`：遍历 mappings 的
  source/type 生成 normal/boundary/abnormal 三组输入（可直接作 test_cases）；
  Modbus 返回明确不支持；验证 pytest：三组结构、类型覆盖（string/double/
  int/bool/array）、输出可作为 execute 的输入格式。

## 4. execute_conversion_test + 报告存储

- [x] 4.1 新增 `mcp_server/conversion/report_store.py`：测试报告 JSON 持久化
  （owner 隔离、7 天 TTL、test_run_id 查询、越权不存在语义）；验证 pytest：
  保存/查询/过期/越权。
- [x] 4.1b 工具实现：先过校验（不合法返回校验报告不进沙箱）→ 逐 case 沙箱
  执行 → expected 深度对比（含类型）→ 聚合报告（total/passed/failed/skipped、
  results[] 含失败摘要截断）→ 持久化返回 test_run_id；验证 pytest：2 对 1 错
  聚合、无 expected 仅返回输出、非法配置短路、Modbus 拒绝。
- [x] 4.2 `get_test_report` 工具：归属校验后返回报告；验证 pytest：本人可查、
  他人 404 语义、不存在 404。

## 5. save_conversion_config + pack_bundle

- [x] 5.1 `save_conversion_config` 工具：校验通过才存
  `template_store.save(bytes, template_name=<name>.json)`，返回 file_id +
  下载端点；验证 pytest：合法保存可下载取回、非法拒绝、owner 隔离。
- [x] 5.2 `pack_bundle` 工具：解析 test_report_json，status != passed 拒绝；
  生成 ZIP（config/mapping_report/test_report/source_spec?/target_spec?/
  README（占位符清单从 config 提取）/manifest（SHA256 清单））；存
  template_store 返回 file_id；验证 pytest：门控拒绝、ZIP 结构完整、SHA256
  一致、README 占位符提取。

## 6. server.py 注册与工具面

- [x] 6.1 `conversion_tools.py` 汇总 6 工具（`@mcp.tool()` + docstring 参数
  说明，仿 edge_tools 注册模式）；`server.py` 调用注册 + `TOOL_DEFINITIONS`
  增 6 条 type=exec；save/pack 记操作日志（既有 trace 机制），纯计算工具
  不记；验证 pytest：`list_mcp_tools` 含 6 工具、total=77、防漂移
  （webchat test_grants 按新注册表解析仍全绿）。
- [x] 6.2 鉴权口径：6 工具不要求业务登录（不调 `_require_session`），鉴权由
  AuthMiddleware 的 Bearer 校验承担（无凭据/无效凭据 401）；产物归属取
  `derive_owner_id(mcp_token_var)`；验证 pytest：user 级凭据可调用、
  无 mcp_token 时产物类工具明确报错。

## 7. SKILL.md 改写 + 资源包升版

- [x] 7.1 `test-validation/SKILL.md`：工具表"待开发"→"已就绪"；Phase 1/3/5
  改为工具调用步骤（validate → generate → execute → get_test_report →
  save）；Modbus 章节声明沙箱执行不适用；版本 0.1.1→0.2.0（SKILL.md +
  manifest.json）。
- [x] 7.2 `pack-distribution/SKILL.md`：Phase 3 打包改 `pack_bundle`（测试
  门控说明）；install_pack 等保持"待开发"；版本 0.2.0→0.3.0。
- [x] 7.3 `protocol-conversion/SKILL.md` §13：补服务端沙箱执行入口说明；
  版本 1.4.0→1.4.1。
- [x] 7.4 `xlpa/SKILL.md`：能力矩阵与下一步建议补"沙箱测试 / 打包分发"
  （Web 与 IDE 一致可用）；版本 0.7.0→0.8.0。
- [x] 7.5 `modbus-conversion/SKILL.md`：测试章节声明 execute 工具不适用
  Modbus（维持静态契约 + 离线算例报告口径）；版本 bump。
- [x] 7.6 `package-manifest.json` 0.25.0 → 0.26.0；`list_mcp_tools` 的
  resource_package.version 随之显示 0.26.0；验证 pytest：包 manifest 校验
  通过、版本一致。

## 8. 回归与证据

- [x] 8.1 主 pytest 全绿（新增 `mcp_server/tests/test_conversion_tools.py`
  及各模块单测，记录通过数）；webchat pytest 全绿（确认 exec 不进写入集、
  防漂移不破）。
- [x] 8.2 端到端冒烟：启动 mcp_server，user 级 token 依次调用
  validate → generate → execute → get_test_report → save → pack_bundle →
  票据下载 ZIP 解包校验 SHA256；结论记入
  `validation/conversion-execution-sandbox/evidence-index.md`。
- [x] 8.3 IDE 兼容核验：既有 71 工具行为不变（`list_mcp_tools` 输出比对，
  仅 total 与新增条目差异）；webchat 会话经回环调用 exec 工具放行（无
  gate_blocked）。
