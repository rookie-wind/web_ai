"""PDF 结构化抽取：正文块 + 表格转 GFM Markdown，按物理页留锚点。

对应变更 pdf-extract-pymupdf-markdown 的 D1/D4/D6：

- 逐页先 `find_tables()`，落在表格 bbox 内的文本块从正文剔除，
  避免同一段文字在正文与表格中重复出现；
- 表格转 GitHub 风格 Markdown（表头行 + 分隔行 + 数据行），
  单元格内换行/多空格合并为一，竖线转义，列数按最宽行补齐；
- 每个非空页以 `## 第 N 页` 锚点分隔，供下游产物标注来源页；
- 依赖 PyMuPDF 采用惰性导入：未安装时抛 `ImportError`，由上传端点
  显式降级为 warning，绝不静默假装已提取。
"""

from __future__ import annotations

__all__ = [
    "extract_pdf_markdown",
    "extract_pdf_pages_markdown",
    "table_to_markdown",
]

import re
from pathlib import Path

# 命中任一关键词即认为首行是表头（工业点表/协议表的常见列名）。
_HEADER_KEYS = (
    "地址", "名称", "类型", "参数", "偏移", "序号", "R/W", "备注",
    "数据", "功能", "解释", "字长",
)


def clean_cell(value: object) -> str:
    """清洗单元格：合并空白、转义竖线，None 归空。"""
    if value is None:
        return ""
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text.replace("|", "\\|")


def is_header_row(row: list[str]) -> bool:
    """判断首行是否为表头（含常见表头关键词）。"""
    joined = "".join(row)
    return any(key in joined for key in _HEADER_KEYS)


def table_to_markdown(raw_rows: list[list[object]]) -> str:
    """把二维行数组转为 GFM 表格字符串。

    Args:
        raw_rows: 表格抽取结果（每行一个单元格列表，允许行长不齐）。

    Returns:
        Markdown 表格文本；无有效数据行时返回空串。
    """
    rows = [[clean_cell(cell) for cell in row] for row in raw_rows if row]
    rows = [row for row in rows if any(cell for cell in row)]
    if not rows:
        return ""
    ncol = max(len(row) for row in rows)
    for row in rows:
        row += [""] * (ncol - len(row))
    if is_header_row(rows[0]):
        header, body = rows[0], rows[1:]
    else:
        header = [f"列{i + 1}" for i in range(ncol)]
        body = rows
    lines = ["| " + " | ".join(header) + " |",
             "| " + " | ".join(["---"] * ncol) + " |"]
    lines += ["| " + " | ".join(row) + " |" for row in body]
    return "\n".join(lines)


def _page_prose(page: "pymupdf.Page", table_bboxes: list) -> str:
    """取页内落在表格区域之外的文本块，作为正文。"""
    texts: list[str] = []
    for x0, y0, x1, y1, text, _no, btype in page.get_text("blocks"):
        if btype != 0:
            continue
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        if any(bx0 <= cx <= bx1 and by0 <= cy <= by1
               for bx0, by0, bx1, by1 in table_bboxes):
            continue
        seg = re.sub(r"\s+", " ", text).strip()
        if seg:
            texts.append(seg)
    return "\n\n".join(texts)


def extract_pdf_pages_markdown(
    path: Path, first_page: int = 1, last_page: int | None = None
) -> str:
    """抽取指定物理页区间（1-based，闭区间）为 Markdown。

    Args:
        path: PDF 文件路径。
        first_page: 起始页码（含）。
        last_page: 结束页码（含）；None 表示到末页。

    Returns:
        Markdown 文本；页序保留并在锚点名中体现实际物理页码。

    Raises:
        ImportError: 运行环境未安装 PyMuPDF。
        Exception: 文件无法解析等抽取错误，由调用方显式降级。
    """
    import pymupdf

    doc = pymupdf.open(str(path))
    try:
        start = max(1, first_page)
        end = doc.page_count if last_page is None else min(doc.page_count,
                                                            last_page)
        parts: list[str] = [
            f"<!-- 源文件: {path.name} | 共 {doc.page_count} 页，"
            f"抽取第 {start}-{end} 页（PyMuPDF，表格转 GFM） -->",
        ]
        for page_no in range(start, end + 1):
            page = doc[page_no - 1]
            tables = page.find_tables().tables
            prose = _page_prose(page, [table.bbox for table in tables])
            blocks: list[str] = []
            if prose:
                blocks.append(prose)
            for ti, table in enumerate(tables):
                md = table_to_markdown(table.extract())
                if md:
                    blocks.append(
                        f"**表 {page_no}.{ti + 1}**"
                        f"（{table.row_count} 行 × {table.col_count} 列）\n"
                        f"\n{md}"
                    )
            if not blocks:
                continue
            parts.append(f"## 第 {page_no} 页\n\n" + "\n\n".join(blocks))
        markdown = "\n\n".join(parts)
        # 除头注与页锚点外无任何内容 → 视为未抽取到文本层
        if re.sub(r"<[^>]*>|## 第 \d+ 页|\s", "", markdown):
            return markdown
        return ""
    finally:
        doc.close()


def extract_pdf_markdown(path: Path) -> str:
    """把整份 PDF 抽取为 Markdown 全文。

    Args:
        path: PDF 文件路径。

    Returns:
        Markdown 文本；正文与表格皆为空（如纯扫描件）时返回空串。

    Raises:
        ImportError: 运行环境未安装 PyMuPDF。
        Exception: 文件无法解析等抽取错误，由调用方显式降级。
    """
    return extract_pdf_pages_markdown(path)
