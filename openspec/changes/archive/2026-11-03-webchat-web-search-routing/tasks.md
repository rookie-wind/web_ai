## 1. 工具面与门禁

- [x] 1.1 `adapter.py`：`tools` 追加 `"WebSearch"`；`allowed_tools` 仍只含
  `Write`/`Edit`；`can_use_tool` 放行 WebSearch；`WebFetch`、`Bash` 保持拒绝。
  验证：options 断言包含 WebSearch；复跑 `_smoke_websearch_v5.py` 变体 W：
  WebSearch 被调用、MCP 仍 connected/77 工具、工具错误数 0。
- [x] 1.2 `grants.py`：新增 `WEB_SEARCH_TOOL_NAMES={"WebSearch"}` 放行并写审计；
  其余未知内置工具仍 deny。验证 pytest：WebSearch allow、WebFetch/Bash deny。

## 2. 路由与数据边界

- [x] 2.1 `adapter.py` 系统提示追加路由表：内部（平台/设备/建档/下发/召测/
  协议转换/边缘）→ xlpa；外部（公开标准/厂商手册/新闻/给定 URL）→ WebSearch；
  混合任务先检索后执行；不确定默认按 xlpa 或先澄清。
- [x] 2.2 系统提示定义可选前缀语义：仅消息开头、大小写不敏感、只影响当前消息、
  执行前剥离、`/web` 无任务时追问、其他 `/xxx` 视为普通文本。
- [x] 2.3 系统提示加入数据边界：禁止把凭据/设备地址/内部文档原文送入检索；
  必要时先脱敏或确认；检索失败如实告知。
- [x] 2.4 前端输入框 placeholder 增加可选前缀说明（不新增模式开关、不拦截输入）。

## 3. 回归与验收

- [x] 3.1 新增用例：工具面/门禁/系统提示/placeholder 断言；webchat 全量
  **156 passed**；主项目基线 **770 passed, 1 skipped**。
- [ ] 3.2 行为验收：外部标准问题走 WebSearch；平台设备问题走 xlpa；`/web`、
  `/xlpa` 强制生效；不带前缀自动判定；内部信息检索被拒绝或先脱敏。
  <!-- 2026-10-31：`_smoke_websearch_v5.py` 复跑变体 W 已证「外部问题调用
  WebSearch 且 MCP 仍 77 工具」；追加的自动路由/前缀真机探针本次多轮返回空
  消息（无 error，疑似模型服务瞬时不可用），未取得新证据，故 3.2 不勾。 -->
- [x] 3.3 WebFetch 作为后续评估项（URL 白名单/重定向/内网拦截），本变更不实现。
- [ ] 3.4 `openspec validate --all --strict` 通过后归档本变更。
