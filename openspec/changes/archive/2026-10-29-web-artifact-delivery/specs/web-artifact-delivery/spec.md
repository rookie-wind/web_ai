## Purpose

定义 webchat 侧"产物与上传"的行为契约：用户输入（文本/文档/图片）分道进入会话、
图片经本地 OCR 转文本、会话产物经后端代理下载并以一次性 grant 授权、工作区与产物
按保留期分类处置。本能力在 webchat 侧代理与治理，MUST NOT 改动 mcp_server；与
mcp_server 侧的 `xlpa-archive-template-delivery`（模板生产与交付）是不同能力。

## ADDED Requirements

### Requirement: 输入必须按三通道分道进入会话

用户输入 MUST 支持文本、文档、图片三类，并按数据性质分道处置：文本粘贴 MUST 直接
作为会话消息；已填建档表格 MUST 经 webchat 后端代理转发到 mcp_server 既有上传通道
换取 file_id，MUST NOT 复制进会话工作区（保持"只有 MCP 碰建档数据"）；协议文档
MUST 落会话工作区供运行时读取；屏幕截图 MUST 经本地 OCR 转文本后落会话工作区。
拍照（照片）通道一期推后，provider MUST 预留接口。上传入口优先级：文本粘贴 >
电子表格文件 > 屏幕截图 > 拍照。

#### Scenario: 已填建档表格经代理换取 file_id

- **WHEN** 用户上传一份已填建档表格
- **THEN** webchat 后端代理转发到 mcp_server 既有上传通道，返回 file_id
- **THEN** 表格不复制进会话工作区；运行时后续凭 file_id 经 MCP 工具读取

#### Scenario: 协议文档落会话工作区

- **WHEN** 用户上传协议文档（点表/规格说明等）
- **THEN** 文档落会话工作区（input 分类），运行时可直接读取

#### Scenario: 屏幕截图经 OCR 落工作区

- **WHEN** 用户上传屏幕截图
- **THEN** 后端经本地 OCR 转为文本后落会话工作区，运行时只读文本

### Requirement: 本地 OCR 必须为可插拔 provider 且失败显式提示

OCR MUST 做成可插拔 provider，默认本地实现（离线可跑、CPU 友好、重依赖隔离在
webchat venv，MUST NOT 污染 mcp_server 环境）；识别失败或行列结构无法保留时
MUST 显式提示，MUST NOT 静默以猜测内容继续。质量基线（V8'：三张样图 + 一份电子
表格对照）MUST 留证。

#### Scenario: 截图识别成功

- **WHEN** 一张清晰屏幕截图经 OCR provider 识别
- **THEN** 得到文本并落会话工作区，事件流给出识别结果与质量提示，运行时读该文本继续

#### Scenario: 识别失败显式提示

- **WHEN** 图片模糊或表格行列结构无法保留
- **THEN** 系统显式报错/提示（如"无法识别，请重试或改用文本/表格"），
  MUST NOT 以猜测内容静默继续

### Requirement: 产物下载必须经后端代理且 URL 不携带凭据

产物（模板/报告/转换配置等）下载 MUST 由 webchat 后端代理；下载请求 MUST 经请求头
携带会话凭据 + 一次性 grant；下载 URL MUST NOT 携带凭据或 owner 摘要（防反代日志与
浏览器历史留存）；下载端点 MUST 先校验 artifact_id 命中服务端产物登记表才放行
（artifact_id 为客户端可控输入，MUST NOT 直接拼接路径，防 `../` 路径逃逸），校验
 grant 与会话归属后再回源取产物字节流转发。

#### Scenario: 会话内产物代理下载

- **WHEN** 用户在会话内下载一个产物
- **THEN** 请求头携带会话凭据与一次性 grant，后端校验通过后回源取字节流转发
- **THEN** 下载 URL 不含凭据/owner 摘要

#### Scenario: 跨会话下载被拒

- **WHEN** 用户尝试下载不属于自己会话的产物
- **THEN** 后端校验会话归属失败，拒绝（404/403），不泄漏产物存在性

#### Scenario: artifact_id 路径逃逸被拒

