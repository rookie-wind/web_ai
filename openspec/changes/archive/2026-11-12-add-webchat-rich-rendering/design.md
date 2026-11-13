# add-webchat-rich-rendering — 设计

## Context

前端为纯 vanilla ES modules（`app.js` / `api.js` / `sse.js`），无构建系统、
无第三方库；助手消息经 `textContent +=` 纯文本追加渲染（`app.js` text_delta
分支）。后端未下发任何 CSP 头；`index.html` 无内联脚本与内联事件处理器，
全部脚本为 `/static` 外链模块（CSP 兼容性已核实）。会话系统提示已有追加
机制 `WEBCHAT_SYSTEM_APPEND`（`adapter.py:280`，preset+append 形态）。
测试为 `test_static_frontend.py` 的静态 marker 断言模式；部署为 Windows
单机、一期直接公网、移动端沉浸布局（`position:fixed; inset:0`）。事件契约
（text_delta 等）与 SSE 重放路径不在本变更范围内。动机见 proposal.md。

## Goals / Non-Goals

**Goals:**

- 助手消息富渲染管线：markdown（GFM 表格）+ 代码块高亮与复制 + mermaid
  图形，三条路径（实时流、断线重连、刷新回放）形态一致
- 强制消毒纪律与 CSP 头，使 XSS 面不因 HTML 渲染扩大
- 零 CDN 依赖的 vendored 引入方式，mermaid 懒加载控制首屏成本
- 模型侧输出约定经既有 `WEBCHAT_SYSTEM_APPEND` 注入，资源包零改动

**Non-Goals:**

- 不做数学公式（KaTeX）与任务清单 checkbox 渲染
- 不做表格全屏查看层、表格导出（CSV/Excel）
- 不改事件契约、后端存储、会话/门禁/租约语义
- 不动 SKILL.md、agent_assets 资源包与 IDE 路径
- 不引入构建系统、打包器或 npm 工具链

## Decisions

### D1 渲染库选型：marked + DOMPurify + highlight.js(core+白名单) + mermaid

- markdown 解析用 **marked**：内置 GFM 表格、`breaks: true` 支持聊天式
  单换行、体积小于 markdown-it 且无插件依赖（否决 markdown-it：插件生态
  在本场景无增益）。
- 代码高亮用 **highlight.js core + 白名单语言注册**
  （json/yaml/python/javascript/xml/bash/ini/sql，约 20KB）：协议点表与
  配置样例的实际语言集；否决全量语言包（约 1MB，90% 语言用不到）。
- 图形渲染用 **mermaid**（v11.4.1 UMD 单文件）：```mermaid 是模型输出
  流程图的事实标准语法；否决自研 SVG 简图（语法生态与维护成本不成比例）。
  v11 ESM 为分片 bundle（dist/chunks 数十个文件），无构建系统下不可单文件
  分发，故取 UMD——懒加载语义不变（实现方式由 dynamic import 调整为
  script 动态注入，见 D5）。实测 v11.4.1 忽略 `flowchart.htmlLabels`
  （渲染仍输出 foreignObject，被消毒白名单剥除后标签全空），故在
  initialize **顶层**设 `htmlLabels: false` 以 `<text>` 渲染标签，
  foreignObject 始终不入白名单。
- 消毒用 **DOMPurify**：事实标准、与 marked 产出的 HTML 兼容、支持
  白名单配置。

### D2 vendored 引入：`static/vendor/` + 文件头版本注释

各库 dist 直接放入 `webchat/webchat/static/vendor/`，文件头注释记录来源
URL 与版本号（无 VENDOR.md，避免目录外散文件）。来源：jsdelivr 在本部署
网络不可达（实测），改经 npmmirror 抓取。产物形态：marked/DOMPurify 为
官方 ESM（render.js 静态 import）；highlight.js/mermaid 为 UMD 单文件
（hljs 经 index.html 经典 script 常载为全局，mermaid 由渲染模块按需
动态注入 script）。总增量约 2.7MB（mermaid 2.5MB 占大头）。另实测
Windows 注册表把 `.mjs` 映射为 text/plain，Starlette StaticFiles 按扩展
名猜 MIME 会导致模块脚本被浏览器拒载——api.py 导入时显式
`mimetypes.add_type("text/javascript", ".mjs"/.js)` 修正。否决 CDN：
现场与移动端网络不可控，CDN 失效将静默退化为纯文本。否决引入构建系统：
与仓库"无构建"现状冲突，vendored dist 是最小改动半径。

### D3 流式渲染：节流重渲染 + 结束时最终精确渲染

text_delta 累积到会话文本缓冲，节流间隔（约 300ms，常量可调）内用
marked+DOMPurify 重渲染当前活跃气泡；本轮文本块结束（turn_done 或后续
事件到来）时做一次最终精确渲染，修正未闭合围栏/半截表格的临时形态。
未闭合语法按纯文本兜底（宽松解析，不报错不闪烁）。滚动锚定：距底部超过
阈值即视为用户上翻，暂停自动拉底；用户回到贴底恢复跟随（保护既有
autoscroll 体验）。否决"流式纯文本、结束后一次性切换"：与"内容丰富"
诉求相悖，长回复期间信息不可读。

### D4 消毒纪律（不可妥协，地位等同方案文档 D7/D8）

- marked 产出 HTML → DOMPurify 白名单消毒 → 才可注入 DOM；白名单覆盖
  markdown 常规标签（含表格）+ mermaid 产出的 SVG 内联元素；默认拒绝
  全部事件处理器属性与 `javascript:` URI。
- mermaid 以 `securityLevel: 'strict'` 初始化（禁图内脚本、禁外部访问）。
- 任何环节失败（解析异常、消毒异常、mermaid 语法错误）一律降级：
  markdown 层降级为纯文本；mermaid 层显示原始源码 + 错误提示条。
  消毒不可按内容来源选择性跳过。
- 理由：助手内容携带用户上传文档的转述，提示注入风险面已在方案文档 D8
  认定；HTML 渲染把该风险从"展示面"升级为"执行面"，消毒+strict+CSP
  三层缺一不可。

### D5 mermaid 懒加载

常载库（marked/DOMPurify 经 ESM、highlight.js 经 UMD script）随页面加载；
mermaid（UMD 单文件约 2.5MB）仅当本会话首次出现 ```mermaid 代码块时
动态注入 script 标签加载，加载期间该代码块显示占位提示，加载完成后渲染；
渲染失败时 mermaid 会向 body 追加错误图形，渲染层负责移除（#d<id>）。
理由：多数查询类会话不产生图形，避免所有用户为首屏买单；移动端首屏
耗时敏感性高（实例池容量模型已有时间预算）。

