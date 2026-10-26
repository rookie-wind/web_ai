"""阶段零：从平台拉取 A 类字典 → 生成 v14 建档模板 → 解析自检。

这是"填表前取最新模板"的正式、可复跑入口。两种用法：

  - CLI：``python -m mcp_server.archiving.templates.stage_zero_generate``
  - 代码：``generate_archive_template()`` 返回生成/自检结果

离线边界（不可臆造）：
  - 用户大分类 / 品牌 / 型号：来自云端 MCP 只读工具（在线实时拉取）。
  - 可建档设备类型（8163 网关 / XLBA 电表）与代理通信方式：来源是边缘
    :7500（getDeviceTypeSelect / getDictItemList CommunicationMode），
    现网 :7500 离线 → 用内置确认枚举（code 经实测）。
  - 模板「设备类型」字典列采用平台全量（get_device_type_list 全集），
    而非只建档那两种。

生成策略与解释：
  - generator 是模板结构（列/下拉/合并/隐藏元数据/映射码值）的唯一真源，
    本模块只负责"拉取 + 传参 + 生成 + 自检"，不手工改模板结构。
  - 品牌→型号按型号接口的 brandName 归一（级联下拉键一致）。
  - 生成后立即用 read_archive_template 自检：errors 只允许"必填项待填"类
    （空模板的正常告警），任何结构/拓扑错误都视为失败并抛出，保证产物
    一定能被后续阶段读通。

注意：平台连接（MCP 地址 / token）通过环境变量覆盖接口，避免硬编码扩散：
  XLPX_MCP_URL 默认 http://localhost:8765/mcp
  XLPX_MCP_TOKEN 默认空（空时尝试自动取本机接入 token）。
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

__all__ = ["StageZeroResult", "generate_archive_template"]

# ── MCP 连接（可被环境变量覆盖）──
MCP_URL = os.getenv("XLPX_MCP_URL", "http://localhost:8765/mcp")
MCP_TOKEN = os.getenv("XLPX_MCP_TOKEN", "")

# 可建档设备类型（来源边缘 :7500，离线用实测；新类型经 profile/SHEET_SPECS 扩展）
_ARCHIVABLE_TYPES = {
    "8163网关": "100009",
    "XLBA电表": "100019",
}
# 代理通信方式（边缘 getDictItemList CommunicationMode；13=MQTT 实测）
_COMM_MODES = [{"name": "AI_test现场MQTT", "code": "13"}]


@dataclass
class StageZeroResult:
    """阶段零生成结果。"""

    path: Path
    counts: dict
    ok: bool
    errors: list
    warnings: list


async def _pull_cloud_dict(api_method) -> list[dict]:
    """调用云端只读工具并抽取 rows。

    Args:
        api_method: 被依赖注入的平台调用函数（返回 JSON 文本）。

    Returns:
        rows 列表；拉取失败返回空列表。
    """
    import asyncio as _a

    text = await api_method()
    try:
        data = json.loads(text) if isinstance(text, str) else text
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []
    payload = data.get("data") or {}
    rows = payload.get("rows", []) if isinstance(payload, dict) else payload
    return rows if isinstance(rows, list) else []


async def _generate(
    *,
    url: str = MCP_URL,
    token: str = MCP_TOKEN,
    output_dir: str | Path | None = None,
) -> tuple[Path, dict]:
    """实际执行拉起点（依赖真实 MCP 时由调用方注入；CLI 用实时通道）。

    Args:
        url: MCP 端点。
        token: MCP Bearer Token。
        output_dir: 输出目录，默认当前工作目录。

    Returns:
        (产物路径, 计数统计 dict)。
    """
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    async def call(tool: str, args: dict | None = None) -> str:
        async with streamablehttp_client(url, headers=headers) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, args or {})
                return "\n".join(
                    i.text for i in result.content if getattr(i, "text", None)
                )

    user_nos = await _pull_cloud_dict(lambda: call("get_device_type_list", {}))
    brands_raw = await _pull_cloud_dict(lambda: call("get_brand_list", {}))
    models_raw = await _pull_cloud_dict(lambda: call("get_model_list", {}))

    # 品牌：以型号的 brandName 为稳定键，回填 brand_list 的 code
    code_by_bname = {
        (b.get("nameCN") or b.get("name")): b.get("code") for b in brands_raw
    }
    brands, seen_b = [], set()
    for m in models_raw:
        bn = m.get("brandName")
        if not bn or bn in seen_b:
            continue
        seen_b.add(bn)
        brands.append({"name": bn, "code": str(code_by_bname.get(bn, "") or "")})
    models_by_brand: dict[str, list[dict]] = {}
    for m in models_raw:
        bn = m.get("brandName") or "未知品牌"
        models_by_brand.setdefault(bn, []).append(
            {"name": m.get("name") or "", "code": str(m.get("modelCode") or "")}
        )

    # 设备类型：平台全量，非只建档那两种
    device_types = [
        {"name": u.get("deviceTypeName") or "", "code": str(u.get("deviceTypeCode") or "")}
        for u in user_nos if u.get("deviceTypeName")
    ]
    user_big_nos = [
        {"name": u.get("deviceTypeName") or "", "code": str(u.get("deviceTypeCode") or "")}
        for u in user_nos if u.get("deviceTypeName")
    ]

    from mcp_server.archiving.templates.generator import generate_template

    out_dir = Path(output_dir) if output_dir else Path.cwd()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    out = generate_template(
        out_dir / f"设备建档模板_{stamp}.xlsx",
        device_types=device_types,
        user_big_nos=user_big_nos,
        comm_modes=_COMM_MODES,
        brands=brands,
        models_by_brand=models_by_brand,
    )
    counts = {
        "user_big": len(user_big_nos),
        "brands": len(brands),
        "models": sum(len(v) for v in models_by_brand.values()),
        "device_types": len(device_types),
    }
    return Path(out), counts


def _self_check(path: Path, counts: dict) -> StageZeroResult:
    """用 read_archive_template 自检产物。

    仅允许"必填项待填"类 errors（空模板正常告警）；任何结构/拓扑错误视为失败。

    Args:
        path: 生成产物路径。
        counts: 计数统计。

    Returns:
        StageZeroResult；结构错误时 ok=False 且 errors 非空。
    """
    from mcp_server.archiving.excel_reader import read_archive_template

    t = read_archive_template(path)
    # 空模板合法的"待填"提示：只关心结构/拓扑，不由这些判定失败
    expect_warn = {"连接参数缺少必填项"}
    fatal = [e for e in t.errors if not any(e.startswith(k) for k in expect_warn)]
    return StageZeroResult(
        path=path,
        counts=counts,
        ok=not fatal,
        errors=fatal,
        warnings=t.warnings,
    )


def generate_archive_template(
    *,
    url: str = MCP_URL,
    token: str = MCP_TOKEN,
    output_dir: str | Path | None = None,
) -> StageZeroResult:
    """阶段零：拉字典→生成→自检（同步入口）。

    Args:
        url: MCP 端点地址。
        token: MCP Bearer Token。
        output_dir: 输出目录。

    Returns:
        StageZeroResult。
    """
    path, counts = asyncio.run(_generate(url=url, token=token, output_dir=output_dir))
    return _self_check(path, counts)


async def _resolve_token(url: str) -> str:
    """无显式 token 时尝试从 /api/access-info 取本机接入 token。"""
    if MCP_TOKEN:
        return MCP_TOKEN
    import urllib.request

    base = url[:-4] if url.endswith("/mcp") else url
    try:
        with urllib.request.urlopen(f"{base}/api/access-info", timeout=5) as resp:
            return json.loads(resp.read().decode()).get("token", "")
    except Exception:
        return ""


def _main() -> int:
    token = os.getenv("XLPX_MCP_TOKEN", MCP_TOKEN)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    if not token:
        token = loop.run_until_complete(_resolve_token(MCP_URL))
    result = generate_archive_template(url=MCP_URL, token=token)
    print("GENERATED:", result.path.resolve())
    print("counts:", result.counts)
    if result.errors:
        print("FATAL ERRORS:", result.errors)
        return 1
    print("SELF-CHECK OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())