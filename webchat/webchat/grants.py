"""写入门禁：授权票据（grant）存储与 PreToolUse 验票策略。

计划域窗口语义：用户在页面确认后，后端为 ``(session_id, target)`` 铸一张
grant；``target`` 为 plan_id/task_id（边缘写）或 tool_name（云端写）。grant
在 TTL 窗口内可被同一目标的多次工具调用复用（覆盖 execute_archive_task 的
batch/cursor 分批续跑与共享 active_plan_id 的逐台边缘写序列），一次确认覆盖
整个已确认计划。放行即滑动续期：每次命中放行把窗口起点顺延一个 TTL，故持续
写入的长轮次不会中途过期（避免确认风暴），停手满一个 TTL 后票据自然回收。

拒绝语义二分：``login``（云平台业务登录）为绝对禁止——deny 不查票、确认无法
解除；``provision``（边缘会话开辟 ``edge_get_token``）与 ``write`` 为条件性
拒绝——无 grant 时 deny 并要求确认，经 confirm 铸票后在 TTL 窗口内放行。两类
拒绝均写入 gate_blocked 事件，由 payload 的 ``confirmable`` 标记区分。

写入/登录工具集合来源锁定：``mcp_server/server.py`` 工具注册表的 ``"type"``
字段（锁定日期 2026-10-29）；防漂移由 tests 按 type 解析比对，勿手改常量。
本模块不 import mcp_server（沿用包边界纪律）。

内置工具面：命令工具 ``Bash``、URL 拉取工具 ``WebFetch`` 与其他未知内置工具
保持 deny；内置写入工具（``Write``/``Edit``/``MultiEdit``/``NotebookEdit``）
仅在会话工作区 ``xlpa-output/`` 内、且为文本类扩展名时放行（agent 生成可下载
文档），路径经 ``resolve()`` 校验，越界与非法扩展名一律 deny 且不可确认解除。
外部检索工具 ``WebSearch`` 显式放行并记审计（只接收查询词，不拉取 URL）。
只读工具 ``Read`` 仅在会话工作区与 canonical 技能目录内放行（路径经
``resolve()`` 校验，越界一律 deny 且不可确认解除）；`.pdf` 二进制文件
拒绝直接读取，并按磁盘实况提示改读后端自动抽取的同名旁路文件
（优先 `.pdf.md`，历史会话的 `.pdf.txt` 次之）。
"""

from __future__ import annotations

__all__ = [
    "BUILTIN_WRITE_TOOL_NAMES",
    "READ_TOOL_NAMES",
    "WEB_SEARCH_TOOL_NAMES",
    "CLOUD_WRITE_TOOL_NAMES",
    "EDGE_WRITE_TOOL_NAMES",
    "WRITABLE_OUTPUT_EXTENSIONS",
    "WRITE_TOOL_NAMES",
    "LOGIN_TOOL_NAMES",
    "PROVISION_TOOL_NAMES",
    "DEFAULT_GRANT_TTL",
    "DEFAULT_DOWNLOAD_GRANT_TTL",
    "grant_ttl_from_env",
    "bare_tool_name",
    "resolve_target",
    "classify_tool",
    "build_arg_summary",
    "build_param_schema",
    "GATED_PARAM_REGISTRY",
    "GrantStore",
    "TaskScope",
    "DownloadGrantStore",
    "WriteGate",
]

import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Callable

# grant 默认 TTL（秒），可由 WEBCHAT_GRANT_TTL 覆盖。
DEFAULT_GRANT_TTL = 300
# 一次性产物下载 grant 默认 TTL（秒），可由 WEBCHAT_DOWNLOAD_GRANT_TTL 覆盖。
DEFAULT_DOWNLOAD_GRANT_TTL = 120

# 来源：server.py 注册表 type=="write"（云端写，32 个）。锁定日期 2026-10-29。
CLOUD_WRITE_TOOL_NAMES: frozenset[str] = frozenset({
    "add_classify", "update_classify", "del_classify",
    "add_device_type", "update_device_type", "del_device_type",
    "add_brand", "update_brand", "del_brand",
    "add_model", "update_model", "del_model",
    "add_protocol_info", "update_protocol", "del_protocol_info",
    "del_protocol_file",
    "add_data_item", "update_data_item", "del_data_item",
    "gen_script", "del_script",
    "add_coeff", "update_coeff", "del_coeff",
    "add_sense", "update_sense", "del_sense",
    "save_protocol_type", "del_protocol_type",
    "save_function_item", "del_function_item",
    "upload_protocol_file",
})

