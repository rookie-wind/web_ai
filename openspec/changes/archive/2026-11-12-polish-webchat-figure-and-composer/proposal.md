# polish-webchat-figure-and-composer

## Why

富渲染上线后的真机反馈两个体验缺陷：①泳道式 mermaid 大图在移动端左右被裁
（mermaid 给 SVG 写内联 `max-width:<自然宽>` 压过样式表的 `max-width:100%`，
容器横滚但 iOS 隐藏滚动条，滑动能力不可发现）；②composer 在移动端占高过大
（两行长占位文案 + 初始 2 行 textarea + 工具栏间距），挤压消息区。另发现
消毒白名单两个缺口导致图形文字排版损坏：`dy` 被剥使多行 CJK 标签整体上移
1.1em 顶出节点框；`foreignObject` 被剥使 mermaid v11.4.1 的**边标签**整体
消失（该版本对边标签不走 htmlLabels:false 路径，页面内对照实验已钉死）。

## What Changes

- 图窄屏适配策略（阈值混合）：mermaid 渲染后清除内联 `max-width`——自然宽
  ≤ 阈值（约 700px）的中小图强制缩放适配容器宽（"看全"）；超阈值大图保留
  横滚 + 增加可发现性提示（渐隐边缘 / "左右滑动查看"提示条）
- 渲染层布局密度收紧：mermaid initialize 收紧 nodeSpacing/rankSpacing、
  padding 与 fontSize，同图自然宽下降约 20~30%
- 模型侧布局约定：`WEBCHAT_SYSTEM_APPEND` 增补图布局紧凑规则（流程图默认
  TB 方向、并行分支/泳道 ≤3、节点文案 ≤10 字、Web 展示宽度有限图宜紧凑）
- 消毒白名单补全：`ALLOWED_ATTR` 增加 `dy`/`dx`（多行标签定位）；`ALLOWED_TAGS`
  增加 `foreignObject`（边标签容器；其内部 HTML 由 DOMPurify 递归消毒，
  mermaid strict + CSP 防线不变）
- composer 移动端紧凑化：占位提示改单行短文案（聚焦时切换为含完整前缀释义
  的长文案）、textarea 初始 1 行（自适应增高保留，上限 160→120px）、输入区
  与工具栏内边距收紧；表单控件 ≥16px 字号契约不变
- 历史回放路径随同一渲染管线自动获得上述行为，无需单独处理

## Capabilities

### New Capabilities

（无——全部落在既有能力上）

### Modified Capabilities

- `web-chat-ui`: 新增 Requirement「图在窄屏必须阈值混合适配」（缩放适配与
  横滚兜底的判据与可发现性提示）与「mermaid 图形文本必须完整呈现」（节点
  标签居中于框内、边标签文字可见、SVG 定位属性与消毒后 foreignObject 容器
  必须在白名单内）；MODIFIED「输入区必须提示可选路由前缀且不得强制」——
  提示文案允许紧凑短形态（失焦时），完整释义 MUST 在聚焦时经占位符展示，
  前缀可选语义与"不带前缀自动判断"说明不变
- `agent-runtime-session`: 新增 Requirement「Web 会话系统提示必须约定图
  布局紧凑规则」——`WEBCHAT_SYSTEM_APPEND` 增补 TB 方向优先、泳道 ≤3、
  节点文案精简的输出约定；与既有富内容输出格式约定并存、互不替代

## Impact

- `webchat/webchat/static/js/render.js`：SANITIZE_OPTIONS 补全；渲染后 SVG
  尺寸归一化（阈值判断 + 清除/保留内联 max-width）+ 提示条注入；mermaid
  initialize 布局密度参数
- `webchat/webchat/static/js/app.js` / `static/index.html` / `static/app.css`：
  composer 占位符聚焦展开逻辑、初始行数与上限、紧凑样式
- `webchat/webchat/sdk_runtime/adapter.py`：`WEBCHAT_SYSTEM_APPEND` 增补
  布局紧凑约定文本
- `webchat/tests/`：marker 断言与冒烟取证同步扩展
- 不改事件契约、后端存储、vendored 资产清单（无新库）、vendor 文件本身
- 铁律：无失败测试不得写实现；无转绿测试不得勾 task
