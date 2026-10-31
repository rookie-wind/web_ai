## Context

动机见 proposal.md - Why。此处记录塑形方案的现状与约束（均已实测核实）：

- **C4 已禁 Bash**：Web 会话 agent 无 shell，`test-validation` 的"运行
  `python -m unittest test_protocol_converter`"与 `pack-distribution` 的"压缩为
  ZIP"在 Web 端无法执行；IDE 端虽有 Bash 但依赖本机环境，且与"服务端持有执行
  能力"的目标架构不符。
- **引擎是纯库、无 CLI**：`protocol_converter.py`（24,846 B）只有
  `MapperCore.transform_mqtt / transform_http` 两个类方法入口，无 `main`、无
  `argparse`、无文件读写（纯内存 JSON 变换）——子进程执行需一个 runner 脚本
  包一层 stdin→stdout 协议。
- **引擎单一事实源**：`agent_assets/skills/protocol-conversion/scripts/` 是分发
  源只读母本（C1 治理后干净、无作业残留）；mcp_server 启动日志已绑定
  `SKILLS_DIR = agent_assets/skills`（打包 ZIP 时即用），引用该路径属既有依赖。
- **产物存储范式已存在**：`template_store`（SnapshotStore）提供 owner 隔离、
  30 天 TTL、防篡改校验、`file_id` 即票据的下载端点
  `/api/archive/templates/<id>?owner=`；`save(snapshot, owner_id=, template_bytes=,
  template_name=)` 接受任意字节。URL 带 owner 摘要的公网门控已由 C5 proposal
  延至 C7，一期（内网）保持既有行为。
- **webchat 门禁的防漂移锚**：`webchat/tests/test_grants.py` 按正则解析
  `server.py` 的 `TOOL_DEFINITIONS`，断言 `WRITE_TOOL_NAMES == type∈{write,
  edge_write}` 全集、`LOGIN_TOOL_NAMES == type==login 全集 + edge_get_token`；
  新增 type=exec 不进任何集合，测试天然兼容。
- **Modbus 无镜像引擎**：`mapper_core.c` 的 Python 镜像只覆盖 MQTT/HTTP 映射；
  Modbus 转换配置由边缘 C 引擎按 JSON 契约读取，测试策略是静态契约检查 +
  离线算例（SKILL 层），无法沙箱执行。
- **环境约束**：Windows 单机、无容器（架构 D8），隔离只能靠逻辑手段；mcp_server
  venv 为 Python 3.14，引擎脚本无第三方依赖（纯标准库），子进程用同 venv 的
  `sys.executable` 执行即可。

## Goals / Non-Goals

**Goals:**
- 6 个 exec 类 MCP 工具落地，Web 与 IDE 经同一 `/mcp` 入口调用。
- 沙箱纪律：固定代码 + 不可信数据；子进程、超时、大小上限、临时目录用后即清。
- 产物（配置/ZIP）按 owner 隔离保存、30 天保留、file_id 即票据可下载。
- 测试门控打包：`pack_bundle` 校验测试报告状态为 passed 才打包。
- SKILL.md 从"AI 手动模拟"切换到工具调用；资源包升版 0.26.0。
- 主 pytest + webchat pytest 全绿；IDE 既有工具行为不变。

**Non-Goals:**
- 编译/执行 C 引擎（mapper_core.c 本体）——镜像引擎仅用于测试验证，与 SKILL
  既有定位一致。
- Modbus 沙箱执行（无镜像引擎；静态契约校验 + 离线算例维持 SKILL 层）。
- `install_pack` / `list_packs` / `get_pack_info` / `delete_pack`（pack-distribution
  SKILL 规划的安装/管理类工具）——安装属目标环境运维动作，推后。
- Web 端对 mcp_server 侧产物（来源 B）的代理下载——C5 已划归二期。
- D12 工具面按意图收敛（77 工具全量 schema 体积优化）——独立后续优化。
- mcp_server 既有端点的公网门控（C7）。

## Decisions

### D1 工具面：6 工具、type=exec、user 级、webchat 零改动

| 工具 | 形态 | 说明 |
|---|---|---|
| `validate_config_format` | 进程内 | 纯结构校验，不执行配置 |
| `generate_test_data` | 进程内 | 从 mappings 结构推导测试输入 |
| `execute_conversion_test` | **子进程沙箱** | 逐 case 执行镜像引擎 |
| `get_test_report` | 进程内 | 按 test_run_id 查询持久化报告 |
| `save_conversion_config` | 进程内（写存储） | 配置 JSON 存 template_store |
| `pack_bundle` | 进程内（写存储） | 打 ZIP 存 template_store |

