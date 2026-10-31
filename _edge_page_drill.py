"""实调 20.2.96.2：验证 edge_get_device_tree 分页取回全量、每页不触发截断。

用法：
    python _edge_page_drill.py <短信验证码>

默认目标 20.2.96.2 / xldz（20.* 段走门户代理，需手机号 + 新鲜验证码）。
复用 _ac1_probe 已验证的配对实例启动与 /mcp HTTP 客户端引导。

验证点：
- 不分页完整树 data 的序列化字符数（即会被 CLI 截断的量级）；
- 分页逐页取回，打印每页字符数；
- 多页无重无漏取回的节点数是否等于 pagination.total；
- 最大单页字符是否远低于 CLI spill 阈值（约 2 万）。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

from _ac1_probe import (
    ENV_FILE,
    MCP_DIR,
    MCP_PORT,
    load_env_file,
    start_servers,
    stop_servers,
    unwrap,
)

IP = "20.2.96.2"
USER = "xldz"
PWD = "xldz-123"
PHONE = "13912986342"
PAGE_LIMIT = 50
CLI_THRESHOLD = 20000


async def run(captcha: str) -> None:
    """连接 /mcp，登录并分页读取设备树，打印对比结论。"""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    token = os.environ.get("MCP_AUTH_TOKEN", "")
    url = f"http://127.0.0.1:{MCP_PORT}/mcp"
    async with streamablehttp_client(
        url, headers={"Authorization": f"Bearer {token}"}
    ) as (read, write, _):
        async with ClientSession(read, write) as s:
            await s.initialize()
            # 验证服务端工具 schema 是否含 offset/limit（判断是否加载了新代码）
            lt = await s.list_tools()
            for t in lt.tools:
                if t.name == "edge_get_device_tree":
                    props = (t.inputSchema or {}).get("properties", {})
                    print(f"[drill] server edge_get_device_tree schema 参数="
                          f"{sorted(props.keys())}")
            login = unwrap(await s.call_tool("edge_get_token", {
                "ip": IP, "username": USER, "password": PWD,
                "phone": PHONE, "captcha": captcha,
            }))
            task_id = login.get("task_id") or login.get("taskId") or ""
            if not task_id:
                print("[drill] 登录失败:", json.dumps(login, ensure_ascii=False)[:500])
                return
            print(f"[drill] 登录成功 task_id={task_id}")

            full = unwrap(await s.call_tool("edge_get_device_tree", {"task_id": task_id}))
            full_chars = len(json.dumps(full.get("data"), ensure_ascii=False))
            print(f"[drill] 不分页完整树 data 序列化 = {full_chars} 字符"
                  f"（这就是会被 CLI 截断的量级）")

            offset = 0
            pages = 0
            total_nodes = 0
            max_page_chars = 0
            ids: set[str] = set()
            has_more = True
            # 结构转储：看不分页原始 data 的真实类型 + 大列表藏在哪个字段
            print(f"[drill] full 顶层键={sorted(full.keys()) if isinstance(full, dict) else type(full).__name__}")
            data_raw = full.get("data") if isinstance(full, dict) else None
            print(f"[drill] data 类型={type(data_raw).__name__} "
                  f"len={len(data_raw) if isinstance(data_raw, (list, dict)) else 'n/a'}")

            def _scan_bigs(obj, path="", out=None, depth=0):
                """递归找出嵌套列表字段（体积可能藏身处），最多深度 3 层。"""
                if out is None:
                    out = []
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if isinstance(v, list) and len(v) >= 3:
                            out.append((f"{path}.{k}", len(v)))
                        if depth < 3:
                            _scan_bigs(v, f"{path}.{k}", out, depth + 1)
                elif isinstance(obj, list) and obj:
                    _scan_bigs(obj[0], f"{path}[0]", out, depth + 1)
                return out

            if isinstance(data_raw, list) and data_raw:
                first = data_raw[0]
                if isinstance(first, dict):
                    print(f"[drill] data[0] 键={sorted(first.keys())}")
                    bigs = _scan_bigs(first, "data[0]")
                    print(f"[drill] data[0] 内大列表字段={bigs[:20]}")
            while has_more:
                res = unwrap(await s.call_tool("edge_get_device_tree", {
                    "task_id": task_id, "offset": offset, "limit": PAGE_LIMIT,
                }))
                pg = res.get("pagination", {})
                page = res.get("data", [])
                if pages == 0:
                    print(f"[drill] 分页调用 res 顶层键="
                          f"{sorted(res.keys()) if isinstance(res, dict) else type(res).__name__}")
                    print(f"[drill] 分页调用 pagination={pg} "
                          f"data类型={type(page).__name__}")
                page_chars = len(json.dumps(page, ensure_ascii=False))
                max_page_chars = max(max_page_chars, page_chars)
                for row in page:
                    ids.add(str(row.get("deviceId") or row.get("id") or ""))
                total_nodes = pg.get("total", total_nodes)
                has_more = pg.get("has_more", False)
                offset = pg.get("next_offset", offset)
                pages += 1
                print(f"[drill] 第{pages}页: 条数={len(page)} 字符={page_chars} "
                      f"total={total_nodes} has_more={has_more} next_offset={offset}")

            verdict = "一致，无重无漏取回全量" if len(ids) == total_nodes else "不一致，需排查"
            safe = "不触发截断" if max_page_chars < CLI_THRESHOLD else "仍可能截断"
            print(f"[drill] 分页汇总: 页数={pages} 取回唯一节点={len(ids)} "
                  f"total={total_nodes} 最大单页字符={max_page_chars}")
            print(f"[drill] 结论: 唯一节点 vs total {verdict}；"
                  f"最大单页 {max_page_chars} < {CLI_THRESHOLD} → {safe}")


def main() -> int:
    """读取验证码参数，启动配对实例并执行分页验证，最后关停。"""
    if len(sys.argv) < 2:
        print("用法: python _edge_page_drill.py <短信验证码>")
        return 2
    captcha = sys.argv[1].strip()
    load_env_file(ENV_FILE)
    load_env_file(MCP_DIR / ".env")
    print(f"[drill] 启动配对实例 mcp :{MCP_PORT} ...", flush=True)
    procs = start_servers()
    try:
        asyncio.run(run(captcha))
    finally:
        print("[drill] 关停服务 ...", flush=True)
        stop_servers(procs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