# 来源：server.py 注册表 type=="edge_write"（边缘写，10 个）。锁定日期同上。
EDGE_WRITE_TOOL_NAMES: frozenset[str] = frozenset({
    "edge_upsert_device", "edge_mount_device", "edge_save_device_parameters",
    "edge_set_device_param", "edge_call_clock", "edge_call_monitor_debug",
    "execute_archive_task", "edge_call_device_data",
    "edge_apply_compensation_plan", "edge_delete_device",
})

# 门禁写入集 = 云端写 + 边缘写（42 个）。
WRITE_TOOL_NAMES: frozenset[str] = CLOUD_WRITE_TOOL_NAMES | EDGE_WRITE_TOOL_NAMES

# 来源：server.py 注册表 type=="login" 的 login（云平台业务登录）。webchat
# 会话已持族凭据，业务登录属绝对禁止：deny 不查票、确认也无法解除。
LOGIN_TOOL_NAMES: frozenset[str] = frozenset({"login"})

# 来源：server.py 注册表 type=="edge_util" 的 edge_get_token（独立登录边缘
# 后端、返回 task_id）。webchat 会话并不持有边缘后端账密，"已持凭据"前提对其
# 不成立，故改判为需确认类（provision）：无 grant 时 deny 并要求确认，经
# confirm 铸票（目标为工具名本身）后在 TTL 窗口内放行。
PROVISION_TOOL_NAMES: frozenset[str] = frozenset({"edge_get_token"})

# 内置写入工具：仅在会话产物目录内、且文本类扩展名时放行（见 decide/_decide_builtin_write）。
BUILTIN_WRITE_TOOL_NAMES: frozenset[str] = frozenset({
    "Write", "Edit", "MultiEdit", "NotebookEdit",
})
# 外部检索：仅放行 WebSearch（只传查询词）；WebFetch 等 URL 拉取工具保持 deny。
WEB_SEARCH_TOOL_NAMES: frozenset[str] = frozenset({"WebSearch"})
# 只读工具：仅 Read（读取技能手册/工作区输入），路径由 read_roots 白名单裁决。
READ_TOOL_NAMES: frozenset[str] = frozenset({"Read"})
# 允许在 xlpa-output/ 内生成的文件扩展名（仅文本类；二进制文档不在能力范围）。
WRITABLE_OUTPUT_EXTENSIONS: frozenset[str] = frozenset({
    ".md", ".txt", ".csv", ".tsv", ".json", ".jsonl",
    ".html", ".htm", ".xml", ".yaml", ".yml", ".log", ".sql",
})
_OUTPUT_SUBDIR = "xlpa-output"

# 需用户补充参数的门控工具入参登记（provision/write 被拦时，确认卡渲染成表单）。
# 仅登记「需用户直接提供、且 agent 常缺失」的凭据类参数；write 类大多经
# 建档模板/计划携带，暂不登记，后续按需补充。sensitive=True 的字段前端以
# password 型掩码输入。required=True 且 tool_input 未提供者进缺参表单。
GATED_PARAM_REGISTRY: dict[str, list[dict]] = {
    "edge_get_token": [
        {"name": "ip", "label": "目标系统 IP", "required": True, "sensitive": False},
        {"name": "username", "label": "边缘后端账号", "required": True, "sensitive": False},
        {"name": "password", "label": "边缘后端密码", "required": True, "sensitive": True},
        {"name": "phone", "label": "手机号（门户代理登录）", "required": False, "sensitive": False},
        {"name": "captcha", "label": "短信验证码", "required": False, "sensitive": True},
    ],
}

# 门禁决策回调：(event_type, payload) -> None，由 runtime 注入（写事件流）。
EventWriter = Callable[[str, dict], None]
# 审计回调：(entry: dict) -> None，由 runtime 注入（写独立审计台账）。
AuditWriter = Callable[[dict], None]
# 计划域摘要反查回调：(target) -> 可并入 arg_summary 的字段字典。
SummaryLookup = Callable[[str], dict]


def grant_ttl_from_env(environ: dict[str, str] | None = None) -> int:
    """从 WEBCHAT_GRANT_TTL 读取 grant TTL（秒），非法/缺省回退默认值。"""
    env = os.environ if environ is None else environ
    raw = env.get("WEBCHAT_GRANT_TTL", "")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_GRANT_TTL
    return value if value > 0 else DEFAULT_GRANT_TTL


