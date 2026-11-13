# polish-webchat-figure-and-composer — 设计

## Context

前序变更 `add-webchat-rich-rendering` 已实现 mermaid 渲染、消毒纪律与 CSP，
但真机反馈两个体验缺陷并暴露两个白名单缺口（均已做页面内对照实验定位）：

- 裁切机制：mermaid 给 SVG 写内联样式 `max-width:<自然宽>px`，内联样式优先
  于样式表 `max-width:100%` → SVG 按自然宽渲染 → 容器 `overflow-x:auto`
  横滚但 iOS 隐藏滚动条 → 用户看到的是静默裁切。
- 文字漂框机制（诊断报告已钉死）：DOMPurify 白名单缺 `dy` → 多行标签整体
  上移 1.1em（实测 4/4 节点 -24px 溢出，原始渲染全部框内 +1px）；缺
  `foreignObject` → v11.4.1 边标签（即使顶层 htmlLabels:false 仍走
  foreignObject 路径）被整体剥空。
- composer 占高：两行长占位文案 + textarea 初始 2 行 + 工具栏间距；spec
  契约"移动端表单控件 ≥16px"不可降字号。

## Goals / Non-Goals

**Goals:**

- 中小图零操作"看全"，超宽图横滚可发现（阈值混合策略）
- 图形文本完整：节点标签在框内、边标签可见
- composer 移动端纵向高度收紧约 40~60px
- 模型侧布局约定降低未来图的生成宽度

**Non-Goals:**

- 不做点图全屏查看层（留后续迭代）
- 不做图内双指缩放（页面级捏合缩放本就可用，未禁用）
- 不改 vendored 资产清单与事件契约；不动 SKILL.md/资源包

## Decisions

### D1 阈值混合适配：清除内联 max-width + 700px 阈值

渲染后（`enhanceMermaidBlocks` 拿到 holder 时）读 SVG 的内联 `max-width`
推导自然宽：≤ `FIGURE_FIT_MAX_WIDTH = 700` → 移除内联 max-width 并置
`width:100%`（缩放适配，配合既有 `height:auto`）；> 700 → 保留自然宽横滚，
并在容器加 `is-scrollable` 类驱动可发现性提示（CSS 渐隐边缘 + 一次性
"左右滑动查看"提示条，滑动后淡出）。700px 依据：移动端气泡宽约 300~350px，
700px 内缩放比 ≥ 0.43，13px 字号缩后 ≥ 5.6px 仍可辨认大义；超 700 缩后
不可读，横滚保真更好。桌面端气泡 720px，绝大多数图 ≤700 直接适配。

### D2 白名单补全：`dy`/`dx` 必加，`foreignObject` 有条件接受

- `ALLOWED_ATTR` += `dy`、`dx`：定位属性，纯缺陷修复，无安全增量。
- `ALLOWED_TAGS` += `foreignObject`：边标签唯一产出路径（诊断实验：原始
  输出 3 个 foreignObject 边标签、htmlLabels:false 对其不生效）。安全论证：
  DOMPurify 对 foreignObject **内部 HTML 递归消毒**（同一白名单，script/
  事件处理器/外链照剥）+ mermaid `securityLevel:strict` + CSP
  `script-src 'self'` 三层不变；新增面仅"模型生成的富文本标签按白名单
  展示"，与节点 `<text>` 同级。`style` 标签已在白名单（图形配色必需）。
- 顺带核对本图实测不需要但同类图可能用的属性：`dominant-baseline`、
  `alignment-baseline`、`startoffset` 一并加入（防御后续图形类型）。

### D3 渲染密度收紧：initialize 参数

`flowchart: { nodeSpacing: 30, rankSpacing: 35, padding: 8 }` +
`themeVariables: { fontSize: "13px" }`（同图自然宽预计降 20~30%，叠加
D1 后更多图落入缩放适配区间）。保留顶层 `htmlLabels: false`（节点标签
`<text>` 路径），边标签按 D2 白名单放行。配置作用域仅 webchat 渲染层。

### D4 模型侧布局约定：`WEBCHAT_SYSTEM_APPEND` 增补

追加一句约定："图布局紧凑规则：流程图默认 TB（上下）方向；并行分支/泳道
尽量不超过 3 列；节点文案尽量精简（≤10 字），不要在单节点内写长句；Web
页面展示宽度有限，图越紧凑越可读。" 不动 SKILL.md 与资源包（与 D7 同
口径，遵循率不足再议资源包升版）。

### D5 composer 紧凑化：聚焦展开占位符

- 占位符双态：失焦短文案 `"输入消息，Enter 发送；可选前缀 /web /xlpa"`；
  聚焦切换为完整长文案（含"强制网页检索/强制协议助手/不带前缀自动判断"
  释义）——满足 MODIFIED 后的 spec（语义可达 + 紧凑形态）。
- textarea 初始 `rows=1`，自适应增高上限 160→120px；`#msg-input` input
  逻辑已有 auto-grow，仅改参数。
- 间距收紧：`.compose` 上下 padding、`.attach-btn`/`#btn-send` 高度
  34→30px、模型下拉 max-width 180→150px；字号全部保持 ≥16px（移动端
  媒体查询内）不动。
- hint 短文案仍含 `/web`/`/xlpa` 关键字（spec 场景"失焦紧凑"判据）。

## Risks / Trade-offs

- [foreignObject 白名单放宽被误读为消毒降级] → spec 已钉"防线 MUST NOT
  放宽"；冒烟含 foreignObject 内 script/onerror 注入样例验证递归消毒；
  文档记录该决定与论证
- [700px 阈值一刀切对个别图不适] → 常量可调；真机反馈再校准
- [占位符聚焦展开在 iOS 上触发键盘后视觉跳动] → 切换仅改 placeholder 文本
  不改布局尺寸，跳动可控；真机冒烟覆盖
- [模型侧约定遵循率不确定] → 与 D7 同口径：冒烟观察，不足再议资源包升版
- [渲染密度收紧导致个别图布局更挤] → 值域温和（50→30/35），降级余地大
- [泳道大图自然宽 SVG 撑宽气泡至 720 上限，消息区出现约 59px 嵌套横滚
  （冒烟实测：页面级无溢出、内容全部可达）] → 外观级观察项，真机反馈后
  再定（候选：figure 强制 display:block 或收缩 bubble 上限），一期不改

## Migration Plan

纯前端 + 提示文本增量：改 render.js/app.js/index.html/app.css/adapter.py，
重启 webchat 服务生效；无数据迁移。回滚 = 还原上述文件至实施基线。上线
顺序：红测 → 实现 → webchat 全量 pytest → 浏览器冒烟（PC + 375 iframe
仿真：文字在框内、边标签可见、阈值两分支行为、composer 高度量化对比）。

## Open Questions

无——设计树六项决策已全部拍板（grill 结论），无遗留假设。