- **WHEN** 客户端构造含 `../` 或未命中登记表的 artifact_id 请求下载
- **THEN** 后端以登记表白名单校验，未命中一律拒绝（404），MUST NOT 直接拼接
  工作区路径，杜绝路径逃逸

### Requirement: 产物下载授权必须为一次性 grant

产物下载授权 MUST 为一次性 grant（消费即作废），区别于写入门禁在 TTL 窗口内可复用
的计划域票据；grant MUST 与 (session_id, 产物标识) 绑定、服务端持有；grant MUST 经
请求头传递，MUST NOT 出现在 URL；一次下载消费后 MUST 立即作废，重放 MUST 被拒。
grant MUST 由按需铸造端点在用户请求下载时签发（响应体返回），MUST NOT 预置进
artifact 事件 payload（防历史重放出现已消费的死票据）。

#### Scenario: grant 消费即作废

- **WHEN** 产物就绪后后端铸造一次性下载 grant，用户凭会话凭据 + grant 下载成功
- **THEN** 该 grant 立即作废；再次使用同一 grant 下载被拒

#### Scenario: grant 不经 URL

- **WHEN** 检查产物下载请求
- **THEN** grant 经请求头传递，不出现在 URL 查询串或路径

#### Scenario: 按需铸造 grant

- **WHEN** 前端要下载某产物，调按需铸造端点请求 grant
- **THEN** 后端校验会话归属后铸造一次性 grant 并在响应体返回（不入事件流）；
  前端再以请求头携带该 grant 下载

### Requirement: 会话工作区与产物必须按保留期分类处置

会话工作区与产物 MUST 按 cleanup.py 既有分类语义处置：会话工作区临时内容（temp）
会话销毁即清；产物与模板（result/template）保留 30 天（与既有快照 DEFAULT_TTL_DAYS
对齐）；含凭据的建档 Excel（sensitive_temp）任务终态后保留 7 天；上传的协议文档与
OCR 文本（input）保留 30 天；写操作审计日志（audit）维持现状不清理；未知分类 MUST
一律保留。保留期是**数据持久化**语义（文件留存供审计/重建）；**可重下载限会话
存活期/进程内**——会话 close 即撤销 mcp_token（与 C3“会话结束凭据立即撤销”一致），
来源 B 回源随之失效，一期不做跨关闭/重启的重下载（持久化产物登记与跨重启归属
推后）。用户主动删除会话 MUST 立即物理删除工作区与产物（新增 delete 端点，
区别于 close）。

#### Scenario: 会话销毁清临时内容

- **WHEN** 会话被用户结束或超时回收
- **THEN** 该会话工作区 temp 内容即清；result/template 产物按 30 天保留

#### Scenario: 保留期内文件持久但重下载限会话存活期

- **WHEN** 会话仍存活（未 close、进程未重启）且用户回到该产物
- **THEN** 可重新铸造一次性 grant 再次下载；会话 close 或进程重启后，产物文件按
  保留期留存（供审计/重建），但一期不再提供重下载（mcp_token 已撤销）

#### Scenario: 未知分类一律保留

- **WHEN** 清理流程遇到无法归类的文件
- **THEN** 一律保留，不误删可复用或可审计资产

### Requirement: 用户主动删除会话必须立即物理删除

用户主动删除会话 MUST 立即物理删除该会话工作区与全部产物（temp/input/result/
template 一并清除），区别于 close（close 只撤销凭据/终止实例并按保留期留存文件）；
删除 MUST 校验会话归属，删除后该会话产物 MUST NOT 再可下载。

#### Scenario: 删除会话即物理清除

- **WHEN** 用户对属于自己的会话发起删除
- **THEN** 后端立即物理删除该会话工作区与全部产物，后续下载请求一律 404

### Requirement: 上传必须施加大小上限

上传 MUST 施加大小上限：建档表格 10 MB、屏幕截图/图片 10 MB、协议文档 20 MB
（对齐 mcp_server 既有分块上传上限机制）；超过上限 MUST 明确拒绝并提示，
MUST NOT 静默截断或耗尽缓冲。

#### Scenario: 超限上传被拒

- **WHEN** 用户上传超过对应通道上限的文件
- **THEN** 后端明确拒绝（如 413）并提示上限，不落盘、不耗尽内存缓冲