def bare_tool_name(tool_name: str, server_name: str = "xlpa") -> str:
    """剥离 MCP 全限定前缀 ``mcp__<server>__``，返回裸工具名。

    Args:
        tool_name: Hook 收到的工具名（可能为全限定名）。
        server_name: MCP 服务名（默认 xlpa）。

    Returns:
        裸工具名；非 MCP 工具原样返回。
    """
    prefix = f"mcp__{server_name}__"
    if tool_name.startswith(prefix):
        return tool_name[len(prefix):]
    if tool_name.startswith("mcp__"):
        parts = tool_name.split("__", 2)
        if len(parts) == 3:
            return parts[2]
    return tool_name


def resolve_target(bare_name: str, tool_input: dict, active_scope: str = "") -> str:
    """推导验票目标：入参 plan_id/task_id 优先，其次活动作用域，最后裸工具名。

    Args:
        bare_name: 裸工具名。
        tool_input: 工具入参（可能带 plan_id/task_id）。
        active_scope: 会话当前活动 task 作用域（由调用方按工具类别裁决后传入）；
            入参未自带 plan/task 时归并到此作用域，令一次确认覆盖整批。

    Returns:
        验票目标字符串。
    """
    if isinstance(tool_input, dict):
        plan_ref = tool_input.get("plan_id") or tool_input.get("task_id")
        if plan_ref:
            return str(plan_ref)
    if active_scope:
        return str(active_scope)
    return bare_name


def classify_tool(bare_name: str) -> str:
    """把裸工具名分类为 ``login`` / ``provision`` / ``write`` / ``read``。"""
    if bare_name in LOGIN_TOOL_NAMES:
        return "login"
    if bare_name in PROVISION_TOOL_NAMES:
        return "provision"
    if bare_name in WRITE_TOOL_NAMES:
        return "write"
    return "read"


# gate_blocked 参数摘要白名单键（C7 design D5）：非白名单键一律不进 payload
_ARG_SUMMARY_WHITELIST = (
    "brand", "model", "protocol", "protocol_type", "device_type",
    "device_name", "classify", "plan_id", "task_id", "report_id",
    "file_id", "file_name", "template_name", "node_count", "total",
    "count", "direction", "region",
)
# 命中即丢弃的敏感键名（即使出现在白名单语义附近也不展示）
_ARG_SENSITIVE_KEY = re.compile(
    r"pass|pwd|token|secret|code|verif|auth|phone|mobile|sms",
    re.IGNORECASE,
)
# 单值最大长度：超出即截断加省略号（脱敏截断）
_ARG_SUMMARY_VALUE_MAX = 40
_ARG_SUMMARY_MAX_KEYS = 12


def build_arg_summary(tool_input: dict) -> dict[str, str]:
    """从工具入参提取展示摘要（确认卡片用，design D5）。

    仅白名单键且未命中敏感模式才提取；值统一转字符串、折叠空白、
    超长截断；非字符串容器类型（dict/list 等）一律不提取，避免结构
    深水区泄露与渲染混乱。

    Args:
        tool_input: 工具入参字典。

    Returns:
        ``{键: 摘要值}``；无可用键时返回空字典。
    """
    summary: dict[str, str] = {}
    if not isinstance(tool_input, dict):
        return summary
    for key in _ARG_SUMMARY_WHITELIST:
        if len(summary) >= _ARG_SUMMARY_MAX_KEYS:
            break
        value = tool_input.get(key)
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            continue
        if _ARG_SENSITIVE_KEY.search(str(key)):
            continue
        text = " ".join(str(value).split())
        if not text:
            continue
        if len(text) > _ARG_SUMMARY_VALUE_MAX:
            text = text[: _ARG_SUMMARY_VALUE_MAX - 1] + "\u2026"
        summary[key] = text
    return summary


