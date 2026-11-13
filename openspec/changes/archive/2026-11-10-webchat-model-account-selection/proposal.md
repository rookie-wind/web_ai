## Why

webchat 目前所有会话共用一个全局模型（`Qwen3.8-Flash`，仅 env 可配）与一个共享
Qoder 云 PAT：用户无法按任务在能力/成本/速度间选模型，也无法用自己的 Qoder
订阅/额度跑模型。IDE 用户本就能在 Qoder IDE 原生选模型，webchat 缺此对等能力。
SDK 已具备所需接口（`get_available_models` / `set_model` / per-client 凭据），
缺的是 webchat 侧的按用户 plumbing、安全存储与前端入口。

## What Changes

- 新建会话时可选 **Qoder 云账号**：服务端默认账号 或 用户自带 PAT；账号会话级
  固定，切账号需换会话（账号凭据在客户端构建时绑定，无热切换接口）。
- 自带 PAT 在建会话时经 `get_available_models` **校验有效性**，失败则拒绝建会话
  并给出可辨识原因；默认账号不可用（无 env PAT 且无本机登录态）时提示需自带。
- 输入区新增**模型下拉**：清单按当前账号拉取，只列 `isEnabled` 模型并标注
  `isFree`/`priceFactor`（免费/成本）；**消息级**切换（`set_model`，不重建客户端、
  不切换接入凭据）。
- 默认预选模型：默认账号沿用配置默认（`Qwen3.8-Flash`）；自带账号选其清单首个
  启用模型（全局配置默认若在该清单则优先）。
- 自带 PAT 可选"**记住**"：默认仅会话内存；记住则**明文**存于已 gitignore 的
  账号库（per-user），可清除；护栏：不进日志/进程命令行、UI 掩码、收紧文件权限。
- 前端新增"新建会话"对话框（账号单选 + PAT 掩码框 + 记住勾选）；compose 区模型
  下拉（紧挨既有上传通道选择）。
- 范围 **web-only**；**不做 BYOK**（自带模型商 key 是另一套受订阅门控的功能）。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `agent-runtime-session`: 新增「会话级 Qoder 云账号绑定与 PAT 校验」「账号级模型
  清单与消息级模型选择」「自带 PAT 的记住/清除与明文存储」三组要求。既有 1:1:1
  绑定、持久客户端、国内版 SDK PAT 仅经 env 注入等要求保持不变且被新行为遵守。
- `web-chat-ui`: 新增「新建会话账号选择对话框」「输入区模型选择下拉」两组要求。
  既有多会话管理、路由前缀提示等要求保持不变。

## Impact

- 代码：`webchat/webchat/` 的 `config.py`、`api.py`、`runtime.py`、
  `sessions_api.py`、`accounts.py`、`sdk_runtime/adapter.py`；前端
  `static/index.html`、`static/js/app.js`。
- SDK 接口：`QoderSDKClient.get_available_models()` / `set_model()`、
  `QoderAgentOptions.model`、`pat_env` 注入口（已有，改喂按会话值）。
- 存储：`Account` 新增可选 `qoder_pat` 字段（`webchat_accounts.json`，已 gitignore、
  不进版本控制，与既有明文 phone/code 同姿态）。
- 凭据分层：新增 **Qoder 云账号**（第五层凭据），与 MCP 接入 Token、门禁票据、
  会话票据、边缘会话凭据互不等价；**不触碰**写门禁、审计归属、平台授权激活。
- 决策与术语：ADR-0004（明文 PAT 存储 stance）；GLOSSARY 已补「模型/型号/自带账号/
  Qoder 云账号」。
- 不变化量：会话:句柄:凭据 1:1:1（账号会话级、模型切换不动凭据）、技能注入、
  事件契约 v1、IDE 回归。