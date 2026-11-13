# polish-webchat-figure-and-composer — 任务

> 铁律（不可协商）：无失败测试不得写实现；无转绿测试不得勾选完成。
> 每个实现 task 的通过标准 = 对应测试由红转绿；validate 仅校验 delta
> 结构，不替代测试。拆分方案经人工确认后才进入 /opsx-apply 实施。

## 1. 测试先行（先写失败测试，保持红）

- [x] 1.1 `test_static_frontend.py` 补白名单 marker 断言：render.js 的
  `ALLOWED_ATTR` 含 `dy`/`dx`，`ALLOWED_TAGS` 含 `foreignObject`。验证
  方式：该测试红
- [x] 1.2 `test_static_frontend.py` 补阈值适配 marker 断言：render.js 含
  `FIGURE_FIT_MAX_WIDTH` 常量与清除内联 `max-width` 的归一化逻辑、
  `is-scrollable` 提示类；app.css 含 `.is-scrollable` 渐隐/提示条样式。
  验证方式：该测试红
- [x] 1.3 `test_static_frontend.py` 补 composer 紧凑 marker 断言：
  app.js/index.html 含占位符双态（失焦短文案 + focus 展开完整释义）、
  textarea 初始 1 行与 120px 上限；app.css 含紧凑间距与 16px 底线保留
  （`font-size: 16px` 断言仍在）。验证方式：该测试红
- [x] 1.4 `test_static_frontend.py` 补系统提示约定断言：adapter.py 的
  `WEBCHAT_SYSTEM_APPEND` 含图布局紧凑规则关键字（TB 方向 / 泳道 / ≤10 字
  语义文本）。验证方式：该测试红

## 2. 消毒白名单补全（render.js）

- [x] 2.1 `ALLOWED_ATTR` 增加 `dy`/`dx`/`dominant-baseline`/
  `alignment-baseline`/`startoffset`；`ALLOWED_TAGS` 增加 `foreignObject`。
  通过标准：1.1 转绿；既有消毒相关测试无回归
- [x] 2.2 渲染密度收紧：mermaid initialize 增加 `flowchart: { nodeSpacing:
  30, rankSpacing: 35, padding: 8 }` 与 `themeVariables: { fontSize:
  "13px" }`（保留顶层 htmlLabels:false）。通过标准：随 5.x 冒烟验证同图
  自然宽下降；静态测试无回归

## 3. 图阈值混合适配（render.js / app.css）

- [x] 3.1 `enhanceMermaidBlocks` 渲染后归一化：读 SVG 内联 `max-width`
  推导自然宽，≤ `FIGURE_FIT_MAX_WIDTH`(700) 时移除内联 max-width 并置
  width:100%（缩放适配），>700 保留横滚并给容器加 `is-scrollable` +
  注入一次性"左右滑动查看"提示条。通过标准：1.2 转绿；模块内两分支
  行为可测
- [x] 3.2 `app.css` 增加 `.is-scrollable` 边缘渐隐与提示条样式（含提示条
  滑动后淡出）。通过标准：1.2 对应断言转绿；design token 断言仍绿

## 4. composer 移动端紧凑化（app.js / index.html / app.css）

- [x] 4.1 占位符双态：index.html 初始 placeholder 改短文案；app.js 增加
  focus/blur 切换逻辑（focus 展开完整释义、blur 恢复短文案，输入非空时
  blur 不覆盖已输入内容的占位行为）。通过标准：1.3 对应断言转绿
- [x] 4.2 紧凑样式：textarea 初始 rows=1、auto-grow 上限 160→120px；
  `.compose` 内边距、按钮高度（34→30px）、模型下拉 max-width 收紧；全部
  表单控件保持 ≥16px。通过标准：1.3 转绿；`test_static_frontend.py` 既有
  16px 反缩放断言与 composer 结构断言无回归

## 5. 系统提示布局约定（adapter.py）

- [x] 5.1 `WEBCHAT_SYSTEM_APPEND` 追加图布局紧凑规则文本（TB 方向、泳道
  ≤3、节点文案 ≤10 字、宽度有限图宜紧凑）。通过标准：1.4 转绿；git diff
  确认 SKILL.md 与 agent_assets 零改动

## 6. 集成验证与取证

- [x] 6.1 webchat 全量 pytest 回归通过，无跳过、无未转绿
- [x] 6.2 浏览器冒烟（dev_smoke_server"大图/流程图/坏图"分支）：多行 CJK
  标签逐行居中在节点框内（bbox 判定）、边标签文字可见、≤700 图缩放适配
  无裁切、>700 图横滚且提示条出现；foreignObject 内 script/onerror 注入
  样例被递归消毒；截图取证至 `.screenshots/`
- [x] 6.3 移动端（375 同源 iframe 仿真）冒烟：composer 高度量化对比（记录
  改动前后数值）、占位符聚焦展开/失焦紧凑行为、16px 契约保持、宽表格
  回归不受影响；截图取证

## 7. 收尾

- [x] 7.1 归档前核对：proposal 的 Modified Capabilities 与 delta 文件一一
  对应（web-chat-ui / agent-runtime-session）；`openspec validate --strict`
  通过。判据：validate 输出无 error
