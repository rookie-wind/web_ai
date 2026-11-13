# add-webchat-rich-rendering — 任务

> 铁律（不可协商）：无失败测试不得写实现；无转绿测试不得勾选完成。
> 每个实现 task 的通过标准 = 对应测试由红转绿；validate 仅校验 delta
> 结构，不替代测试。拆分方案经人工确认后才进入 /opsx-apply 实施。

## 1. 测试先行（先写失败测试，全部保持红）

- [x] 1.1 新建 `webchat/tests/test_content_security.py`：断言 `/`、
  `/static/app.css`、`/static/js/app.js` 响应头含
  `Content-Security-Policy`，且 script 指令仅同源（无 `unsafe-inline`
  于 script、无 `data:`/外部主机脚本源）。验证方式：`pytest tests/test_content_security.py` 全红
- [x] 1.2 `test_static_frontend.py` 补 vendored 资产断言：index.html
  引用 `/static/vendor/` 下 marked/DOMPurify/highlight.js 且
  `index.html` 与 `app.js` 无外部 CDN 引用；vendor 文件头含来源与版本
  注释。验证方式：该测试红（文件尚不存在）
- [x] 1.3 `test_static_frontend.py` 补渲染管线 marker 断言：app.js 含
  消毒链（marked 产出→DOMPurify→注入）、mermaid
  `securityLevel: 'strict'`、mermaid dynamic `import()` 懒加载、节流渲染
  常量与最终精确渲染入口、用户消息仍走 `textContent`、代码块复制按钮、
  上翻暂停自动拉底的滚动锚定判定。验证方式：该测试红
- [x] 1.4 `test_static_frontend.py` 补系统提示约定断言：adapter.py 的
  `WEBCHAT_SYSTEM_APPEND` 含「markdown 表格」「mermaid 代码块」输出约定
  文本。验证方式：该测试红

## 2. vendored 资产落地

- [x] 2.1 获取 marked、DOMPurify、highlight.js（core + 白名单语言：
  json/yaml/python/javascript/xml/bash/ini/sql）、mermaid（ESM）压缩版
  dist 放入 `webchat/webchat/static/vendor/`，每文件头注释来源 URL 与
  版本号。通过标准：1.2 vendored 断言转绿，文件存在且体积符合预期
  （mermaid 约 1MB 量级）
- [x] 2.2 `index.html` 经典 script 常载 highlight.js（UMD）；
  marked/DOMPurify 由 render.js 以 ESM 静态 import（mermaid 留给渲染
  模块动态注入）。通过标准：2.2 随 4.x 转绿；本地加载页面无 404、
  无外部网络请求（DevTools 网络面板）

## 3. CSP middleware

- [x] 3.1 `webchat/api.py` 增加响应头 middleware，对全部响应下发 CSP：
  `default-src 'self'; style-src 'self' 'unsafe-inline';
  img-src 'self' data:; connect-src 'self'`。通过标准：1.1 转绿；
  webchat 全量既有 pytest 无回归（登录/SSE/上传/下载端点不受影响）

## 4. 前端渲染管线（app.js / app.css）

- [x] 4.1 新增渲染模块：marked（GFM + `breaks: true`）→ DOMPurify
  白名单消毒 → 注入；代码块经 highlight.js core+白名单语言着色并附复制
  按钮（复制内容与源码一致）。通过标准：1.3 消毒链/高亮/复制 marker
  转绿；渲染或消毒异常时降级纯文本（模块内测试断言）
- [x] 4.2 `app.js` text_delta 分支改造：助手文本累积缓冲 + 约 300ms
  节流重渲染活跃气泡 + 本轮文本块结束时最终精确渲染；用户消息分支保持
  `textContent` 纯文本；滚动锚定：距底超阈值暂停自动拉底、贴底恢复跟随。
  通过标准：1.3 对应 marker 转绿；`tests/test_static_frontend.py` 既有
  断言（turn 串行、guard、上传等）无回归
- [x] 4.3 mermaid 渲染：检测 ```mermaid 围栏 → 懒加载 script 注入 →
  加载 → `securityLevel: 'strict'` 渲染；解析失败显示原始源码 + 错误
  提示条；加载中显示占位。通过标准：1.3 mermaid marker 转绿；降级路径
  断言通过（不吞内容、不中断后续事件）
- [x] 4.4 `app.css` 新增样式：表格横向滚动容器（`overflow-x: auto`，
  移动端横滑不撑破气泡）、代码块与复制按钮、mermaid 容器、错误提示条；
  保持既有 design token（`--space-`/`--text-`/`--radius-`/`--shadow-`）。
  通过标准：`test_static_frontend.py` 的 design token 断言仍绿；真机
  视口截图无横向溢出

## 5. 系统提示输出约定

- [x] 5.1 `adapter.py` 的 `WEBCHAT_SYSTEM_APPEND` 追加输出格式约定：
  结构化数据与点表用 markdown 表格语法；流程/时序/状态说明输出 mermaid
  代码块。通过标准：1.4 转绿；`git diff` 确认 SKILL.md 与 agent_assets
  零改动（IDE 路径不受影响的静态证据）

## 6. 集成验证与取证（跨 task 的系统行为验证）

- [x] 6.1 webchat 全量 pytest 回归通过（含新增
  `test_content_security.py`），无跳过、无未转绿
- [x] 6.2 真实会话冒烟（dev_smoke_server 或真实后端）：助手回复含
  markdown 表格、代码块、mermaid 流程图、注入样例
  （`<script>`/`<img onerror>`）各一，截图取证至 `.screenshots/`；
  判据：表格/图形正常渲染、注入样例无脚本执行无外部请求、mermaid 语法
  错误样例降级为源码+提示条
- [x] 6.3 移动端视口（iPhone 尺寸）冒烟：宽表格气泡内横滑、首屏加载
  时序正常（mermaid 懒加载不阻塞）、CSP 对登录/SSE/上传/下载无误伤。
  判据：截图取证 + 浏览器控制台无 CSP 违规报告

## 7. 收尾

- [x] 7.1 归档前核对：proposal 的 Modified Capabilities 与 delta 文件
  一一对应（web-chat-ui / agent-runtime-session / web-ui-content-security）；
  `openspec validate --strict` 通过。判据：validate 输出无 error
