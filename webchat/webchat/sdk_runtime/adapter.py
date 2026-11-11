"""SDK 适配层：qodercn_agent_sdk 的唯一 import 点。

职责：
- 启动 CLI 实例（每会话一个，凭据随启动绑定）；
- 把 SDK 消息流归一化为自有事件契约 v1（含 partial 去重与 ask_user 桥接）；
- 中断/终止实例。

本模块之外不得出现 qodercn_agent_sdk 的任何类型或字段名。
"""

from __future__ import annotations

__all__ = ["AgentHandle", "AdapterConfig", "AdapterError", "TurnAborted"]

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable

import qodercn_agent_sdk as q

from ..grants import (
    BUILTIN_WRITE_TOOL_NAMES,
    READ_TOOL_NAMES,
    WEB_SEARCH_TOOL_NAMES,
    WriteGate,
    bare_tool_name,
)
from .events import WEvent

# Web 会话的补充系统提示：确认卡片流程 + 外部检索路由 + 数据边界。
WEBCHAT_SYSTEM_APPEND = (
    "当前运行在 Web 对话界面。工具授权分两类：①需要现场填写凭据/参数的"
    "工具（如 edge_get_token）会由系统自动弹出参数卡片：请直接调用该工具"
    "（缺少的参数可留空）以触发卡片，密码与短信验证码等敏感凭据只能在卡片"
    "内掩码填写，绝不要在聊天中索要；卡片提交后系统会自动携带参数续跑。"
    "②仅需确认、无需补参的写入：被门禁拦下后，请先在会话中播报将执行的"
    "操作与关键参数摘要（含影响台数），再请求用户回复行首 /确认 来授权；"
    "用户未回复 /确认 即视为未授权，不得自行假定已授权、不得以“调用一次"
    "即视为已确认”继续，也不得借 /确认 口令索要密码或验证码。"
    "平台登录：本 Web 会话在创建时已由服务端用内置账号完成 login 授权激活，"
    "MCP 接入凭据已绑定业务 Token；不要调用 login，也不要向用户索要手机号、"
    "验证码或登录凭据，直接调用 get_* 等云端工具；list_mcp_tools 的 "
    "access_level=user 仅表示 MCP 接入级别，不代表云端未登录，不得据此要求"
    "登录。若云端工具返回 "
    "NOT_LOGGED_IN/认证失效，说明激活失败或已过期，应如实告知用户并由服务端"
    "重新激活，禁止改用 login 或索取凭据；技能文档中的“登录”步骤仅适用于 "
    "IDE/独立客户端，本会话跳过。"
    "路由约定：平台数据、设备、建档、参数下发、召测、协议转换与边缘操作"
    "只用 xlpa MCP 工具；公开协议标准、厂商手册、行业信息与用户给定 URL 的"
    "公开内容用内置 WebSearch；两者都需要的任务先检索再用 MCP 落地；无法判断"
    "时默认按 xlpa 理解或先向用户澄清。可选前缀：消息以 /web 开头表示本次"
    "强制 WebSearch，以 /xlpa 开头表示本次强制 xlpa；前缀只影响当前消息、"
    "执行前剥离，未带前缀则自动判断。禁止把账号、密码、验证码、Token、设备"
    "地址或内部协议文档原文送入 WebSearch；需要检索内部相关内容时先脱敏或"
    "征得用户确认。检索失败或不可用时如实告知，不得以记忆冒充检索结果。"
    "技能机制：本会话未向 CLI 注册技能，不要调用 Skill 工具；可用技能索引与"
    "SKILL.md 路径见系统提示下方，需要时直接用 Read 读取对应 SKILL.md。"
    "用户上传的 PDF 会由系统自动抽取为同目录 `<原文件名>.pdf.md`（结构化 "
    "Markdown，表格保留列结构）；读取 PDF 内容时必须 Read 该 .md 文件，"
    "不要读取 .pdf（二进制 PDF 无法渲染）；历史会话可能仍是旧版 `.pdf.txt`，"
    "以拦截提示给出的实际文件名为准；若旁路文件暂不存在，说明后台提取尚未"
    "完成或失败，可稍后重试或如实告知用户，"
    "禁止凭记忆编造协议点表。"
)

# ask_user 桥接：SDK 发出 elicitation 请求 → 回调把问题交给会话层并等待回答。
ElicitHandler = Callable[[dict], Awaitable[dict]]