def build_param_schema(bare_name: str, tool_input: dict) -> list[dict]:
    """返回门控工具的用户可填参数表单描述（含必填/可选标记）。

    仅对 ``GATED_PARAM_REGISTRY`` 登记的工具生效。返回全部登记参数，
    每项含 ``name``/``label``/``required``/``sensitive``/``prefilled``：
    必填且当前 ``tool_input`` 已提供者标 ``prefilled``（前端可预填）。
    可选项（如 20.* 门户代理才需要的 phone/captcha）一并展示，避免漏填。

    Args:
        bare_name: 裸工具名（已去 MCP 前缀）。
        tool_input: 当前工具入参（可能为空/不完整）。

    Returns:
        参数描述列表；无登记时返回空列表。
    """
    specs = GATED_PARAM_REGISTRY.get(bare_name) or []
    provided = tool_input if isinstance(tool_input, dict) else {}
    fields: list[dict] = []
    for spec in specs:
        value = provided.get(spec["name"])
        prefilled = value.strip() if isinstance(value, str) else bool(value)
        fields.append({
            "name": spec["name"],
            "label": spec.get("label", spec["name"]),
            "required": bool(spec.get("required")),
            "sensitive": bool(spec.get("sensitive")),
            "prefilled": "" if spec.get("sensitive") else ("" if not prefilled else str(value)),
        })
    return fields


class GrantStore:
    """计划域授权票据存储（内存态，服务端持有事实）。"""

    def __init__(self, ttl_seconds: int = DEFAULT_GRANT_TTL):
        """初始化存储。

        Args:
            ttl_seconds: 票据窗口时长（秒）。
        """
        self.ttl_seconds = ttl_seconds
        self._grants: dict[tuple[str, str], float] = {}
        self._lock = threading.Lock()

    def mint(self, session_id: str, target: str) -> float:
        """为 ``(session_id, target)`` 铸造/续期窗口票据。

        Args:
            session_id: 会话 ID。
            target: 计划域目标（plan_id/task_id 或 tool_name）。

        Returns:
            票据过期时间戳（epoch 秒）。

        Raises:
            ValueError: session_id 或 target 为空。
        """
        if not session_id or not target:
            raise ValueError("session_id 与 target 均不可为空")
        expires_at = time.time() + self.ttl_seconds
        with self._lock:
            self._grants[(session_id, target)] = expires_at
        return expires_at

    def check(self, session_id: str, target: str) -> bool:
        """检查会话对目标是否持有有效票据，命中即滑动续期（不销毁）。

        每次放行把 ``expires_at`` 顺延 ``ttl_seconds``，使持续写入的长轮次
        不因窗口到期中途被拦（确认风暴）；停止写入满一个 TTL 后自然过期回收。
        过期即惰性清理。

        Args:
            session_id: 会话标识。
            target: 计划域目标（plan_id/task_id 或 tool_name）。

        Returns:
            窗口内持有效票据且已滑动续期时返回 True；无票据或已过期返回 False。
        """
        now = time.time()
        key = (session_id, target)
        with self._lock:
            expires_at = self._grants.get(key)
            if expires_at is None:
                return False
            if now >= expires_at:
                del self._grants[key]
                return False
            # 滑动消费：放行一次即把窗口起点顺延 TTL
            self._grants[key] = now + self.ttl_seconds
            return True

    def clear_session(self, session_id: str) -> None:
        """清理某会话的全部票据（会话结束时调用）。"""
        with self._lock:
            for key in [k for k in self._grants if k[0] == session_id]:
                del self._grants[key]


class TaskScope:
    """会话活动 task 作用域：记录最近一次建档 task_id 及其有效期。

    一次建档任务产生 ``task_id`` 后，该会话内**不带** plan_id/task_id 的写入都
    归并到这个作用域目标，使"一次确认覆盖整批"（修确认风暴）。新 task_id 覆盖
    旧作用域，停止满 TTL 后惰性回收。本类只决定"归到哪个目标"，是否放行仍由
    ``GrantStore`` 验票——二者语义分离。
    """

    def __init__(self, ttl_seconds: int = DEFAULT_GRANT_TTL):
        """初始化作用域存储。

        Args:
            ttl_seconds: 作用域空闲有效期（秒）。
        """
        self.ttl_seconds = ttl_seconds
        self._active: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def note(self, session_id: str, task_id: str) -> None:
        """登记/刷新会话的活动 task 作用域（新 task 覆盖旧作用域）。

        Args:
            session_id: 会话标识。
            task_id: 建档任务标识；为空则忽略。
        """
        if not session_id or not task_id:
            return
        with self._lock:
            self._active[session_id] = (str(task_id), time.time() + self.ttl_seconds)

    def active(self, session_id: str) -> str:
        """返回会话当前活动作用域；未设置或已过期返回空串（惰性清理）。"""
        now = time.time()
        with self._lock:
            entry = self._active.get(session_id)
            if entry is None:
                return ""
            task_id, expires_at = entry
            if now >= expires_at:
                del self._active[session_id]
                return ""
            return task_id

    def clear_session(self, session_id: str) -> None:
        """清理某会话的活动作用域（会话结束/中止时调用）。"""
        with self._lock:
            self._active.pop(session_id, None)