### D6 CSP 头：api.py 内轻量 middleware

`default-src 'self'; style-src 'self' 'unsafe-inline';
img-src 'self' data:; connect-src 'self'`。`style-src 'unsafe-inline'`
为 mermaid/highlight.js 运行时内联样式所必需；`script-src` 落在
default-src 'self'（不放开内联脚本）。已核实前端无内联脚本/内联事件
处理器，SSE（EventSource/fetch）与上传下载均为同源，策略无破坏面。
否决"暂不加 CSP"：消毒被绕过时 CSP 是最后防线，成本仅一个 middleware。

### D7 模型输出约定：只改 `WEBCHAT_SYSTEM_APPEND` 文本

追加一段输出格式约定（表格用 markdown 表格语法；流程/时序/状态说明输出
mermaid 代码块；其余输出不变）。不动 SKILL.md 与 agent_assets：IDE 路径
零影响、资源包零升版。若真机验证模型遵循率不足，升资源包属后续独立变更，
不在本变更内追认。

### D8 用户消息保持纯文本

用户气泡维持 `textContent` 渲染。理由：用户输入渲染成样式会造成"我打的
字变了"的困惑，且用户输入可信度与助手内容同级（消毒也救不了语义歧义），
主流聊天产品均不渲染用户输入 markdown。

### D9 移动端宽表格：容器 `overflow-x: auto`

表格包一层横向滚动容器（CSS 实现），列超宽时气泡内横滑；不劫持消息区
纵向滚动。否决全屏查看层：交互成本高、一期先上最小方案看真机反馈（可
拆后续迭代）。

## Risks / Trade-offs

- [模型不遵循 mermaid/表格约定] → 上线前真实会话冒烟验证遵循率；不遵循
  时页面仅显示源码形态，无破坏性后果；遵循率不足再议资源包升版（不在本
  变更追认）
- [长消息节流重渲染的移动端性能] → 仅重渲染当前活跃气泡；节流常量可调；
  最终渲染一次性收尾；如真机卡顿则加大间隔或提高触发阈值
- [vendor 体积约 2.7MB 进入仓库] → mermaid UMD 单文件占 2.5MB（懒加载
  缓解首屏成本）、highlight 常载 bundle 119KB；仓库增量一次性，无运行时
  外部依赖
- [CSP 误伤未知用法] → 全端点冒烟（登录、SSE、上传、artifact 下载、
  模型清单）+ 真机截图取证；发现阻断面再按需收窄策略（仍不放开 script）
- [提示注入经消毒后仍残留钓鱼文本/链接展示] → CSP 阻断外联与脚本执行，
  白名单拒绝危险属性；文本级钓鱼属模型行为问题，超出前端渲染职责，残余
  风险记录在案（与方案文档 D8 同口径：接受展示性残余风险，阻断执行性风险）
- [mermaid 渲染 SVG 在暗色终端/投影场景可读性] → 当前应用无暗色模式，
  默认浅色主题一致；暗色模式为整体设计议题，不在此单点处理

## Migration Plan

纯增量部署：新增 `static/vendor/`、改 `app.js`/`app.css`/`index.html`/
`api.py`/`adapter.py`，重启 webchat 服务即生效；无数据迁移、无 schema
变更、事件契约不变。回滚 = 还原上述文件至实施基线提交并重启（vendored
目录整体删除），会话与数据不受影响。上线顺序：先过测试闸门（marker 断言
+CSP 头测试），再真机冒烟（PC/移动、表格/代码/图形/注入样例），通过后
合并。

## Open Questions

无——设计树九项决策已全部拍板（grill 结论），无遗留假设。