全部 user 级（不写平台、不碰边缘），`TOOL_DEFINITIONS` type 取新值 `exec`。
webchat `classify_tool` 对非 login/write 一律放行——跑测试/打包不是平台写操作，
无需用户逐次确认（确认风暴反噬体验）；产物归属由存储层 owner 隔离兜底。
**备选**：把 exec 纳入 C4 写入集要求确认——否决，语义不符（无平台副作用），
且 IDE 路径无门禁会造成两条路径行为分叉。

### D2 沙箱 = 固定代码 + 不可信数据（非不可信代码）

安全模型：执行的代码是仓库内受版本控制的固定脚本清单（runner + 引擎镜像），
用户输入只作为**数据**（JSON 配置/测试输入）进入；不执行用户提供的代码、
不解释 shell。措施：
- `subprocess.run([sys.executable, runner_path], input=..., cwd=<临时沙箱目录>,
  timeout=N, shell=False)`，参数为列表、无字符串拼接命令行；
- **每次调用独立临时目录**（`tempfile.mkdtemp` 于系统临时区），结束即
  `shutil.rmtree`，失败路径也清理（try/finally）；
- 输入上限：config ≤ 1 MB、单条测试输入 ≤ 256 KB、case 数 ≤ 50；
- 输出上限：stdout ≤ 2 MB，超出即失败返回（防内存放大）；
- 超时：单 case ≤ 20s、整批 ≤ 120s（引擎纯内存操作，正常毫秒级完成，上限只
  兜底病态输入的递归/巨量遍历）；
- 递归深度：镜像引擎对 sub_mappings 递归无显式上限，靠子进程超时 + 输出上限
  兜底（进程崩溃即该 case 失败，不影响服务）。

**备选**：进程内直接 import 引擎——否决，递归/异常会打进服务进程，子进程是
唯一可靠的故障隔离边界（Windows 无容器前提下的逻辑隔离）。

### D3 引擎单一事实源：引用分发源只读母本，不复制

runner 直接 import `SKILLS_DIR/protocol-conversion/scripts/protocol_converter.py`
（`sys.path` 注入该目录）。版本随资源包升级自动跟随，杜绝双份漂移；启动时
校验文件存在，缺失则 exec 工具返回明确的"引擎不可用"错误（服务不崩）。
**备选**：复制引擎到 mcp_server/ 下——否决，违反单一事实源，资源包升级即漂移。

### D4 validate_config_format：进程内三契约校验

- **MQTT**（`platform_name` + `mappings[]`）：根字段、每条规则的
  target/source_type/type 必填、source_type ∈ {path,constant,generated,
  array_foreach,context}、type ∈ {string,double,int,long,bool,object,substitute}、
  条件必填（constant/generator/item_type）、scale 为数值。
- **HTTP**（`base_url` + `token{}` + `apis[]`）：apis[].data_mappings 同上规则。
- **Modbus**：根字段 prtlType/modelNum/classNum/taskList/labelList、read 必填
  （write/convert 可选）、data_type/data_order 枚举（对齐 modbus-conversion
  SKILL 核心表）。
校验产出结构化结果（ok/errors[]，每条含路径与原因），**不执行配置**。
进程内实现（纯遍历无递归执行风险）。

### D5 generate_test_data：进程内结构推导

遍历 mappings 的 source 路径与 type，生成三组输入（normal/boundary/abnormal）：
normal 按类型造值（string→样例串、double/int→样例数、bool→true）、boundary
含空串/0/负数/超大数/空数组、abnormal 含类型错位（数字字段传字符串等）。
输出可直接作为 `execute_conversion_test` 的 test_cases 输入。Modbus 不支持
（返回明确错误）。

### D6 execute_conversion_test + 报告持久化

输入：`conversion_type ∈ {mqtt_to_mqtt, http_to_mqtt}`、`config_json`、
`test_cases[]`（每条 {name, input, expected?}）。流程：
1. 先过 D4 校验（不合法直接返回校验报告，不进沙箱）；
2. 逐 case 在沙箱子进程执行（runner stdin 收 {mode, config, input}，stdout 回
   {ok, output | error}）；
3. 有 expected 则深度对比（含类型），无 expected 仅返回实际输出；
4. 聚合为报告（testId/test_run_id、total/passed/failed/skipped、results[]），
   持久化到转换报告存储（JSON 文件，owner 隔离，7 天 TTL——对齐
   sensitive_temp/operation_log 短保留语义），返回 test_run_id；
5. `get_test_report(test_run_id)` 按归属查询。
失败 case 显式带错误与 stdout 摘要（截断），**不静默跳过**。

### D7 save_conversion_config / pack_bundle：复用 template_store

- `save_conversion_config(conversion_type, config_json, name)`：先过 D4 校验，
  合法才存；`template_store.save(..., template_bytes=<UTF-8 JSON>,
  template_name=<name>.json)`，返回 file_id + 下载 URL（既有端点）。
