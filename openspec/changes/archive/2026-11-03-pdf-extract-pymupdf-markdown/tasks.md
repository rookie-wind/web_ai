## 1. 依赖与抽取模块

- [x] 1.1 `webchat/requirements.txt` 去掉 `pypdf`、加 `PyMuPDF`，在 `webchat/.venv` 执行 `pip install -r webchat\requirements.txt` 并确认 `python -c "import pymupdf; print(pymupdf.__doc__ is not None)"` 成功
- [x] 1.2 新建 `webchat/webchat/pdf_extract.py`：移植 `_pdf_to_md.py` 的 `clean_cell` / `is_header_row` / `table_to_markdown` / `page_prose` / `convert`，对外只暴露 `extract_pdf_markdown(path: Path) -> str`（惰性 `import pymupdf`，缺失时抛 `ImportError`），用单元测试验证「含框线表格的 dict 输入 → GFM 行列数一致、`|` 被转义、无表头时生成 `列N` 占位」
- [x] 1.3 在 `pdf_extract.py` 明确空内容判据：正文与表格均为空时返回空串，验证「只有线条、无文字」的页不产出伪表

## 2. 上传链路落地 .pdf.md

- [x] 2.1 `artifacts.py`：删除 `extract_pdf_text`，`_build_pdf_text_result` 改用 `extract_pdf_markdown`，落盘目标由 `{stem}.pdf.txt` 改为 `{stem}.pdf.md`；`ImportError` 告警文案改为"PDF 文本提取组件未安装（PyMuPDF）"；验证上传响应字段仍为 `text_status`/`path`，事件载荷为 `text_path`/`text_chars`
- [x] 2.2 更新 `artifacts.py` 模块 docstring 与 `_build_pdf_text_result` docstring 中的 `.pdf.txt` 描述；验证 `Select-String -Path webchat\webchat\artifacts.py -Pattern "pdf.txt"` 无命中

## 3. 护栏与提示文案对齐

- [x] 3.1 `grants.py` `.pdf` 分支按磁盘实况选择重定向目标（`.pdf.md` → 历史 `.pdf.txt` → 都不存在则提示 `.pdf.md` 并说明可能未完成），保留 `PDF ` 前缀以维持 `guard="pdf_binary"` 判定；验证 `test_grants.py` 新增三条用例覆盖三种情形
- [x] 3.2 `sdk_runtime/adapter.py` 的 `WEBCHAT_SYSTEM_APPEND` 把读取指引改为同目录 `<原文件名>.pdf.md`（并注明历史会话可能为 `.pdf.txt`）、`.txt 暂不存在` 措辞同步；验证 `test_gate_hook.py` 中 `.pdf.txt` 断言改为 `.pdf.md` 后通过
- [x] 3.3 前端 `static/js/app.js`：上传回执文案与 `pdf_binary` 拦截提示中的 `.pdf.txt` 改为 `.pdf.md`；验证 `node --check`（复制为 `.mjs`）通过，且 `test_static_frontend.py` 字符串断言全部更新通过

## 4. 测试与端到端验证

- [x] 4.1 `webchat/tests/test_artifacts_upload.py`：现有 PDF 夹具改用 PyMuPDF 生成（文本层 + 一张框线表），断言产物为 `xlpa-input/协议文档.pdf.md`、`upload_text.text_path` 指向该文件、MD 内表格单元格不与原版面列串位；损坏 PDF 用例改为断言"无 `.pdf.md` + 载荷含 warning"
- [x] 4.2 新增真实样本 golden 测试：仓库内存在 `webchat/webchat_data/workspaces/f90f3931e7cb97e46aea1286e73dbd64/xlpa-input/527 AMC*.pdf` 时校验寄存器表页产物含 `| 0025H | 相电压UA |` 类行且列数一致，路径不存在则 `pytest.skip`；验证该测试本地 PASS、拷贝到无样本环境时 SKIP 不失败
- [x] 4.3 在 `webchat` 目录下用 `webchat/.venv/Scripts/python.exe -m pytest tests -q` 跑绿（仓库根 `pytest.ini` 的 `testpaths` 只含 `mcp_server/tests`，webchat 测试必须显式指定位子），失败项逐条修复
- [x] 4.4 重启 webchat 后端后做端到端验证：登录→建会话→上传 AMC 说明书→`upload_text` 指向 `.pdf.md`→Agent 用 Read 读到点表且不再命中 `pdf_binary` 拦截；把 `amc_md_png` 式目视核对结论记录进 change 目录（新增 `verification.md`）

## 5. 收尾

- [x] 5.1 仓库根 `_pdf_to_md.py` 顶部加"已迁入 `webchat/webchat/pdf_extract.py`，本脚本仅作诊断工具"说明，或确认无引用后删除；验证 `Select-String -Path .\*.py -Pattern "_pdf_to_md"` 无残留依赖
- [x] 5.2 更新 change 内 specs/design 与实际实现的一致性（若实现过程中改了后缀选择策略或空判据），并运行 `openspec validate pdf-extract-pymupdf-markdown --strict` 通过
