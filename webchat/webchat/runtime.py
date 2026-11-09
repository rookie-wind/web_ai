"""会话运行时：1:1:1 绑定、租约、实例池、消息执行。"""

from __future__ import annotations

__all__ = ["QuotaExceeded", "SessionActivationFailed", "SessionRuntime", "WebSession"]

import asyncio
import hashlib
import json
import logging
import secrets
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

import httpx

from .artifacts import ArtifactRegistry, scan_outputs, unique_path
from .errors import QuotaExceeded, SessionActivationFailed
from .event_store import EventStore
from .gate_audit import GateAuditLog
from .grants import GrantStore, TaskScope, WriteGate, bare_tool_name, classify_tool
from .skills import SkillCatalog
from .sdk_runtime import (
    ActivationError,
    AdapterConfig,
    AgentHandle,
    TurnAborted,
    call_login_tool,
)


def _json_from_tool_content(content: object) -> dict:
    """把 tool_result content（字符串或文本块列表）解析为业务字典。

    取首个能解析为 JSON 对象的文本；均不能则返回空字典。
    """
    texts: list[str] = []
    if isinstance(content, str):
        texts.append(content)
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                texts.append(block["text"])
            elif isinstance(block, str):
                texts.append(block)
    for raw in texts:
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


logger = logging.getLogger(__name__)

# 来源 B：这些工具的结果含 file_id，事件时回源 mcp_server 取字节落盘并登记产物。
REMOTE_ARTIFACT_TOOLS = frozenset({
    "generate_device_archive_template",
    "get_device_archive_template_download",
    "save_conversion_config",
    "pack_bundle",
})
# 回源超时与单文件上限（超过即放弃，不落半成品）
REMOTE_ARTIFACT_TIMEOUT = 60.0
REMOTE_ARTIFACT_MAX_BYTES = 64 * 1024 * 1024


@dataclass
class WebSession:
    """一个 Web 会话（会话:实例:凭据 1:1:1）。"""

    id: str
    username: str
    workspace: Path
    mcp_token: str = ""
    handle: AgentHandle | None = None
    lease_holder: str = ""
    lease_expires: float = 0.0
    closed: bool = False
    turn_count: int = 0
    plan_summaries: dict[str, dict] = field(default_factory=dict)
    # 来源 B 幂等：file_id -> artifact_id（同一会话同一 file_id 只登记一次）
    remote_files: dict[str, str] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    # 空闲回收：最后活动时间与执行中轮次标记（扫描时跳过执行中的会话）
    last_activity: float = field(default_factory=time.time)
    turn_running: bool = False
    # 后台 PDF 文本提取中的文件名（轮次开始前等待，避免读到尚未生成的 .txt）
    pending_text: set[str] = field(default_factory=set)
    # 当前执行中的 asyncio 任务（供 /abort 取消；结束后清空）
    run_task: asyncio.Task | None = None
    # 本会话出现过的建档 task_id（供中止服务端批次）
    archive_task_ids: set[str] = field(default_factory=set)

    def hold_lease(self, holder_id: str, ttl: float) -> bool:
        """尝试获取或续期写租约（持有者一致或租约过期才允许）。"""
        now = time.time()
        if self.lease_holder and self.lease_holder != holder_id and now < self.lease_expires:
            return False
        self.lease_holder = holder_id
        self.lease_expires = now + ttl
        return True

    def has_lease(self, holder_id: str) -> bool:
        """判断 holder 是否持有有效租约。"""
        return (
            self.lease_holder == holder_id
            and time.time() < self.lease_expires
        )


