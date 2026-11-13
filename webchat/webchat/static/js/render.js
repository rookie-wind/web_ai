// 富内容渲染模块：markdown → 白名单消毒 → HTML；代码高亮与复制；mermaid 懒加载。
//
// 消毒纪律（design D4，不可妥协）：任何由助手内容派生的 HTML 必须经
// DOMPurify 白名单消毒后才可注入 DOM；mermaid 以 strict 安全模式运行；
// 渲染/消毒失败一律降级，不吞内容、不中断事件流。

import { marked } from "/static/vendor/marked.esm.js";
import DOMPurify from "/static/vendor/purify.es.mjs";

// highlight.js 白名单语言（core 由 index.html 以 UMD 常载，全局 hljs）
const HLJS_LANGS = [
  "json", "yaml", "python", "javascript", "xml", "bash", "ini", "sql",
];

marked.use({ gfm: true, breaks: true });

// 白名单消毒配置：markdown 常规标签（含表格）+ 代码块结构 + mermaid SVG
// 元素；事件处理器属性一律不在名单（默认拒绝）；data-* 属性关闭。
const SANITIZE_OPTIONS = {
  ALLOWED_TAGS: [
    "p", "br", "strong", "em", "del", "s", "code", "pre", "blockquote",
    "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "hr",
    "table", "thead", "tbody", "tr", "th", "td",
    "a", "span", "div", "img", "button",
    "svg", "g", "path", "rect", "circle", "ellipse", "line", "polyline",
    "polygon", "text", "tspan", "marker", "defs", "style", "title",
    "lineargradient", "stop", "clippath", "use",
    // 边标签容器：mermaid v11.4.1 边标签唯一产出路径（诊断实验钉死），
    // 内部 HTML 经同一白名单递归消毒；大小写双拼保查询命中
    "foreignObject", "foreignobject",
  ],
  ALLOWED_ATTR: [
    "href", "src", "alt", "title", "class", "id",
    "colspan", "rowspan", "target", "rel", "type",
    // SVG 文本定位与基线属性：dy/dx 缺失会使多行标签整体上移漂出框外
    // （诊断实验实测）；基线类为防御后续图形类型
    "dy", "dx", "dominant-baseline", "alignment-baseline", "startoffset",
    "width", "height", "viewbox", "d", "x", "y", "x1", "y1", "x2", "y2",
    "cx", "cy", "r", "rx", "ry", "fill", "stroke", "stroke-width",
    "transform", "preserveaspectratio", "xmlns", "xmlns:xlink",
    "markerwidth", "markerheight", "refx", "refy", "orient", "overshoot",
    "text-anchor", "font-family", "font-size", "font-weight", "font-style",
    "points", "offset", "stop-color", "stop-opacity", "gradientunits",
    "gradienttransform", "clip-path", "opacity", "fill-opacity", "aria-label",
    "role", "rel",
  ],
  ALLOW_DATA_ATTR: false,
};

// HTML 语境消毒选项：仅用于 foreignObject 内部片段的回填消毒
// （DOMPurify 3.1.7 在 SVG 语境会掏空 foreignObject 的 HTML 子树，实测）
const HTML_SANITIZE_OPTIONS = {
  ALLOWED_TAGS: ["div", "span", "p", "br", "strong", "em", "b", "i", "code"],
  ALLOWED_ATTR: ["class", "title"],
};