class DownloadGrantStore:
    """产物下载票据存储：**消费即作废**（语义与 C4 窗口可复用票据相反）。

    绑定 ``(session_id, artifact_id)``，服务端持有事实；token 只经请求头
    （``X-Artifact-Grant``）传递，绝不进 URL、绝不进 artifact 事件 payload
    （否则历史重放会产出已消费的死票据）。
    """

    def __init__(self, ttl_seconds: int = DEFAULT_DOWNLOAD_GRANT_TTL):
        """初始化存储。

        Args:
            ttl_seconds: 未消费 grant 的兜底 TTL（秒）。
        """
        self.ttl_seconds = ttl_seconds
        self._grants: dict[str, tuple[str, str, float]] = {}
        self._lock = threading.Lock()

    def mint(self, session_id: str, artifact_id: str) -> tuple[str, float]:
        """铸造一次性 grant。

        Args:
            session_id: 会话 ID。
            artifact_id: 服务端产物登记表中的产物标识。

        Returns:
            ``(token, expires_at)`` 二元组。

        Raises:
            ValueError: session_id 或 artifact_id 为空。
        """
        if not session_id or not artifact_id:
            raise ValueError("session_id 与 artifact_id 均不可为空")
        token = secrets.token_urlsafe(32)
        expires_at = time.time() + self.ttl_seconds
        with self._lock:
            self._grants[token] = (session_id, artifact_id, expires_at)
        return token, expires_at

    def consume(self, token: str, session_id: str, artifact_id: str) -> bool:
        """原子校验并删除票据（并发/重放仅一次成功）。

        Args:
            token: 请求头携带的 grant。
            session_id: 当前会话 ID（须与铸造时一致）。
            artifact_id: 目标产物标识（须与铸造时一致）。

        Returns:
            校验通过且成功消费返回 True；不存在/已消费/过期/不匹配返回 False。
        """
        if not token:
            return False
        with self._lock:
            entry = self._grants.get(token)
            if entry is None:
                return False
            bound_session, bound_artifact, expires_at = entry
            if time.time() >= expires_at:
                del self._grants[token]  # 过期票据惰性清理
                return False
            if bound_session != session_id or bound_artifact != artifact_id:
                # 不匹配不消费（不得借越权尝试销毁他人票据）
                return False
            del self._grants[token]  # 匹配成功：消费即作废（锁内原子）
            return True

    def clear_session(self, session_id: str) -> None:
        """清理某会话的全部未消费票据（会话结束时调用）。"""
        with self._lock:
            for token in [
                t for t, (sid, _, _) in self._grants.items() if sid == session_id
            ]:
                del self._grants[token]


def pdf_sidecar_name(pdf: Path) -> str:
    """按磁盘实况选出 PDF 旁路文件名（供读取护栏重定向）。优先
    新版结构化产物 `.pdf.md`，其次历史会话留下的 `.pdf.txt`；
    两者都未落盘时返回 `.pdf.md`（后台提取可能尚未完成或已失败）。

    Args:
        pdf: 工作区内待读取的 PDF 绝对路径。

    Returns:
        同目录下旁路文件的文件名。
    """
    for suffix in (".md", ".txt"):
        candidate = pdf.with_name(pdf.name + suffix)
        if candidate.exists():
            return candidate.name
    return pdf.name + ".md"


