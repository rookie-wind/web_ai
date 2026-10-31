# HTML PPT Studio 技能

> 从 https://github.com/lewislulu/html-ppt-skill 安装

## 概述

HTML PPT Studio 是一个专业的 HTML 演示文稿制作技能，支持：

- **36 个主题** — minimal-white, editorial-serif, soft-pastel, sharp-mono, arctic-cool, sunset-warm, catppuccin-latte/mocha, dracula, tokyo-night, nord, solarized-light, gruvbox-dark, rose-pine, neo-brutalism, glassmorphism, bauhaus, swiss-grid, terminal-green, xiaohongshu-white, rainbow-gradient, aurora, blueprint, memphis-pop, cyberpunk-neon, y2k-chrome, retro-tv, japanese-minimal, vaporwave, midcentury, corporate-clean, academic-paper, news-broadcast, pitch-deck-vc, magazine-bold, engineering-whiteprint
- **15 个完整 deck 模板** — 包含 8 个真实项目提取的风格和 7 个场景脚手架
- **36 种页面布局** — cover, toc, section-divider, bullets, two-column, three-column, big-quote, stat-highlight, kpi-grid, table, code, diff, terminal, flow-diagram, timeline, roadmap, mindmap, comparison, pros-cons, todo-checklist, gantt, image-hero, image-grid, chart-bar, chart-line, chart-pie, chart-radar, arch-diagram, process-steps, cta, thanks 等
- **27 个 CSS 动画** + **20 个 Canvas FX 动画**
- **演讲者模式** — 支持逐字稿、计时器、像素级预览
- **键盘导航** — 方向键、全屏、主题切换、动画演示等
- **触摸导航** — 支持手机/平板左右滑动

## 安装位置

```
.qoder/skills/html-ppt/
```

## 包含的文件

- `SKILL.md` — 技能主文件
- `references/` — 详细文档
  - `themes.md` — 36 个主题说明
  - `layouts.md` — 36 种布局说明
  - `animations.md` — 47 个动画说明
  - `full-decks.md` — 15 个完整 deck 模板
  - `presenter-mode.md` — 演讲者模式指南
  - `authoring-guide.md` — 完整创作指南
- `assets/` — CSS、JS、主题、动画资源
- `templates/` — 模板文件
- `scripts/` — 脚手架和渲染脚本
- `examples/` — 示例 deck

## 使用方法

在 Qoder 中，你可以直接说：

- "做一份 8 页的技术分享 slides，用 cyberpunk 主题"
- "turn this outline into a pitch deck"
- "做一个小红书图文，9 张，白底柔和风"
- "帮我做一份 PPT"
- "创建演讲稿"

技能会自动触发并引导你完成演示文稿的制作。

## 快速开始

### 1. 创建新 deck

```bash
# 从基础模板创建
./scripts/new-deck.sh my-talk

# 从完整 deck 模板创建
./scripts/new-deck.sh my-talk -t pitch-deck
```

### 2. 浏览资源

```bash
# 浏览所有 36 个主题
open templates/theme-showcase.html

# 浏览所有 36 种布局
open templates/layout-showcase.html

# 浏览所有 47 个动画
open templates/animation-showcase.html

# 浏览所有 15 个完整 deck
open templates/full-decks-index.html
```

### 3. 渲染为 PNG

```bash
# 单页渲染
./scripts/render.sh templates/single-page/kpi-grid.html

# 多页渲染
./scripts/render.sh examples/demo-deck/index.html 8
```

## 键盘快捷键

```
← → Space PgUp PgDn Home End   导航
F                               全屏
S                               打开演讲者窗口
N                               快速笔记
R                               重置计时器
O                               幻灯片概览
T                               切换主题
A                               切换动画演示
#/N                             深链接到第 N 页
```

## 离线使用

技能完全支持离线使用。唯一的远程依赖是 `assets/fonts.css` 中的 Google Fonts 导入。离线时，浏览器会自动回退到系统字体栈。

## 许可证

MIT © 2026 lewis <sudolewis@gmail.com>

## 原始仓库

https://github.com/lewislulu/html-ppt-skill