function sanitizeMermaidSvg(rawSvg) {
  // 两段式消毒（design D2 补充）：① SVG 整体过白名单（foreignObject 壳
  // 保留、子树被 DOMPurify 掏空）；② 从原文按文档序摘出各 foreignObject
  // 的 HTML 内容，逐段按 HTML 语境消毒后回填空壳。每一段都过 DOMPurify，
  // 消毒纪律不降级；数量对不上时保留空壳（降级为边标签缺失，不冒险）。
  const rawDoc = new DOMParser().parseFromString(rawSvg, "text/html");
  const rawFo = Array.from(rawDoc.querySelectorAll("foreignObject"));
  const holder = document.createElement("div");
  holder.innerHTML = DOMPurify.sanitize(rawSvg, SANITIZE_OPTIONS);
  const shells = holder.querySelectorAll("foreignObject");
  shells.forEach((shell, i) => {
    const raw = rawFo[i];
    if (!raw || shell.childElementCount > 0) { return; }
    shell.innerHTML = DOMPurify.sanitize(raw.innerHTML, HTML_SANITIZE_OPTIONS);
  });
  return holder.innerHTML;
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// 代码块自定义渲染：mermaid 围栏保留源码待增强；其余经 hljs 高亮并附复制按钮。
// 表格外包 .table-wrap（横向滚动容器，design D9：宽表格气泡内横滑）
const renderer = {
  table(header, body) {
    return (
      `<div class="table-wrap"><table><thead>${header}</thead>`
      + `<tbody>${body}</tbody></table></div>`
    );
  },

  code(code, infostring) {
    const lang = (infostring || "").trim().split(/\s+/)[0].toLowerCase();
    if (lang === "mermaid") {
      return `<div class="mermaid-src"><pre><code>${escapeHtml(code)}</code></pre></div>`;
    }
    const hljs = window.hljs;
    let body = escapeHtml(code);
    let shownLang = lang || "text";
    if (hljs) {
      try {
        if (lang && hljs.getLanguage(lang)) {
          body = hljs.highlight(code, { language: lang }).value;
        } else {
          shownLang = "text";
          body = hljs.highlightAuto(code, HLJS_LANGS).value;
        }
      } catch (_) {
        body = escapeHtml(code);
      }
    }
    return (
      `<div class="code-block">`
      + `<div class="code-bar"><span class="code-lang">${escapeHtml(shownLang)}</span>`
      + `<button type="button" class="btn-code-copy">复制</button></div>`
      + `<pre><code class="hljs language-${escapeHtml(shownLang)}">${body}</code></pre>`
      + `</div>`
    );
  },
};

marked.use({ renderer });

// markdown → 消毒 → HTML 串；解析或消毒失败由调用方降级纯文本
export function renderAgentHtml(text) {
  const raw = marked.parse(String(text || ""));
  return DOMPurify.sanitize(raw, SANITIZE_OPTIONS);
}

// ── mermaid：懒加载（同源 vendor UMD）+ strict 初始化 + 逐块渲染 ──

let mermaidLoading = null;
let mermaidSeq = 0;

function loadMermaid() {
  if (window.mermaid) { return Promise.resolve(window.mermaid); }
  if (!mermaidLoading) {
    mermaidLoading = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = "/static/vendor/mermaid.min.js";
      s.onload = () => {
        try {
          // strict：禁图内脚本与外部访问（web-ui-content-security 契约）；
          // htmlLabels 顶层 false 用 <text> 渲染标签、避免 foreignObject。
          // 注意：v11.4.1 忽略 flowchart.htmlLabels（实测），必须放顶层
          window.mermaid.initialize({
            startOnLoad: false,
            securityLevel: "strict",
            theme: "default",
            htmlLabels: false,
            // 布局密度收紧（design D3）：同图自然宽下降，更多图落入缩放适配区间
            flowchart: { nodeSpacing: 30, rankSpacing: 35, padding: 8 },
            themeVariables: { fontSize: "13px" },
          });
          resolve(window.mermaid);
        } catch (err) { reject(err); }
      };
      s.onerror = () => reject(new Error("mermaid resource load failed"));
      document.head.appendChild(s);
    });
  }
  return mermaidLoading;
}

function addBar(block, cls, msg) {
  const bar = document.createElement("div");
  bar.className = cls;
  bar.textContent = msg;
  block.prepend(bar);
  return bar;
}