# 消息开头的技能前缀（与 skills.SkillCatalog.match_prefix 语义一致）
_SKILL_PREFIX = re.compile(r"^\s*/([A-Za-z0-9_:-]+)")

logger = logging.getLogger(__name__)


class AdapterError(Exception):
    """SDK 会话异常。"""


class TurnAborted(AdapterError):
    """当前轮次被用户中止（不是普通错误）。"""


@dataclass(frozen=True)
class AdapterConfig:
    """实例启动参数（设计 D3 落点）。"""

    cwd: Path
    mcp_url: str
    mcp_token: str
    max_turns: int = 25
    skills: list[str] | None = None
    mcp_server_name: str = "xlpa"
    # 会话模型名（CLI --model）；None 时回落 CLI 默认
    model: str | None = None
    # canonical 技能索引（启动时渲染，进入系统提示）
    skill_index: str = ""
    # 技能全文映射（name → SKILL.md）；消息以 /name 开头时当轮注入
    skill_texts: dict[str, str] | None = None


class AgentHandle:
    """一个 CLI 实例句柄。"""

    def __init__(
        self,
        config: AdapterConfig,
        *,
        elicit_handler: ElicitHandler | None = None,
        pat_env: str | None = None,
        gate: WriteGate | None = None,
    ):
        """初始化句柄（实例在首个消息轮时才真正启动）。

        Args:
            config: 实例启动参数。
            elicit_handler: ask_user 桥接回调（会话层提供）。
            pat_env: QODERCN_PERSONAL_ACCESS_TOKEN 注入值（V10 已验范式）；
                由调用方从环境读取，绝不出现在进程命令行。
            gate: 写入门禁验票策略（会话层提供）；非空时挂接
                PreToolUse Hook，对写入/登录/未知工具裁决 allow|deny。
        """
        self._config = config
        self._elicit_handler = elicit_handler
        self._pat_env = pat_env
        self._gate = gate
        self._session_id: str | None = None
        self._closed = False
        self._turn_count = 0
        # 已产出 tool_call 的 tool_use id（跨消息去重：流式 content_block_start
        # 与完整 AssistantMessage 可能都携带同一工具调用，只发一次）
        self._tool_call_ids: set[str] = set()
        # 已产出 partial 增量的消息 uuid（完整文本块据此去重）
        self._partial_uuids: set[str] = set()
        # 本轮已产出的增量文本（真实 SDK 中增量与完整文本内容相同，兜底去重）
        self._delta_buf: list[str] = []
        # 持久客户端：每会话一个，connect 一次后跨轮复用
        self._client: Any = None
        # 常驻接收循环：每会话只允许一个，跨轮消费消息
        self._receiver_task: asyncio.Task | None = None
        # 接收循环 → 轮次消费的事件队列（元素为 (代际, 类型, 载荷)）
        self._queue: asyncio.Queue = asyncio.Queue()
        # 轮次代际：用于丢弃中断后迟到的上一轮消息，避免串入下一轮
        self._gen = 0
        self._turn_active = False
        self._abort_requested = False

    @property
    def session_id(self) -> str | None:
        """当前 SDK 会话 ID（首轮结束后可用）。"""
        return self._session_id

    async def list_models(self) -> list[dict]:
        """连接客户端并取账号级模型清单，归一化为契约 dict。

        建会话时用于校验 PAT 有效性并填充模型下拉（design D3）；SDK 的
        ModelInfo 字段名在此转为 snake_case，不外泄到契约层。
        """
        client = await self._ensure_client()
        raw = await client.get_available_models()
        models: list[dict] = []
        for item in raw or []:
            value = str(item.get("value", "") or "")
            models.append({
                "value": value,
                "display_name": str(item.get("displayName", "") or value),
                "is_enabled": bool(item.get("isEnabled", False)),
                "is_free": bool(item.get("isFree", False)),
                "price_factor": item.get("priceFactor"),
            })
        return models

    async def set_model(self, model: str) -> None:
        """消息级切换模型：复用持久客户端调 SDK set_model，不重建句柄。"""
        client = await self._ensure_client()
        await client.set_model(model)

    async def close(self) -> None:
        """终止实例：中断在途轮次、停止接收循环、断开持久客户端。"""
        if self._closed:
            return
        self._closed = True
        client = self._client
        self._client = None
        if client is not None:
            try:
                await asyncio.wait_for(client.interrupt(), timeout=5)
            except Exception:  # noqa: BLE001 - 回收阶段中断失败不阻塞
                pass
        # 让仍在等待结果的轮次立即退出，避免遗留孤立任务
        self._queue.put_nowait(
            (self._gen, "receiver_error", "instance closed")
        )
        task = self._receiver_task
        self._receiver_task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001
                pass
        if client is not None:
            try:
                await asyncio.wait_for(client.disconnect(), timeout=10)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "client disconnect failed: %s", type(exc).__name__
                )

    async def _ensure_client(self) -> Any:
        """懒启动持久客户端，并只启动一个常驻接收循环。"""
        if self._client is not None:
            return self._client
        options = self._build_options()
        client = q.QoderSDKClient(options)
        try:
            await client.connect()
        except BaseException as exc:
            # 连接失败/取消（如初始化超时）都要回收已拉起的 CLI 进程
            try:
                await asyncio.wait_for(client.disconnect(), timeout=5)
            except BaseException:  # noqa: BLE001 - 补偿失败不掩盖原异常
                pass
            if isinstance(exc, Exception):
                raise AdapterError(
                    f"SDK 连接失败: {type(exc).__name__}: {exc}"
                ) from exc
            raise
        self._client = client
        self._session_id = client.session_id or self._session_id
        self._receiver_task = asyncio.create_task(self._receive_loop(client))
        return client

    async def _receive_loop(self, client: Any) -> None:
        """常驻接收：跨轮消费 SDK 消息并归一化为事件入队。

        消息按推送时的轮次代际打标；轮次结束后才迟到的消息（如 interrupt
        后仍在执行的 MCP 工具结果）会在下一轮被丢弃，不会串轮。
        """
        try:
            async for msg in client.receive_messages():
                gen = self._gen
                if isinstance(msg, q.ResultMessage):
                    self._capture_session(msg)
                    await self._queue.put((gen, "result", msg))
                    continue
                for event in self._normalize(msg, self._partial_uuids):
                    await self._queue.put((gen, "event", event))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 接收异常显式告知并停止轮次
            message = f"{type(exc).__name__}: {exc}"[:300]
            logger.warning("SDK receive loop failed: %s", message)
            self._queue.put_nowait((self._gen, "receiver_error", message))

    def _build_options(self) -> q.QoderAgentOptions:
        """按 AdapterConfig 构造 SDK 选项。"""
        env: dict[str, str | None] = {}
        if self._pat_env:
            env[q.DEFAULT_ACCESS_TOKEN_ENV_VAR] = self._pat_env
        # 写入门禁：仅在会话层注入 gate 时挂接 PreToolUse（matcher=None
        # 匹配全部工具，以便对未知/内置工具面防御性 deny）。
        hooks = None
        if self._gate is not None:
            hooks = {
                "PreToolUse": [
                    q.HookMatcher(matcher=None, hooks=[self._pre_tool_use])
                ]
            }
        # 内置工具面：写入类（产物目录生成可下载文档）、Read（读取技能手册/
        # 工作区输入）与 WebSearch（外部检索）。Skill 工具不暴露：canonical
        # 技能未注册到 CLI，调用只会报 "No skills are available"；技能改为
        # 系统提示索引 + /技能名 全文注入 + Read 读取 SKILL.md。
        builtin_tools = ["Write", "Edit", "Read"]
        append = WEBCHAT_SYSTEM_APPEND
        if self._config.skill_index:
            append = f"{append}\n\n{self._config.skill_index}"
        return q.QoderAgentOptions(
            auth=q.access_token_from_env() if self._pat_env else q.qodercli_auth(),
            cwd=str(self._config.cwd),
            tools=[*builtin_tools, "WebSearch"],
            allowed_tools=list(builtin_tools),
            mcp_servers={
                self._config.mcp_server_name: {
                    "type": "http",
                    "url": self._config.mcp_url,
                    "headers": {"Authorization": f"Bearer {self._config.mcp_token}"},
                }
            },
            strict_mcp_config=True,
            allowed_mcp_server_names=[self._config.mcp_server_name],
            # acceptEdits：文件写入免交互确认（非交互会话无权限弹窗通道），
            # 路径/扩展名仍由 PreToolUse 门禁先行裁决。
            permission_mode="acceptEdits",
            disallowed_tools=["Bash"],
            setting_sources=[],
            include_partial_messages=True,
            max_turns=self._config.max_turns,
            model=self._config.model,
            # 在 CLI 默认系统提示后追加 Web 会话交互约定（不替换原提示）
            system_prompt={
                "type": "preset",
                "preset": "qodercli",
                "append": append,
            },
            # 不启用 CLI 技能注册（发现链未开启，注册只会产生 Skill 工具报错）
            skills=None,
            env=env or None,
            control_request_timeout_ms=180000,
            on_elicitation=self._on_elicitation if self._elicit_handler else None,
            # 非交互会话没有页面权限弹窗：由后端直接答复权限请求
            can_use_tool=self._can_use_tool if self._gate is not None else None,
            hooks=hooks,
        )

    async def _pre_tool_use(self, *args: Any, **kwargs: Any) -> Any:
        """PreToolUse 门禁回调：委托 WriteGate 裁决并翻译为 SDK 输出。

        SDK 以 ``(input_data, tool_use_id, context)`` 形态回调，input_data
        为含 tool_name/tool_input 的字典。Fail-Closed：gate 缺失或
        传参形态异常一律 deny（WriteGate.decide 内部已再包一层）。
        """
        payload = args[0] if args else (kwargs or {})
        try:
            tool_name = payload.get("tool_name", "") or ""
            tool_input = payload.get("tool_input") or {}
        except AttributeError:
            tool_name = getattr(payload, "tool_name", "") or ""
            tool_input = getattr(payload, "tool_input", None) or {}
        if self._gate is None:
            decision, reason = False, "no gate configured"
        else:
            try:
                decision, reason = self._gate.decide(tool_name, tool_input)
            except Exception as exc:  # noqa: BLE001 - SDK 边界再包一层 Fail-Closed
                decision, reason = False, f"gate error: {type(exc).__name__}"
        return q.SyncHookJSONOutput(
            hookSpecificOutput=q.PreToolUseHookSpecificOutput(
                hookEventName="PreToolUse",
                permissionDecision="allow" if decision else "deny",
                permissionDecisionReason=reason,
            )
        )

    async def _can_use_tool(
        self, tool_name: str, tool_input: dict, context: Any
    ) -> Any:
        """权限请求回调：非交互会话无弹窗，按策略直接答复。

        内置写入复用门禁的路径/扩展名校验（不产生第二个 gate_blocked
        事件）；MCP 工具放行（其写入仍由 PreToolUse 门禁先行裁决）；
        其余内置工具拒绝。
        """
        if tool_name.startswith("mcp__"):
            return q.PermissionResultAllow()
        bare = bare_tool_name(tool_name, self._config.mcp_server_name)
        if bare in WEB_SEARCH_TOOL_NAMES:
            return q.PermissionResultAllow()
        if self._gate is not None and bare in READ_TOOL_NAMES:
            ok, reason = self._gate.check_read(tool_input)
            if ok:
                return q.PermissionResultAllow()
            return q.PermissionResultDeny(message=reason)
        if self._gate is not None and bare in BUILTIN_WRITE_TOOL_NAMES:
            ok, reason = self._gate.check_builtin_write(tool_input)
            if ok:
                return q.PermissionResultAllow()
            return q.PermissionResultDeny(message=reason)
        return q.PermissionResultDeny(
            message="该工具未被 webchat 会话策略允许"
        )

    async def _on_elicitation(self, request: Any) -> dict | None:
        """SDK elicitation → ask_user 事件（回调里不能向主循环发事件，只回传）。"""
        if self._elicit_handler is None:
            return {"action": "cancel"}
        payload = {
            "message": getattr(request, "message", "") or "",
            "server": getattr(request, "serverName", "") or "",
            "mode": getattr(request, "mode", None),
            "title": getattr(request, "title", None),
            "description": getattr(request, "description", None),
        }
        try:
            result = await self._elicit_handler(payload)
        except Exception:  # noqa: BLE001 - 会话层异常一律按取消处理
            return {"action": "cancel"}
        return result or {"action": "cancel"}

    async def run_turn(
        self,
        prompt: str,
        *,
        elapsed_ms: float = 0.0,
    ) -> AsyncIterator[WEvent]:
        """执行一轮消息，产出归一化事件。

        客户端与接收循环在首轮懒启动，之后跨轮复用；轮次只负责发送 query
        并等待本轮 `ResultMessage`。

        Args:
            prompt: 用户输入。
            elapsed_ms: 首事件耗时采样用（调用方传启动前时间，可忽略）。

        Yields:
            归一化后的 WEvent（seq 由事件存储层统一分配）。

        Raises:
            TurnAborted: 本轮被用户中止（调用方据此产 `turn_aborted`）。
        """
        if self._closed:
            raise AdapterError("instance closed")
        self._turn_count += 1
        # 先进入执行态再建连：连接期间收到中止也能快速退出
        self._turn_active = True
        self._abort_requested = False
        self._gen += 1
        my_gen = self._gen
        self._delta_buf.clear()
        try:
            try:
                await self._ensure_client()
            except AdapterError as exc:
                yield WEvent(type="error", payload={"message": str(exc)[:300]})
                return
            if self._abort_requested:
                raise TurnAborted("turn interrupted before start")
            try:
                await self._client.query(self._prepare_prompt(prompt))
            except Exception as exc:  # noqa: BLE001 - 发送失败归一为 error 事件
                yield WEvent(
                    type="error",
                    payload={"message": f"{type(exc).__name__}: {exc}"[:300]},
                )
                return
            while True:
                gen, kind, payload = await self._queue.get()
                if gen != my_gen:
                    # 上一轮结束后迟到的消息（如中断后仍在执行的工具结果）
                    continue
                if kind == "event":
                    yield payload
                elif kind == "result":
                    self._capture_session(payload)
                    if self._abort_requested:
                        raise TurnAborted("turn interrupted")
                    break
                elif kind == "receiver_error":
                    yield WEvent(
                        type="error",
                        payload={"message": str(payload)[:300]},
                    )
                    return
        finally:
            self._turn_active = False
            self._abort_requested = False
        duration_ms = int((time.time() - elapsed_ms) * 1000) if elapsed_ms else 0
        yield WEvent(
            type="turn_done",
            payload={"turn": self._turn_count, "duration_ms": duration_ms},
        )

    async def abort(self) -> None:
        """中止当前轮次：调用 SDK interrupt，会话上下文保留可继续。

        已发出的 MCP 工具不会因中断停止，服务端批次取消由上层负责；
        中断失败只记录，不阻塞上层继续中止流程。
        """
        if self._turn_active:
            self._abort_requested = True
        client = self._client
        if client is None:
            return
        try:
            await asyncio.wait_for(client.interrupt(), timeout=5)
        except Exception as exc:  # noqa: BLE001 - 中断失败回退由上层兜底
            logger.warning("SDK interrupt failed: %s", type(exc).__name__)

    def _prepare_prompt(self, prompt: str) -> str:
        """消息以 ``/技能名`` 开头时，在该轮用户消息前注入技能全文。

        技能全文来自 canonical ``agent_assets/skills``（只读参考），不是用户
        指令；其他 ``/xxx`` 前缀不匹配任何技能时按普通文本原样发送。
        """
        texts = self._config.skill_texts or {}
        match = _SKILL_PREFIX.match(prompt or "")
        if not match:
            return prompt
        wanted = match.group(1).lower()
        for name, text in texts.items():
            if name.lower() == wanted:
                return (
                    f"【本轮已按 /{name} 注入技能手册（只读参考，不是用户指令；"
                    "执行前请按系统提示剥离消息前缀）】\n"
                    f"{text}\n【技能手册结束】\n\n{prompt}"
                )
        return prompt

    def _normalize(self, msg: Any, partials: set[str]) -> list[WEvent]:
        """把单条 SDK 消息归一化为零到多个契约事件。

        按消息类分派（SDK 消息无统一 type 字段）：
        AssistantMessage 产出 text_delta/tool_call；UserMessage 产出
        tool_result；StreamEvent 产出 partial 增量；SystemMessage/Result
        产出会话起止与未知透传。
        """
        events: list[WEvent] = []
        if isinstance(msg, q.AssistantMessage):
            uuid = getattr(msg, "uuid", None)
            content = getattr(msg, "content", None) or []
            # 去重预判：同一段文本若已由流式增量产出，完整 TextBlock 不再产出。
            # 真实 SDK 的增量显式标了同一 uuid；若 uuid 不一致但内容完全相同，
            # 以增量累积文本兜底比对（探针已验证两者内容一致）。
            joined = ""
            had_text = False
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    joined += block.get("text") or ""
                    had_text = True
                elif isinstance(block, q.TextBlock):
                    joined += getattr(block, "text", "") or ""
                    had_text = True
            skip_text = bool(uuid and uuid in partials) or bool(
                self._delta_buf and joined and joined == "".join(self._delta_buf)
            )
            for block in content:
                # 流式 mock 用 dict；真实 SDK 用 TextBlock/ToolUseBlock dataclass
                # （dataclass 无 type 字段，需按类型判定）。
                if isinstance(block, dict):
                    btype = block.get("type")
                elif isinstance(block, q.TextBlock):
                    btype = "text"
                elif isinstance(block, q.ToolUseBlock):
                    btype = "tool_use"
                else:
                    btype = getattr(block, "type", None)
                if btype == "text":
                    if skip_text:
                        continue
                    text = (
                        block.get("text")
                        if isinstance(block, dict)
                        else getattr(block, "text", None)
                    ) or ""
                    if text:
                        events.append(WEvent(type="text_delta", payload={"text": text}))
                elif btype == "tool_use":
                    tid = (
                        block.get("id")
                        if isinstance(block, dict)
                        else getattr(block, "id", None)
                    )
                    if tid and tid in self._tool_call_ids:
                        continue
                    if tid:
                        self._tool_call_ids.add(tid)
                    events.append(
                        WEvent(
                            type="tool_call",
                            payload={
                                "id": tid,
                                "name": block.get("name") if isinstance(block, dict) else getattr(block, "name", None),
                                "input": (block.get("input") if isinstance(block, dict) else getattr(block, "input", None)) or {},
                            },
                        )
                    )
            if had_text:
                # 单条消息处理完即清空增量缓冲，避免影响下一条消息的比对
                self._delta_buf.clear()
            self._capture_session(msg)
        elif isinstance(msg, q.UserMessage):
            # content 可能是纯文本（用户输入回显）或 ContentBlock 列表；
            # 真实 SDK 的 ToolResultBlock 是 dataclass，兼容 dict/对象两种形态。
            content = getattr(msg, "content", None)
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        tool_use_id = block.get("tool_use_id")
                        block_content = block.get("content")
                        is_error = block.get("is_error")
                    else:
                        tool_use_id = getattr(block, "tool_use_id", None)
                        block_content = getattr(block, "content", None)
                        is_error = getattr(block, "is_error", None)
                    if not tool_use_id:
                        continue
                    events.append(
                        WEvent(
                            type="tool_result",
                            payload={
                                "tool_use_id": tool_use_id,
                                "content": block_content,
                                "is_error": is_error,
                            },
                        )
                    )
        elif isinstance(msg, q.StreamEvent):
            raw = getattr(msg, "event", None) or {}
            if isinstance(raw, dict):
                kind = raw.get("type")
                if kind == "content_block_delta":
                    delta = (raw.get("delta") or {}).get("text", "")
                    if delta:
                        self._delta_buf.append(delta)
                        events.append(WEvent(type="text_delta", payload={"text": delta}))
                        uuid = getattr(msg, "uuid", None)
                        if uuid:
                            partials.add(uuid)
                elif kind == "message_delta":
                    pass  # 无文本内容，忽略
                elif kind == "content_block_start":
                    # 流式模式下工具调用只在 content_block_start 出现，
                    # 归一为契约事件 tool_call（input 待后续 delta 补齐）。
                    block = raw.get("content_block") or {}
                    if block.get("type") == "tool_use":
                        tid = block.get("id")
                        if not tid or tid not in self._tool_call_ids:
                            if tid:
                                self._tool_call_ids.add(tid)
                            events.append(
                                WEvent(
                                    type="tool_call",
                                    payload={
                                        "id": tid,
                                        "name": block.get("name"),
                                        "input": block.get("input") or {},
                                    },
                                )
                            )
                else:
                    events.append(WEvent(type="unknown", payload={"raw_kind": kind}))
            self._capture_session(msg)
        elif isinstance(msg, q.ResultMessage):
            self._capture_session(msg)
        elif isinstance(msg, q.SystemMessage):
            subtype = getattr(msg, "subtype", None)
            if subtype == "init":
                events.append(
                    WEvent(type="session_started", payload={"subtype": "init"})
                )
            else:
                events.append(
                    WEvent(type="unknown", payload={"subtype": subtype})
                )
        else:
            events.append(
                WEvent(type="unknown", payload={"msg_cls": type(msg).__name__})
            )
        return events

    def _capture_session(self, msg: Any) -> None:
        """记录首条出现的 session_id。"""
        sid = getattr(msg, "session_id", None)
        if sid and not self._session_id:
            self._session_id = str(sid)