class SessionRuntime:
    """会话管理器：配额、绑定、消息执行、回收。"""

    # 计划域事件白名单：仅这些工具的 tool_result 参与建档摘要反查（design D5）
    _PLAN_TOOLS = frozenset({
        "read_device_archive_template", "plan_device_archive",
    })

    def __init__(
        self,
        *,
        mint_url: str,
        mint_secret: str,
        workspaces_dir: Path,
        events: EventStore,
        max_instances: int = 4,
        max_sessions_per_user: int = 2,
        max_turns: int = 25,
        lease_ttl: float = 45.0,
        mcp_url: str = "http://127.0.0.1:8765",
        pat: str = "",
        grants: GrantStore | None = None,
        audit: GateAuditLog | None = None,
        artifacts: ArtifactRegistry | None = None,
        activate: Callable[[str, str, str, str], Awaitable[dict]] | None = None,
        agent_model: str = "",
        max_concurrent_turns: int = 16,
        skill_catalog: SkillCatalog | None = None,
        read_extra_roots: tuple[Path, ...] | None = None,
    ):
        """初始化运行时。

        Args:
            mint_url: MCP Server 基地址（mint 端点所在）。
            mint_secret: mint 端点密钥。
            workspaces_dir: 工作区根目录。
            events: 事件存储。
            max_instances: 全局活跃实例上限。
            max_sessions_per_user: 每用户并发会话上限。
            max_turns: 单轮工具迭代上限。
            lease_ttl: 租约 TTL（秒）。
            mcp_url: 实例接入的 /mcp 地址。
            pat: QODER PAT（实例注入，不出现在命令行）。
            grants: 写入门禁票据存储（缺省新建内存态）。
            audit: 门禁审计台账（缺省不记审计）。
            artifacts: 产物登记表（缺省不登记；turn 收尾扫描 xlpa-output/）。
            activate: 平台授权激活回调（mcp_url, token, phone, code）；
                缺省用 SDK 层的 call_login_tool（design D9，AC 演练硬前置）。
            agent_model: 会话模型名（传入 CLI --model）；为空时回落 CLI 默认。
            max_concurrent_turns: 并发执行轮次上限；<=0 表示不限制。
            skill_catalog: canonical 技能目录快照；索引进系统提示，全文按
                ``/技能名`` 前缀当轮注入，Read 白名单含该目录。
            read_extra_roots: Read 白名单的额外目录（CLI 大结果落盘目录等）；
                默认取配置 `WEBCHAT_READ_EXTRA_ROOTS` + CLI 默认目录。
        """
        self._mint_url = mint_url
        self._mint_secret = mint_secret
        self._workspaces_dir = Path(workspaces_dir)
        self._workspaces_dir.mkdir(parents=True, exist_ok=True)
        self._events = events
        self._max_instances = max_instances
        self._max_per_user = max_sessions_per_user
        self._max_turns = max_turns
        self._lease_ttl = lease_ttl
        self._mcp_url = mcp_url
        self._pat = pat
        self._grants = grants if grants is not None else GrantStore()
        # 活动 task 作用域：与票据窗口同 TTL，决定无 task 写入归并到哪个目标
        self._task_scope = TaskScope(ttl_seconds=self._grants.ttl_seconds)
        self._audit = audit
        self._artifacts = artifacts
        self._activate = activate or call_login_tool
        self._agent_model = agent_model
        self._max_concurrent_turns = max_concurrent_turns
        self._active_turns = 0
        self._skill_catalog = skill_catalog
        self._skill_index = skill_catalog.render_index() if skill_catalog else ""
        self._skill_texts = dict(skill_catalog.texts) if skill_catalog else {}
        self._read_extra_roots = tuple(read_extra_roots or ())
        # tool_use_id -> 裸工具名（跨轮保留，计划摘要反查用）
        self._tool_names: dict[str, str] = {}
        self._sessions: dict[str, WebSession] = {}
        self._instance_slots = asyncio.Semaphore(max_instances)
        self._user_counts: dict[str, int] = {}

    # ── 配额 ──

    async def create(self, username: str, *, account: dict | None = None) -> WebSession:
        """创建会话：配额检查 → mint 凭据 → 授权激活 → 工作区 → 事件落位。

        account 提供 ``{phone, code}`` 时，mint 成功后、会话对用户可用
        之前用该接入凭据对 /mcp 调一次 login 完成平台登录绑定（design D9）；
        激活失败必须使创建失败并回滚槽位/凭据，不得留下可用但一查即错的
        会话。未提供 account 时不激活（存量测试/无预设凭据场景）。
        """
        active = sum(1 for s in self._sessions.values() if not s.closed)
        if active >= self._max_instances:
            raise QuotaExceeded(
                f"全局活跃实例已达上限 {self._max_instances}，请稍后重试"
            )
        if self._user_counts.get(username, 0) >= self._max_per_user:
            raise QuotaExceeded(
                f"每用户并发会话上限 {self._max_per_user} 已满"
            )
        try:
            # 硬闸：并发创建竞态下信号量保底（正常情况下此处不阻塞）
            await asyncio.wait_for(self._instance_slots.acquire(), timeout=2)
        except asyncio.TimeoutError as exc:
            raise QuotaExceeded("实例槽位繁忙，请稍后重试") from exc
        session_id = secrets.token_hex(16)
        workspace = self._workspaces_dir / session_id
        (workspace / "xlpa-tmp").mkdir(parents=True, exist_ok=True)
        (workspace / "xlpa-input").mkdir(parents=True, exist_ok=True)
        (workspace / "xlpa-output").mkdir(parents=True, exist_ok=True)
        token = await self._mint(username, session_id)
        session = WebSession(
            id=session_id,
            username=username,
            workspace=workspace,
            mcp_token=token,
        )
        phone = str((account or {}).get("phone", "") or "")
        code = str((account or {}).get("code", "") or "")
        if phone and code:
            try:
                await self._activate(
                    f"{self._mcp_url}/mcp", token, phone, code
                )
            except ActivationError as exc:
                await self._revoke(token)
                shutil.rmtree(workspace, ignore_errors=True)
                self._instance_slots.release()
                raise SessionActivationFailed(
                    f"平台授权激活失败，会话未创建: {exc}"
                ) from exc
        self._sessions[session_id] = session
        self._user_counts[username] = self._user_counts.get(username, 0) + 1
        self._events.append(session_id, "session_started", {"username": username})
        return session

    async def _mint(self, username: str, session_id: str) -> str:
        """调 MCP Server mint 端点签发凭据。"""
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{self._mint_url}/api/mcp-token/mint",
                json={"username": username},
                headers={"X-Mint-Secret": self._mint_secret},
            )
        if resp.status_code != 200:
            raise RuntimeError(f"mint 失败: HTTP {resp.status_code}")
        return resp.json()["token"]

    # ── 查询 ──

    def get(self, session_id: str) -> WebSession | None:
        """按 ID 取会话。"""
        return self._sessions.get(session_id)

    def forget(self, session_id: str) -> None:
        """移除会话记录（用户主动删除会话后，后续访问一律 404）。"""
        self._sessions.pop(session_id, None)

    def list_for(self, username: str) -> list[WebSession]:
        """列出某用户的会话。"""
        return [s for s in self._sessions.values() if s.username == username]

    def all_sessions(self) -> list[WebSession]:
        """列出全部会话（空闲扫描用快照）。"""
        return list(self._sessions.values())

    def touch(self, session: WebSession) -> None:
        """刷新最后活动时间（消息/租约/确认/SSE/上传下载均算活动）。"""
        session.last_activity = time.time()

    # ── 并发轮次护栏 ──

    def try_begin_turn(self) -> bool:
        """占用一个并发轮次名额；超限返回 False（不排队、不拉起进程）。"""
        if self._max_concurrent_turns <= 0:
            return True
        if self._active_turns >= self._max_concurrent_turns:
            return False
        self._active_turns += 1
        return True

    def end_turn(self) -> None:
        """释放并发轮次名额。"""
        if self._active_turns > 0:
            self._active_turns -= 1

    # ── PDF 后台文本提取等待 ──

    def begin_text_extraction(self, session: WebSession, name: str) -> None:
        """登记一个已排队的 PDF 文本提取任务。"""
        session.pending_text.add(name)

    def finish_text_extraction(self, session_id: str, name: str) -> None:
        """标记 PDF 文本提取结束（成功或失败）；会话已删除则忽略。"""
        session = self._sessions.get(session_id)
        if session is not None:
            session.pending_text.discard(name)

    async def wait_pending_text(
        self, session: WebSession, *, timeout: float = 120.0
    ) -> None:
        """轮次开始前等待该会话的后台文本提取完成（最长 ``timeout`` 秒）。

        只等待已登记的任务；超时仅告警并继续，避免单个异常文件永久阻塞会话。
        前端已提示“文本提取在后台进行”，等待期间不额外产事件。
        """
        if not session.pending_text:
            return
        deadline = time.monotonic() + timeout
        while session.pending_text and time.monotonic() < deadline:
            await asyncio.sleep(0.5)
        if session.pending_text:
            logger.warning(
                "text extraction still pending after %.0fs: session=%s files=%s",
                timeout, session.id, sorted(session.pending_text),
            )

    # ── 中止当前任务 ──

    async def cancel_archive_tasks(
        self, session: WebSession, task_id: str = ""
    ) -> list[str]:
        """请求 MCP 服务端中止建档批次（协作式，当前单元完成后停止）。"""
        if not session.mcp_token:
            return []
        ids = [task_id] if task_id else sorted(session.archive_task_ids)
        if not ids:
            return []
        cancelled: list[str] = []
        async with httpx.AsyncClient(timeout=10.0) as client:
            for tid in ids:
                try:
                    resp = await client.post(
                        f"{self._mint_url}/api/archive/tasks/{tid}/cancel",
                        headers={
                            "Authorization": f"Bearer {session.mcp_token}"
                        },
                    )
                except httpx.HTTPError as exc:
                    logger.warning(
                        "archive cancel failed: task=%s err=%s",
                        tid, type(exc).__name__,
                    )
                    continue
                if resp.status_code == 200:
                    cancelled.append(tid)
                else:
                    logger.warning(
                        "archive cancel rejected: task=%s http=%s",
                        tid, resp.status_code,
                    )
        return cancelled

    async def abort_turn(
        self, session: WebSession, task_id: str = ""
    ) -> tuple[bool, list[str]]:
        """中止当前 Web 轮次，并请求中止服务端建档批次。

        顺序：先请求服务端批次取消（interrupt 不会停止已发出的 MCP 工具），
        再调用句柄 ``abort()``（SDK interrupt）让本轮尽快收尾；宽限期内未结束
        才取消任务兜底。中止后同一会话可继续下一轮，旧确认票据作废。

        Returns:
            ``(aborted, tasks_cancelled)``。已完成的写入不回滚。
        """
        cancelled_tasks = await self.cancel_archive_tasks(
            session, task_id=task_id
        )
        task = session.run_task
        aborted = False
        handle_abort = getattr(session.handle, "abort", None)
        graceful = callable(handle_abort)
        if graceful:
            try:
                await handle_abort()
            except Exception as exc:  # noqa: BLE001 - 中断失败走取消兜底
                logger.warning(
                    "handle abort failed: session=%s err=%s",
                    session.id, type(exc).__name__,
                )
        if task is not None and not task.done():
            if graceful:
                # interrupt 后等待本轮自行收尾（不取消，保留上下文与连接）
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=5)
                except asyncio.TimeoutError:
                    logger.warning(
                        "interrupt wait timeout: session=%s", session.id
                    )
                except asyncio.CancelledError:
                    pass
                except Exception:  # noqa: BLE001 - 轮次异常不影响中止结果
                    pass
            if task.done():
                aborted = True
            else:
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=10)
                except asyncio.TimeoutError:
                    logger.warning("abort turn timeout: session=%s", session.id)
                except asyncio.CancelledError:
                    pass
                except Exception:  # noqa: BLE001 - 轮次异常不影响中止结果
                    pass
                aborted = task.done()
        session.run_task = None
        session.turn_running = False
        # 中止后作废本会话旧确认票据，避免后续误放行
        self._grants.clear_session(session.id)
        self._task_scope.clear_session(session.id)
        self.touch(session)
        self._events.append(
            session.id,
            "turn_aborted",
            {
                "reason": "user_abort",
                "aborted": aborted,
                "tasks_cancelled": cancelled_tasks,
            },
        )
        return aborted, cancelled_tasks

    # ── 空闲回收 ──

    async def sweep_idle(
        self, idle_ttl: float, *, now: float | None = None
    ) -> int:
        """结束空闲且无执行中轮次的会话，返回结束数量。

        采用 close 语义：撤销凭据、释放槽位、产 session_closed 事件；
        MUST NOT 删除工作区与产物（仍按保留期留存）。
        """
        cutoff = (now if now is not None else time.time()) - idle_ttl
        closed = 0
        for session in self.all_sessions():
            if session.closed or session.turn_running:
                continue
            if session.last_activity >= cutoff:
                continue
            await self.close(session, reason="idle")
            closed += 1
        return closed

    # ── 消息执行 ──

    async def run_message(
        self, session: WebSession, prompt: str, *, holder_id: str
    ) -> None:
        """执行一轮消息：事件经 EventStore 落盘。"""
        if not session.has_lease(holder_id):
            raise PermissionError("当前连接不持有写租约")
        if session.handle is None:
            config = AdapterConfig(
                cwd=session.workspace,
                mcp_url=f"{self._mcp_url}/mcp",
                mcp_token=session.mcp_token,
                max_turns=self._max_turns,
                skills=["xlpa"],
                model=self._agent_model or None,
                skill_index=self._skill_index,
                skill_texts=self._skill_texts,
            )
            read_roots = [session.workspace]
            if self._skill_catalog is not None:
                read_roots.append(self._skill_catalog.root)
            # CLI 大结果落盘目录（qoder-mcp-outputs / .qoder-cn/tmp）等额外白名单
            read_roots.extend(self._read_extra_roots)
            gate = WriteGate(
                session.id,
                self._grants,
                event_writer=lambda t, p: self._events.append(session.id, t, p),
                audit_writer=self._audit.append if self._audit is not None else None,
                summary_lookup=lambda target: dict(
                    session.plan_summaries.get(target) or {}
                ),
                workspace_dir=session.workspace,
                read_roots=read_roots,
                task_scope=self._task_scope,
            )
            session.handle = AgentHandle(
                config, pat_env=self._pat or None, gate=gate
            )
        turn_started = time.time()
        session.turn_count += 1
        session.turn_running = True
        self.touch(session)
        # 上传 PDF 后立刻发消息时，先等后台文本提取完成，避免模型读不到 .txt
        await self.wait_pending_text(session)
        try:
            async for event in session.handle.run_turn(prompt):
                if event.type == "turn_done":
                    continue
                if event.type == "tool_call":
                    use_id = str(event.payload.get("id") or "")
                    raw_name = str(event.payload.get("name") or "")
                    if use_id and raw_name:
                        self._tool_names[use_id] = raw_name.rsplit("__", 1)[-1]
                elif event.type == "tool_result":
                    self._harvest_plan_summary(session, event.payload)
                elif event.type == "gate_blocked":
                    # 建档写工具被门禁拦截时 target 即 task_id；即使大结果落盘
                    # 导致计划摘要不可解析，也能据此中止服务端批次。
                    target = str(event.payload.get("target") or "")
                    if target.startswith("xlpa_task_"):
                        session.archive_task_ids.add(target)
                self._events.append(session.id, event.type, event.payload)
                if event.type == "tool_result":
                    # 来源 B：白名单工具返回 file_id → 立即回源落盘并登记
                    # （工具结果本身不自动落盘为产物，避免未请求的文件）
                    await self._harvest_remote_artifact(session, event.payload)
            # D5：turn 收尾扫描产物（来源 A：工作区 xlpa-output/）
            if self._artifacts is not None:
                scan_outputs(
                    session.id,
                    session.workspace,
                    self._artifacts,
                    event_writer=lambda t, p: self._events.append(
                        session.id, t, p
                    ),
                )
            # turn_done 字段语义：真实轮次序号 + 本轮耗时（不得用事件序号替代）
            self._events.append(
                session.id,
                "turn_done",
                {
                    "turn": session.turn_count,
                    "duration_ms": int((time.time() - turn_started) * 1000),
                },
            )
        except TurnAborted:
            # 用户中止：不产 turn_done / 不扫描产物；turn_aborted 由
            # abort_turn 统一追加（避免重复）
            return
        finally:
            session.turn_running = False
            self.touch(session)

    # ── 门禁票据 ──

    def _harvest_plan_summary(self, session: WebSession, payload: dict) -> None:
        """从建档类工具结果反查计划域摘要，缓存供 gate_blocked 卡片使用。

        仅白名单工具（read_device_archive_template / plan_device_archive）
        的成功结果参与；按 task_id/plan_id 索提取台数与设备类型。解析
        失败静默跳过（降级交给卡片的「摘要不可用」分支）。
        """
        name = self._tool_names.get(str(payload.get("tool_use_id") or ""), "")
        if name not in self._PLAN_TOOLS or payload.get("is_error"):
            return
        data = _json_from_tool_content(payload.get("content"))
        if not data:
            return
        ids = {str(data[k]) for k in ("task_id", "plan_id") if data.get(k)}
        if not ids:
            return
        if data.get("task_id"):
            session.archive_task_ids.add(str(data["task_id"]))
        total = data.get("node_count")
        types: list[str] = []
        nodes = data.get("nodes")
        if isinstance(nodes, list):
            total = total if total is not None else len(nodes)
            types = sorted(
                {
                    str(n.get("device_type"))
                    for n in nodes
                    if isinstance(n, dict) and n.get("device_type")
                }
            )
        summary = {}
        if total is not None:
            summary["device_total"] = total
        if types:
            shown = "、".join(types[:5]) + ("…" if len(types) > 5 else "")
            summary["device_types"] = shown
        if not summary:
            return
        for target in ids:
            session.plan_summaries.setdefault(target, {}).update(summary)

    async def _harvest_remote_artifact(
        self, session: WebSession, payload: dict
    ) -> None:
        """来源 B：白名单工具返回 file_id 时回源取字节并登记产物。

        使用会话 mcp_token 回源 mcp_server 的模板下载端点（或工具结果自带的
        ``download_url``），字节落 ``xlpa-output/``、登记产物并产 artifact 事件。
        同一会话同一 file_id 只登记一次；回源失败产 error 事件显式告知，
        事件与日志均不含 URL、owner 摘要或 Token。
        """
        if self._artifacts is None or payload.get("is_error"):
            return
        name = self._tool_names.get(
            str(payload.get("tool_use_id") or ""), ""
        )
        if name not in REMOTE_ARTIFACT_TOOLS:
            return
        data = _json_from_tool_content(payload.get("content"))
        file_id = str(data.get("file_id") or "")
        if not file_id or not session.mcp_token:
            return
        if file_id in session.remote_files:
            return
        raw_name = str(
            data.get("file_name") or data.get("template_name") or ""
        ).strip()
        file_name = Path(raw_name).name if raw_name else ""
        if not file_name:
            file_name = f"{file_id}.bin"
        url = self._remote_download_url(session, data, file_id)
        try:
            async with httpx.AsyncClient(
                timeout=REMOTE_ARTIFACT_TIMEOUT
            ) as client:
                resp = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {session.mcp_token}"},
                )
            if resp.status_code != 200:
                raise RuntimeError(f"upstream HTTP {resp.status_code}")
            content = resp.content
            if len(content) > REMOTE_ARTIFACT_MAX_BYTES:
                raise RuntimeError("artifact exceeds size cap")
        except Exception as exc:  # noqa: BLE001 - 回源失败不中断对话
            logger.warning(
                "artifact fetch failed: file_id=%s err=%s",
                file_id,
                type(exc).__name__,
            )
            self._events.append(
                session.id,
                "error",
                {"message": f"产物文件获取失败：{file_name}"},
            )
            return
        out_dir = Path(session.workspace) / "xlpa-output"
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            path = unique_path(out_dir, file_name)
            path.write_bytes(content)
        except OSError:
            self._events.append(
                session.id,
                "error",
                {"message": f"产物文件落盘失败：{file_name}"},
            )
            return
        rel_name = path.relative_to(out_dir).as_posix()
        entry = self._artifacts.register(
            session.id, rel_name, path, size=len(content)
        )
        if entry is None:
            return
        session.remote_files[file_id] = entry.artifact_id
        self._events.append(
            session.id,
            "artifact",
            {
                "artifact_id": entry.artifact_id,
                "name": entry.name,
                "size": entry.size,
            },
        )

    def _remote_download_url(
        self, session: WebSession, data: dict, file_id: str
    ) -> str:
        """拼回源地址：优先工具结果的 download_url，否则按 owner 派生构造。

        owner 派生与 mcp_server ``archiving.snapshot_store.derive_owner_id``
        保持一致（sha256(token)）；webchat 不 import mcp_server，故保留同构
        副本，仅用于回源查询参数，不进事件或浏览器可见位置。
        """
        download_url = str(data.get("download_url") or "")
        if download_url.startswith(("http://", "https://")):
            return download_url
        if download_url.startswith("/"):
            return f"{self._mint_url}{download_url}"
        owner_id = hashlib.sha256(
            session.mcp_token.encode("utf-8")
        ).hexdigest()
        return (
            f"{self._mint_url}/api/archive/templates/{file_id}"
            f"?owner={owner_id}"
        )

    def confirm_grant(
        self, session: WebSession, target: str, tool_name: str = ""
    ) -> float:
        """用户确认后为会话铸造计划域写票据。

        对绝对禁止类目标（``login``）拒绝铸票，避免产生永不参与校验的
        孤儿票据；provision（``edge_get_token``）与 write 目标照常铸票。

        Args:
            session: 目标会话。
            target: 计划域目标（plan_id/task_id、云端写/开辟 tool_name）。
            tool_name: 确认来源工具名（仅用于审计留痕，可选）。

        Returns:
            票据过期时间戳（epoch 秒）。

        Raises:
            ValueError: 目标为绝对禁止类（如 login），不可经确认放行。
        """
        if classify_tool(bare_tool_name(target)) == "login":
            raise ValueError("绝对禁止类目标不可铸票")
        expires_at = self._grants.mint(session.id, target)
        if self._audit is not None:
            self._audit.append({
                "ts": time.time(),
                "session_id": session.id,
                "target": target,
                "tool_name": tool_name,
                "decision": "confirm",
                "reason": "user confirmed",
            })
        return expires_at

    # ── 回收 ──

    async def close(self, session: WebSession, *, reason: str = "") -> None:
        """结束会话：撤销凭据、终止实例、释放配额、封存事件。

        ``reason`` 仅用于事件留痕（如 ``idle``），缺省为空。
        先置 closed 再执行异步回收，避免回收期间新消息进入。
        """
        if session.closed:
            return
        session.closed = True
        session.lease_holder = ""
        if session.mcp_token:
            await self._revoke(session.mcp_token)
        if session.handle is not None:
            await session.handle.close()
        self._grants.clear_session(session.id)
        self._task_scope.clear_session(session.id)
        # D6：xlpa-tmp = temp，会话销毁即清（产物按保留期留存）
        self._clear_temp(session.workspace)
        self._user_counts[session.username] = max(
            0, self._user_counts.get(session.username, 1) - 1
        )
        self._instance_slots.release()
        payload = {"username": session.username}
        if reason:
            payload["reason"] = reason
        self._events.append(session.id, "session_closed", payload)

    @staticmethod
    def _clear_temp(workspace: Path) -> None:
        """清空会话工作区 ``xlpa-tmp/``（temp 分类，会话销毁即清）。"""
        temp = workspace / "xlpa-tmp"
        if not temp.exists():
            return
        for path in temp.iterdir():
            try:
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    path.unlink(missing_ok=True)
            except OSError:
                pass  # 清理失败不阻塞会话回收

    async def _revoke(self, token: str) -> None:
        """调 MCP Server revoke 端点。"""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                await client.post(
                    f"{self._mint_url}/api/mcp-token/revoke",
                    json={"token": token},
                    headers={"X-Mint-Secret": self._mint_secret},
                )
        except httpx.HTTPError:
            pass  # 撤销失败不阻塞回收；凭据 TTL 会兜底


async def idle_sweep_loop(
    runtime: SessionRuntime, idle_ttl: float, interval: float
) -> None:
    """后台空闲回收循环：每 ``interval`` 秒扫描一次并结束空闲会话。

    执行中的轮次（``turn_running``）与会话内打开的 SSE 连接（持续 touch）
    都不会被回收；回收采用 close 语义，不删除工作区与产物。
    """
    while True:
        await asyncio.sleep(interval)
        try:
            closed = await runtime.sweep_idle(idle_ttl)
            if closed:
                logger.info("idle sweep closed %d session(s)", closed)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - 单次扫描异常不终止后台任务
            logger.exception("idle sweep failed")