function dropBar(block) {
  const bar = block.querySelector(".mermaid-bar");
  if (bar) { bar.remove(); }
}

function markMermaidError(block, msg) {
  block.classList.remove("mermaid-loading");
  dropBar(block);
  block.classList.add("mermaid-error");
  if (!block.querySelector(".mermaid-error-bar")) {
    addBar(block, "mermaid-error-bar", msg);
  }
}

// ── 阈值混合适配（design D1）：中小图缩放适配看全，超宽图横滚 + 提示 ──

const FIGURE_FIT_MAX_WIDTH = 700;

function applyFigureFit(container) {
  // mermaid 给 SVG 写内联 max-width:<自然宽>（内联样式压过样式表），
  // 以此推导自然宽：≤阈值清除内联限制缩放适配；>阈值保留横滚并提示。
  const svgEl = container.querySelector("svg");
  if (!svgEl) { return; }
  // 消毒器会剥掉 svg 的 style 属性，自然宽从 viewBox 取（mermaid 恒有 viewBox，
  // 其宽度即图形自然宽的 px 值）
  let natural = parseFloat(svgEl.style.maxWidth);
  if (!Number.isFinite(natural)) {
    const vb = (svgEl.getAttribute("viewBox") || "").split(/\s+/);
    natural = parseFloat(vb[2]);
  }
  if (Number.isFinite(natural) && natural <= FIGURE_FIT_MAX_WIDTH) {
    svgEl.style.maxWidth = "none";
    svgEl.style.width = "100%";
    return;
  }
  // 超阈值：强制自然宽渲染（对抗 mermaid 的 width="100%" 与样式表
  // max-width:100% 的压缩），容器 overflow-x:auto 才能真正横滚
  svgEl.style.maxWidth = "none";
  svgEl.style.width = natural + "px";
  svgEl.style.height = "auto";
  container.classList.add("is-scrollable");
  const hint = document.createElement("div");
  hint.className = "figure-scroll-hint";
  hint.textContent = "↔ 左右滑动查看";
  container.after(hint);
  container.addEventListener("scroll", () => {
    hint.style.opacity = "0";
    setTimeout(() => hint.remove(), 500);
  }, { once: true, passive: true });
}

// 扫描 root 内未处理的 mermaid 源码块：加载中显示占位，成功替换为 SVG，
// 失败保留源码 + 错误提示条（不吞内容）。异步 fire-and-forget 由调用方发起。
export async function enhanceMermaidBlocks(rootEl) {
  if (!rootEl) { return; }
  const items = Array.from(
    rootEl.querySelectorAll(".mermaid-src:not([data-rendered])"),
  ).map((b) => ({ el: b, code: b.textContent || "" }));
  if (!items.length) { return; }
  for (const item of items) {
    item.el.dataset.rendered = "1";
    item.el.classList.add("mermaid-loading");
    addBar(item.el, "mermaid-bar", "图形渲染加载中…");
  }
  let mermaid;
  try {
    mermaid = await loadMermaid();
  } catch (_) {
    for (const item of items) {
      markMermaidError(item.el, "图形渲染库加载失败，已显示源码");
    }
    return;
  }
  for (const item of items) {
    item.el.classList.remove("mermaid-loading");
    dropBar(item.el);
    const id = `mermaid-svg-${++mermaidSeq}`;
    try {
      const { svg } = await mermaid.render(id, item.code);
      const holder = document.createElement("div");
      holder.className = "mermaid-figure";
      holder.innerHTML = sanitizeMermaidSvg(svg);
      item.el.replaceWith(holder);
      applyFigureFit(holder);
    } catch (_) {
      // mermaid 渲染失败会向 body 追加错误图形（#d<id>），移除避免污染页面
      const bomb = document.getElementById(`d${id}`);
      if (bomb) { bomb.remove(); }
      markMermaidError(item.el, "图形渲染失败：mermaid 语法无法解析，已显示源码");
    }
  }
}
