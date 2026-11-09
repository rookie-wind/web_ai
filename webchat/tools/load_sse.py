"""SSE 并发压测脚本：多账号建会话 → 并发保持事件流 → 统计占用 → 清理。

用途：验证 WEBCHAT_MAX_INSTANCES（默认 100）下的实际并发与资源表现。
SSE 为增量读取，脚本只统计连接存活、心跳与事件字节数，不触发 Agent 轮次。

用法（在 webchat 目录下，使用 webchat venv）::

    .\\.venv\\Scripts\\python tools\\load_sse.py --accounts "alice:pwd,bob:pwd" \\
        --sessions-per-user 5 --seconds 10

注意：每个账号最多建 `WEBCHAT_MAX_SESSIONS_PER_USER` 个会话；要压到 100 连接
需要足够多的账号（如 20 个账号 × 5 会话）。脚本结束会删除本次创建的会话。
"""

from __future__ import annotations

import argparse
import asyncio
import time

import httpx


def _parse_accounts(raw: str) -> list[tuple[str, str]]:
    """解析 ``user:pass,user2:pass2``。"""
    pairs: list[tuple[str, str]] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" not in item:
            raise SystemExit(f"账号格式应为 user:pass，收到: {item!r}")
        user, pwd = item.split(":", 1)
        pairs.append((user.strip(), pwd))
    if not pairs:
        raise SystemExit("至少提供一个账号")
    return pairs


async def _login(client: httpx.AsyncClient, user: str, pwd: str) -> str:
    """登录并返回会话票据。"""
    resp = await client.post(
        "/api/auth/login", json={"username": user, "password": pwd}
    )
    if resp.status_code != 200:
        raise SystemExit(f"登录失败 {user}: HTTP {resp.status_code} {resp.text}")
    return resp.json()["session_token"]


async def _create_sessions(
    client: httpx.AsyncClient, headers: dict, count: int
) -> list[str]:
    """创建会话，返回 session_id 列表；配额不足时如实报告。"""
    ids: list[str] = []
    for _ in range(count):
        resp = await client.post("/api/sessions", headers=headers)
        if resp.status_code != 200:
            print(f"  建会话停止: HTTP {resp.status_code} {resp.text}")
            break
        ids.append(resp.json()["session_id"])
    return ids


async def _hold_stream(
    client: httpx.AsyncClient,
    headers: dict,
    session_id: str,
    seconds: float,
    stats: dict,
) -> None:
    """保持一条 SSE 连接，统计收到的行/字节。"""
    url = f"/api/sessions/{session_id}/events"
    deadline = time.time() + seconds
    try:
        async with client.stream("GET", url, headers=headers) as resp:
            if resp.status_code != 200:
                stats["failed"] += 1
                return
            stats["opened"] += 1
            async for line in resp.aiter_lines():
                stats["bytes"] += len(line) + 1
                if line.startswith("data:"):
                    stats["events"] += 1
                if time.time() >= deadline:
                    break
    except httpx.HTTPError:
        stats["failed"] += 1


async def _run(args: argparse.Namespace) -> None:
    """压测主流程。"""
    accounts = _parse_accounts(args.accounts)
    if args.sessions_per_user > args.per_user_limit:
        raise SystemExit(
            f"--sessions-per-user 不能超过该账号配额 {args.per_user_limit}"
        )
    timeout = httpx.Timeout(args.timeout)
    async with httpx.AsyncClient(base_url=args.base_url, timeout=timeout) as client:
        headers_by_user: dict[str, dict] = {}
        for user, pwd in accounts:
            token = await _login(client, user, pwd)
            headers_by_user[user] = {"Authorization": f"Bearer {token}"}
            print(f"登录成功: {user}")

        created: list[tuple[str, dict, str]] = []
        for user, _ in accounts:
            headers = headers_by_user[user]
            ids = await _create_sessions(
                client, headers, args.sessions_per_user
            )
            created.extend((user, headers, sid) for sid in ids)
            print(f"  {user}: 建会话 {len(ids)} 个")

        target = len(created)
        print(f"并发连接目标: {target}（持续 {args.seconds}s）")
        stats = {"opened": 0, "failed": 0, "events": 0, "bytes": 0}
        started = time.perf_counter()
        await asyncio.gather(*[
            _hold_stream(client, headers, sid, args.seconds, stats)
            for _, headers, sid in created
        ])
        elapsed = time.perf_counter() - started

        for _, headers, sid in created:
            await client.delete(f"/api/sessions/{sid}", headers=headers)

    ok = target - stats["failed"]
    print(
        f"完成: 目标 {target} / 打开 {stats['opened']} / 失败 {stats['failed']} / "
        f"事件行 {stats['events']} / 字节 {stats['bytes']} / 用时 {elapsed:.1f}s"
    )
    if ok < target:
        print("结论: 存在连接失败，请检查配额与资源上限")
    else:
        print("结论: 全部连接保持成功（仅代表连接层可承载）")


def main() -> None:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="webchat SSE 并发压测")
    parser.add_argument("--base-url", default="http://127.0.0.1:8800")
    parser.add_argument(
        "--accounts", required=True, help="user:pass,user2:pass2"
    )
    parser.add_argument("--sessions-per-user", type=int, default=5)
    parser.add_argument(
        "--per-user-limit", type=int, default=5,
        help="与 WEBCHAT_MAX_SESSIONS_PER_USER 保持一致，用于前置校验",
    )
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--timeout", type=float, default=15.0)
    asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    main()