- `pack_bundle(pack_name, config_json, mapping_report_md, test_report_json,
  source_spec_json?, target_spec_json?)`：**测试门控**——解析 test_report_json，
  `status != "passed"` 即拒绝（4xx 语义错误返回）；生成 ZIP（目录结构对齐
  pack-distribution SKILL：config.json / mapping_report.md / test_report.json /
  source_protocol_spec.json / target_protocol_spec.json / README.md /
  manifest.json 含 SHA256 清单），存 template_store，返回 file_id + 下载 URL。
- owner_id = `derive_owner_id(mcp_token)`（与建档快照同源语义：IDE 稳定、Web
  随会话凭据）；TTL 30 天随 store 既有清理。
**备选**：新建独立 conversion store + 下载端点——否决，新增 HTTP 面与存储机制
无对应收益，复用既有票据下载链路即可。

### D8 Modbus 边界与 SKILL.md 改写范围

`execute_conversion_test`/`generate_test_data` 对 `modbus_to_internal` 返回
明确"不支持"错误；`validate_config_format` 支持 Modbus 契约校验。SKILL.md 改写
清单（5 个）：
1. `test-validation`：「调用的 MCP 工具（MCP 就绪后）」→「调用的 MCP 工具（已就绪）」；
   Phase 1/3/5 的"AI 手动"改为工具调用步骤；compatibility 去掉"待开发"。
2. `pack-distribution`：Phase 3 打包改为 `pack_bundle`；`install_pack` 等其余
   工具保持"待开发"标注。
3. `protocol-conversion`：§13 Python 测试镜像补"服务端沙箱执行入口"说明。
4. `xlpa`：能力矩阵与下一步建议补"沙箱测试 / 打包分发"行（Web 与 IDE 一致）。
5. `modbus-conversion`：测试章节声明 execute 工具不适用，维持静态契约 + 离线
   算例报告口径。
版本 bump：package-manifest 0.25.0→0.26.0；test-validation 0.1.1→0.2.0、
pack-distribution 0.2.0→0.3.0、protocol-conversion 1.4.0→1.4.1、xlpa 0.7.0→0.8.0
（SKILL.md frontmatter 与 manifest.json 同步）。

### D9 server.py 注册与兼容性

`conversion_tools.register_conversion_tools(mcp)`（仿 edge_tools 模式），
`TOOL_DEFINITIONS` 增 6 条 type=exec；`list_mcp_tools` total 71→77（纯增量）。
产物类工具（save/pack）记操作日志（既有 trace 机制）；纯计算工具
（validate/generate/execute/get_report）不记（对齐 read 工具口径）。
webchat 零改动：防漂移测试按 type 解析，exec 不进 write/login 集。

## Risks / Trade-offs

- [病态输入打爆子进程] → 超时 + 输出上限 + case 数上限三重兜底；子进程崩溃
  仅该 case 失败。
- [引擎随资源包升级引入不兼容] → 引擎与工具同仓同版发布；资源包 0.26.0 与
  服务端工具为同一变更交付，升级同步；启动校验引擎存在性。
- [77 工具全量 schema 体积增长] → 已知取舍（D12 收敛为后续优化）；webchat 会话
  按意图挂子集的路由已有设计，不阻塞本变更。
- [file_id 即票据的既有安全问题] → 与 C5 同口径：公网门控延至 C7，一期内网；
  本变更不新增 HTTP 端点、不扩大暴露面。
- [测试门控被绕过（直接传伪造 passed 报告）] → 门控是质量约束非安全边界；
  报告可经 `get_test_report` 交叉核验（test_run_id 可溯源），SKILL 层要求引用
  真实 test_run_id。
- [Web 端拿到 file_id 但代理下载属二期] → 一期 Web 用户可经 IDE/浏览器直接
  下载（内网）；来源 B 代理下载已列 C5 二期清单，spec 场景相应收窄。

## Migration Plan

1. **部署**：mcp_server 更新重启（新工具注册）；资源包 0.26.0 分发（含 SKILL.md
   改写）；二者同变更交付，无中间态依赖。
2. **灰度顺序**：沙箱 runner + validate → generate/execute/report → save/pack →
   SKILL.md + 升版，各步独立 pytest 留证。
3. **回滚**：工具为纯增量注册，回滚 mcp_server 版本即移除工具面；已存产物
   （配置/ZIP/报告）按 TTL 自然过期，无迁移负担。

## Open Questions

- 报告 TTL 7 天是否足够（对齐 sensitive_temp 口径）——实现期按 7 天落地，
  若现场需要更长追溯再调（配置化）。
- `pack_bundle` 的 README 占位符清单（${VAR_NAME}）扫描——一期从 config JSON
  文本中正则提取 `$...$`/`${...}` 模式生成，精度不足时二期再按映射规则细化。
