# 端到端验证记录（任务 4.4）

- 日期：2026-11-02 11:33
- 样本：`527 AMC系列智能电量采集监控装置安装使用说明书V3.10-20250220(1).pdf`（真实工业说明书）
- 上传响应：HTTP 200，`text_status=pending`
- 后台事件：`upload_text` → `text_path=xlpa-input/527 AMC系列智能电量采集监控装置安装使用说明书V3.10-20250220(1).pdf.md`，`text_chars=52863`，warning=无

## 旁路 Markdown 校验

- 文件落盘：True（E:\codeGIT\pca-mcp-server\webchat\webchat_data\workspaces\c2d126c6a40d44930ac0c74203eedd9e\xlpa-input\527 AMC系列智能电量采集监控装置安装使用说明书V3.10-20250220(1).pdf.md）
- 字符数：52863
- 含 `## 第 27 页` 锚点：True
- 寄存器表行数：2，全部 5 列不串位：True
- 样例行：`| 0025H | 相电压UA | R | 0-9999(转换公式见6.5.2) | Uint16 |`

## 读取护栏（pdf_binary）行为

- PDF 被拒：True
- 重定向指向 .pdf.md：True
- Markdown 可直读：True
- guard 标记：`pdf_binary`
- 拒绝原因原文：`PDF 是二进制文件，无法直接解析；请读取自动抽取的文本：527 AMC系列智能电量采集监控装置安装使用说明书V3.10-20250220(1).pdf.md`

## 自动化测试

- `cd webchat; .venv/Scripts/python.exe -m pytest tests -q` 全绿
- 新增 `tests/test_pdf_extract.py`（GFM 规则 + 真实样本 golden，只扫 25-33 页，约 4.9 秒）
- `tests/test_grants.py` 覆盖三条重定向分支（.md 优先 / 旧 .txt 兜底 / 旁路缺失提示未完成）
- 本次全量跑结果：`218 passed`（无 failed / error）

## 已知局限（实测发现，不阻塞本变更）

- 同一工作区重复上传同名 PDF 时，原 PDF 会因 `unique_path` 落为 `名称_1.pdf`，旁路随之为 `名称_1.pdf.md`；护栏重定向按 `pdf.name + ".md"` 拼接，仍能指对名字。若旁路文件自身发生同名碰撞退让为 `_1` 后缀，重定向会指向未落盘的名字——属旧 `.pdf.txt` 方案同样存在的既有行为，未在本变更内改造。
- 端到端只验证到“旁路产出与护栏重定向”；未跑真实 agent 轮次（会消耗模型额度），agent 侧读取行为由系统提示文案与护栏返回值共同保障。
