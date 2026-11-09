"""PDF 结构化抽取测试（GFM 表格规则 + 真实抽取 + 空内容判据）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from webchat.pdf_extract import (
    extract_pdf_markdown,
    extract_pdf_pages_markdown,
    table_to_markdown,
)

__all__ = ["make_table_pdf"]


def make_table_pdf(dest: Path, *, with_text: bool = True) -> Path:
    """生成一页含正文与框线表格（3 列 × 2 行）的最小 PDF（共享夹具）。

    Args:
        dest: 输出 PDF 路径。
        with_text: 是否在表格外写入一行正文说明。

    Returns:
        生成的 PDF 路径。
    """
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    if with_text:
        page.insert_text((72, 60), "Modbus register map below", fontsize=11)
    x0, y0 = 72.0, 120.0
    col_w, row_h = 120.0, 30.0
    ncol, nrow = 3, 2
    cells = [
        ["地址", "名称", "类型"],
        ["0025H", "相电压UA|B", "Uint16"],
    ]
    for r in range(nrow + 1):
        y = y0 + r * row_h
        page.draw_line((x0, y), (x0 + ncol * col_w, y))
    for c in range(ncol + 1):
        x = x0 + c * col_w
        page.draw_line((x, y0), (x, y0 + nrow * row_h))
    for r in range(nrow):
        for c in range(ncol):
            page.insert_text(
                (x0 + c * col_w + 6, y0 + r * row_h + 19),
                cells[r][c],
                fontsize=10,
                fontname="china-s",
            )
    doc.save(str(dest))
    doc.close()
    return dest


def test_table_to_markdown_keeps_columns_and_escapes_pipe() -> None:
    """含表头关键词的首行作表头；单元格竖线转义；列数按最宽行补齐。"""
    md = table_to_markdown(
        [["地址", "名称", "类型"], ["0025H", "UA|UB", "Uint16"], ["0026H"]]
    )
    lines = md.splitlines()
    assert lines[0] == "| 地址 | 名称 | 类型 |"
    assert lines[1] == "| --- | --- | --- |"
    assert lines[2] == "| 0025H | UA\\|UB | Uint16 |"
    # 短行补齐到 3 列，避免 Markdown 渲染串列
    assert lines[3] == "| 0026H |  |  |"


def test_table_to_markdown_placeholder_header_when_no_keyword() -> None:
    """首行无表头关键词时生成占位表头，数据行不被吞掉。"""
    md = table_to_markdown([["1", "2"], ["3", "4"]])
    assert md.splitlines()[0] == "| 列1 | 列2 |"
    assert "| 1 | 2 |" in md and "| 3 | 4 |" in md


def test_table_to_markdown_empty_rows_return_blank() -> None:
    """全空行不产出伪表。"""
    assert table_to_markdown([["", ""], []]) == ""


def test_extract_pdf_markdown_keeps_table_structure(tmp_path) -> None:
    """框线表格抽取后列位置不串位，正文与表格不重复。"""
    pdf = make_table_pdf(tmp_path / "点表.pdf")
    md = extract_pdf_markdown(pdf)
    assert "## 第 1 页" in md
    assert "Modbus register map below" in md
    assert "| 地址 | 名称 | 类型 |" in md
    assert "| 0025H | 相电压UA\\|B | Uint16 |" in md
    # 表格区域内的文字不得再作为正文出现（去重）
    assert md.count("0025H") == 1


def test_extract_pdf_markdown_lines_only_page_yields_blank(tmp_path) -> None:
    """只有线条、无文字的页不产出伪表，返回空串（扫描件判据）。"""
    import pymupdf

    pdf = tmp_path / "空白.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.draw_line((72, 120), (400, 120))
    page.draw_line((72, 120), (72, 200))
    doc.save(str(pdf))
    doc.close()
    # 孤立线条不构成表格，也不得产出伪表/页锚点
    assert extract_pdf_markdown(pdf) == ""


def _find_real_manual() -> Path | None:
    """仓库内已上传过的工业说明书样本（无则跳过 golden 测试）。"""
    root = Path(__file__).resolve().parents[2]
    matches = sorted(
        root.glob("webchat/webchat_data/workspaces/*/xlpa-input/527 AMC*.pdf"),
    )
    return matches[0] if matches else None


def test_extract_real_manual_register_table_columns() -> None:
    """真实说明书点表页逐行 5 列不串位（样本缺失时跳过）。

    只扫描第 25-33 页（寄存器表页段），避免 45 页全档扫描拖慢单测。
    """
    manual = _find_real_manual()
    if manual is None:
        pytest.skip("仓库内无真实说明书样本，跳过 golden 校验")
    md = extract_pdf_pages_markdown(manual, 25, 33)
    assert "## 第 27 页" in md
    assert "## 第 24 页" not in md
    rows = [line for line in md.splitlines()
            if line.startswith("|") and "相电压UA" in line]
    assert rows, "真实说明书寄存器表未抽取到"
    for line in rows:
        # 表行首尾各一个分隔竖线 → 5 列共 6 个（转义竖线不计）
        assert line.count("|") - line.count("\\|") == 6, line


def test_extract_pdf_markdown_raises_import_error(monkeypatch, tmp_path) -> None:
    """依赖缺失时抛 ImportError，由调用方显式降级。"""
    import builtins

    pdf = make_table_pdf(tmp_path / "t.pdf")
    real_import = builtins.__import__

    def _blocked(name, *args, **kwargs):
        if name == "pymupdf":
            raise ImportError("no module named pymupdf")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    with pytest.raises(ImportError):
        extract_pdf_markdown(pdf)
