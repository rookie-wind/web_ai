# web-ui-content-security Specification

## Purpose

定义 webchat 页面的内容安全基线：全部响应携带内容安全策略（CSP）头、
第三方前端代码仅经同源静态目录加载、助手内容渲染管线强制消毒，使页面
在引入富内容渲染后不扩大跨站脚本（XSS）攻击面。

## ADDED Requirements

### Requirement: webchat 全部响应必须携带内容安全策略头

webchat 服务 MUST 为全部 HTTP 响应（单页入口、静态资源与 API）下发
Content-Security-Policy 响应头：脚本仅允许同源加载；样式允许同源与
内联样式（图形渲染库运行时会注入内联样式）；图片允许同源与 data:；
连接仅允许同源。策略 MUST NOT 放开内联脚本执行（不得出现
unsafe-inline 于 script 指令、不得出现 data: 或外部主机的脚本源）。

#### Scenario: 页面与静态资源响应含 CSP 头

- **WHEN** 浏览器请求 webchat 单页入口或任一静态资源
- **THEN** 响应头包含 Content-Security-Policy，其 script 指令仅允许同源

#### Scenario: 内联脚本注入被策略阻断

- **WHEN** 页面中出现任何内联脚本或内联事件处理器（无论来自注入还是失误）
- **THEN** 浏览器依 CSP 拒绝执行，页面其余功能不受影响

#### Scenario: 图形渲染运行时不被 CSP 误伤

- **WHEN** 助手消息中的 mermaid 代码块被渲染为图形
- **THEN** 渲染不受 CSP 阻断（内联样式与 data: 图形资源在允许范围内），
  图形正常显示

### Requirement: 第三方前端代码必须同源 vendored 且记录来源版本

页面引用的全部第三方渲染代码 MUST 来自同源静态目录（vendored 随应用
部署），MUST NOT 引用任何外部 CDN 或跨源脚本。每个 vendored 文件 MUST
记录其来源与版本（文件头注释或配套清单），以便后续升级比对。

#### Scenario: 外网 CDN 不可达时渲染不受影响

- **WHEN** 用户浏览器所处网络无法访问任何外部 CDN（或完全断外网，仅达
  webchat 服务器）
- **THEN** 富内容渲染功能完整可用，页面无对不可达外部资源的引用

#### Scenario: 源码无外部脚本引用

- **WHEN** 检查页面与前端脚本源码中的第三方引用
- **THEN** 全部来自同源静态目录，且每个文件可查到来源与版本记录

### Requirement: 助手内容渲染必须强制消毒且失败可降级

任何由助手内容派生的 HTML 注入页面 DOM 前 MUST 经白名单消毒（默认拒绝
白名单外的标签、属性与事件处理器）；图形渲染 MUST 在禁用脚本执行与
外部访问的严格安全模式下运行。消毒环节不可绕过、不可按内容来源选择性
跳过。消毒或渲染失败 MUST 降级为纯文本/源码展示，MUST NOT 中断会话
事件渲染流，MUST NOT 向页面注入未经消毒的标记。

#### Scenario: 脚本注入被消毒剔除

- **WHEN** 助手回复包含 `<script>` 标签或事件处理器属性（经上传文档
  提示注入诱导产生）
- **THEN** 该类内容被消毒移除，页面不执行任何脚本、不发起外部请求

#### Scenario: 严格模式下图形无外部访问

- **WHEN** mermaid 代码块被渲染
- **THEN** 渲染过程不执行图内脚本、不发起外部网络访问，仅产出静态图形

#### Scenario: 消毒失败降级不中断

- **WHEN** 消毒或渲染环节对某段助手内容失败（异常或不可解析）
- **THEN** 该段内容以纯文本/源码形态降级展示并给出提示，同会话后续事件
  继续正常渲染