class WriteGate:
    """PreToolUse 验票策略：分类 + grant 窗口校验 + 事件/审计回调。

    Fail-Closed：``decide`` 内任何异常一律 deny。adapter 只认本对象的
    ``decide``，不直接依赖 GrantStore/EventStore（回调注入）。
    """

    def __init__(
        self,
        session_id: str,
        grants: GrantStore,
        *,
        server_name: str = "xlpa",
        event_writer: EventWriter | None = None,
        audit_writer: AuditWriter | None = None,
        summary_lookup: SummaryLookup | None = None,
        workspace_dir: str | Path | None = None,
        read_roots: list[str | Path] | None = None,
        task_scope: TaskScope | None = None,
    ):
        """初始化验票策略。

        Args:
            session_id: 所属会话 ID。
            grants: 票据存储。
            server_name: MCP 服务名（剥离全限定前缀用）。
            event_writer: gate_blocked 事件写回调（runtime 注入）。
            audit_writer: 审计台账写回调（runtime 注入）。
            summary_lookup: 计划域摘要反查回调（runtime 注入，
                design D5 摘要源分层：一键建档类经 plan_id/task_id 反查）。
            workspace_dir: 会话工作区根目录；注入后内置写入工具仅允许落在
                其 ``xlpa-output/`` 子目录内。为空时内置写入保持全 deny
                （Fail-Closed，存量无工作区场景行为不变）。
            read_roots: 内置 Read 允许的根目录清单（会话工作区 + canonical
                技能目录）。为空时 Read 保持全 deny（Fail-Closed）。
            task_scope: 会话活动 task 作用域存储；注入后，不带 plan/task 的
                write 类写入归并到当前活动作用域（一次确认覆盖整批）。为空时
                保持旧的 tool_name 回退语义（存量无作用域场景行为不变）。
        """
        self._session_id = session_id
        self._grants = grants
        self._server_name = server_name
        self._event_writer = event_writer
        self._audit_writer = audit_writer
        self._summary_lookup = summary_lookup
        self._workspace_dir = Path(workspace_dir) if workspace_dir else None
        self._read_roots = tuple(Path(p) for p in (read_roots or []))
        self._task_scope = task_scope

    def decide(self, tool_name: str, tool_input: dict | None) -> tuple[bool, str]:
        """对一次工具调用做门禁裁决。

        Args:
            tool_name: Hook 收到的工具名（可能全限定）。
            tool_input: 工具参数。

        Returns:
            ``(allow, reason)`` 二元组；deny 时 reason 为拒绝提示。
        """
        try:
            params = tool_input if isinstance(tool_input, dict) else {}
            bare = bare_tool_name(tool_name, self._server_name)
            if not tool_name.startswith("mcp__"):
                # 非 MCP 工具面：Skill 与受限内置写入放行，其余防御性 deny
                # （命令类工具仍关闭；内置写入仅允许落在会话产物目录内）
                if bare == "Skill" or tool_name.startswith("Skill"):
                    return True, "skill allowed"
                if bare in WEB_SEARCH_TOOL_NAMES:
                    self._audit("allow", bare, bare, "web search allowed")
                    return True, "web search allowed"
                if bare in READ_TOOL_NAMES:
                    return self._decide_read(tool_name, bare, params)
                if bare in BUILTIN_WRITE_TOOL_NAMES:
                    return self._decide_builtin_write(tool_name, bare, params)
                return self._deny(
                    tool_name, bare, params,
                    "未知工具面，已拒绝（Fail-Closed）",
                    confirmable=False,
                )
            kind = classify_tool(bare)
            if kind == "login":
                # 绝对禁止：业务登录不查票、确认亦无法解除
                return self._deny(
                    tool_name, bare, params,
                    "webchat 会话已持凭据，禁用登录类工具",
                    confirmable=False,
                )
            if kind in ("write", "provision"):
                # 条件性拒绝：无票 deny 并要求确认，经 confirm 铸票后窗口内放行
                if self._task_scope is not None and isinstance(params, dict):
                    tid = params.get("task_id")
                    if tid:
                        # 携带 task_id 的写：登记/刷新活动作用域，供后续无 task 写归并
                        self._task_scope.note(self._session_id, str(tid))
                # 作用域仅对 need-params 之外的 write 生效：provision/登记入参工具
                # （如 edge_get_token）保持 tool_name 目标，避免新边缘环境误并入旧作用域
                active = ""
                if (
                    self._task_scope is not None
                    and kind == "write"
                    and bare not in GATED_PARAM_REGISTRY
                ):
                    active = self._task_scope.active(self._session_id)
                target = resolve_target(bare, params, active_scope=active)
                if active and target == active:
                    # 归并命中：作用域随活跃续期，避免长批次中途丢作用域
                    self._task_scope.note(self._session_id, active)
                if self._grants.check(self._session_id, target):
                    self._audit("allow", bare, target, "")
                    return True, "grant valid"
                if kind == "provision" or bare in GATED_PARAM_REGISTRY:
                    # 需现场填凭据/参数：引导至参数卡片，不得走会话口令
                    reason = (
                        "开辟边缘会话需在确认卡片内填写凭据后重试"
                        if kind == "provision"
                        else "该写入需在确认卡片内补充参数后重试"
                    )
                else:
                    # 仅需确认的无参写：回喂模型，令其在会话内播报摘要并请求 /确认
                    reason = (
                        "写入需用户确认：请先在会话中播报将执行的操作与关键参数"
                        "摘要（含影响台数），再请求用户回复行首 /确认 授权；"
                        "不得自行假定已授权，不得以口令索要密码或验证码。"
                    )
                return self._deny(
                    tool_name, bare, params, reason,
                    target=target, confirmable=True,
                )
            return True, "read allowed"
        except Exception as exc:  # noqa: BLE001 - Fail-Closed
            return False, f"gate error: {type(exc).__name__}"

    def check_builtin_write(self, tool_input: dict | None) -> tuple[bool, str]:
        """无副作用地校验内置写入路径/扩展名（供权限请求回调复用）。

        路径 MUST 经 ``resolve()``（跟随符号链接）后位于
        ``${workspace}/xlpa-output/``；越界、缺参、非白名单扩展名、未注入
        工作区一律返回不可放行结论。本方法不写事件、不写审计。
        """
        params = tool_input if isinstance(tool_input, dict) else {}
        raw_path = params.get("file_path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            return False, "缺少 file_path，已拒绝（Fail-Closed）"
        if self._workspace_dir is None:
            return False, "会话工作区未配置，内置写入工具保持关闭"
        candidate = Path(raw_path.strip())
        if not candidate.is_absolute():
            candidate = self._workspace_dir / candidate
        try:
            resolved = candidate.resolve()
            output_root = (self._workspace_dir / _OUTPUT_SUBDIR).resolve()
        except (OSError, RuntimeError):
            return False, "路径无法解析，已拒绝（Fail-Closed）"
        if not resolved.is_relative_to(output_root):
            return (
                False,
                f"仅允许写入会话产物目录 {_OUTPUT_SUBDIR}/，当前路径越界",
            )
        if resolved.suffix.lower() not in WRITABLE_OUTPUT_EXTENSIONS:
            return (
                False,
                "仅允许生成文本类文档（md/txt/csv/json/html 等），"
                "当前扩展名不被支持",
            )
        return True, "workspace output write"

    def check_read(self, tool_input: dict | None) -> tuple[bool, str]:
        """无副作用地校验内置 Read 路径是否在允许根内。

        路径 MUST 经 ``resolve()``（跟随符号链接）后位于会话工作区或 canonical
        技能目录；相对路径按会话工作区解析（与 CLI 的 cwd 一致）。越界、缺参、
        未配置根目录一律返回不可放行结论。本方法不写事件、不写审计。
        """
        params = tool_input if isinstance(tool_input, dict) else {}
        raw_path = params.get("file_path") or params.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            return False, "缺少 file_path，已拒绝（Fail-Closed）"
        if not self._read_roots:
            return False, "未配置可读目录，内置读取保持关闭"
        candidate = Path(raw_path.strip())
        if not candidate.is_absolute() and self._workspace_dir is not None:
            candidate = self._workspace_dir / candidate
        try:
            resolved = candidate.resolve()
            roots = [root.resolve() for root in self._read_roots]
        except (OSError, RuntimeError):
            return False, "路径无法解析，已拒绝（Fail-Closed）"
        if not any(resolved.is_relative_to(root) for root in roots):
            return (
                False,
                "仅允许读取会话工作区、技能目录与配置的额外目录，当前路径越界",
            )
        if resolved.suffix.lower() == ".pdf":
            # 上传 PDF 由后端自动抽取为旁路文件；引导模型读旁路而不是二进制 PDF
            sidecar = pdf_sidecar_name(resolved)
            hint = (
                f"请读取自动抽取的文本：{sidecar}"
                if (resolved.parent / sidecar).exists()
                else (
                    f"应读取自动抽取的文本：{sidecar}"
                    "（后台提取尚未完成或已失败，请稍后重试或如实告知用户）"
                )
            )
            return (
                False,
                f"PDF 是二进制文件，无法直接解析；{hint}",
            )
        return True, "read allowed"

    def _decide_read(
        self, tool_name: str, bare: str, tool_input: dict
    ) -> tuple[bool, str]:
        """内置读取裁决：仅会话工作区与 canonical 技能目录内放行。"""
        ok, reason = self.check_read(tool_input)
        if ok:
            self._audit("allow", bare, bare, reason)
            return True, reason
        guard = "pdf_binary" if reason.startswith("PDF ") else "read_path"
        return self._deny(
            tool_name, bare, tool_input, reason, confirmable=False,
            guard=guard,
        )

    def _decide_builtin_write(
        self, tool_name: str, bare: str, tool_input: dict
    ) -> tuple[bool, str]:
        """内置写入裁决：仅会话产物目录内、文本类扩展名放行。

        校验逻辑见 ``check_builtin_write``；不满足条件一律 deny 且不可经
        用户确认解除（策略限制），拒绝路径统一写 gate_blocked 事件与审计。
        """
        ok, reason = self.check_builtin_write(tool_input)
        if ok:
            self._audit("allow", bare, bare, reason)
            return True, "workspace output write allowed"
        return self._deny(
            tool_name, bare, tool_input, reason, confirmable=False,
            guard="builtin_write_path",
        )

    def _deny(
        self,
        tool_name: str,
        bare: str,
        tool_input: dict,
        reason: str,
        *,
        target: str | None = None,
        confirmable: bool = True,
        guard: str = "",
    ) -> tuple[bool, str]:
        """统一拒绝路径：写 gate_blocked 事件（含摘要与可确认标记）+ 审计。

        ``confirmable`` 区分拒绝语义：True 为条件性拒绝（经用户确认铸票可
        解除），False 为绝对禁止（策略禁止，确认无法解除）。``guard`` 为
        可选护栏标识（如 ``builtin_write_path``），供前端把"自纠错型"
        路径护栏降级为弱提示，不与平台写入禁止同层级展示。
        """
        resolved = target or resolve_target(bare, tool_input)
        # 确认语义分类：供系统提示与前端分流——
        #   param_card：登记入参的工具（需现场填凭据）→ 参数表单卡；
        #   chat_confirm：仅需确认的无参写→ 会话口令 /确认；
        #   guard：护栏自纠错（路径/PDF）→ 弱提示；forbidden：绝对禁止。
        if not confirmable:
            confirm_kind = "guard" if guard else "forbidden"
        else:
            confirm_kind = (
                "param_card" if bare in GATED_PARAM_REGISTRY else "chat_confirm"
            )
        payload = {
            "tool_name": bare,
            "target": resolved,
            "reason": reason,
            "confirmable": confirmable,
            "confirm_kind": confirm_kind,
            "arg_summary": self._arg_summary(resolved, tool_input),
            "param_schema": build_param_schema(bare, tool_input),
        }
        if guard:
            payload["guard"] = guard
        if self._event_writer is not None:
            self._event_writer("gate_blocked", payload)
        self._audit("deny", bare, resolved, reason)
        return False, reason

    def _arg_summary(self, target: str, tool_input: dict) -> dict:
        """构造确认卡片参数摘要（入参白名单 + 计划域反查分层）。

        反查不足时明示「摘要不可用，仅显示计划标识」，MUST NOT 静默
        展示空摘要冒充完整参数（design D5）。
        """
        summary: dict = dict(build_arg_summary(tool_input))
        has_plan_fields = any(
            k in summary for k in ("device_total", "device_types", "node_count")
        )
        if not has_plan_fields and self._summary_lookup is not None:
            try:
                extra = self._summary_lookup(target) or {}
            except Exception:  # noqa: BLE001 - 反查失败降级为明示不可用
                extra = {}
            for key, value in extra.items():
                if key not in summary:
                    summary[key] = value
            has_plan_fields = any(
                k in summary
                for k in ("device_total", "device_types", "node_count")
            )
        if not has_plan_fields:
            summary.setdefault("note", "摘要不可用，仅显示计划标识")
        return summary

    def _audit(
        self, decision: str, bare: str, target: str, reason: str
    ) -> None:
        """追加一条门禁审计记录（台账不随会话生命周期清理）。"""
        if self._audit_writer is None:
            return
        self._audit_writer({
            "ts": time.time(),
            "session_id": self._session_id,
            "target": target,
            "tool_name": bare,
            "decision": decision,
            "reason": reason,
        })
