"""XLPA 自动建档原子 MCP 工具注册。

将边缘建档能力拆分为可审计的原子工具，由 XLPA Skill 按 dry-run 计划、
用户确认和阶段结果编排调用；不提供不可审计的一键黑盒建档工具。

会话模型：``read_device_archive_template`` 解析 Excel 并生成 ``task_id``，
边缘凭据（password 等）仅保存在服务端内存会话中，后续工具用 ``task_id``
引用，绝不作为工具参数反复传递，也不在任何返回中输出明文。

写入/下发/召测类工具均返回动作、关键入参摘要、返回码、返回消息与是否成功。
"""

from __future__ import annotations

__all__ = ["register_edge_tools", "edge_sessions", "template_store"]

import hashlib
import inspect
import io
import json
import secrets
import tempfile
import threading
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from archiving.compensation import CompensationRecorder, DELETE_DEVICE_PATH, apply_compensation
from archiving.converter import AddressConversionError, convert_comm_address, validate_device_address
from archiving.engine import build_existing_index, build_plan
from archiving.excel_reader import ArchiveTemplate, TemplateReadError, read_archive_template
from archiving.models import TemplateSnapshot, TopologyNode
from archiving.log_sanitizer import sanitize_report
from archiving.stage_orchestrator import StageOrchestrator, StageState
from archiving.profiles.base import (
    METER_DEPLOY_ITEM_ID,
    normalize_auth_param_for_deploy,
)
from archiving.profiles.registry import default_registry
from archiving.snapshot_store import SnapshotStore, derive_owner_id as _derive_snapshot_owner
from archiving.task_report_store import TaskReportStore, TaskReportError
from archiving.templates.generator import generate_template, TEMPLATE_VERSION
from archiving.template_migrator import migrate_template, MigrateStatus
from edge_client import (
    EdgeApiError,
    EdgeDeviceClient,
    PORTAL_PROXY_API_URL,
)
from session import mcp_token_var
from operation_log_store import default_store

# 进程共享的写操作日志存储（与 server 侧同一单例）
_op_store = default_store()

# 边缘后端端点（来源 Path B 实测）
PATH_MODIFY_DEVICE = "/devArchManager/doc/set/modifyDevice/v1"
PATH_GET_DEVICE_PARAM = "/devArchManager/doc/get/getDeviceParam/v1"
PATH_MODIFY_DEVICE_PARAM = "/devArchManager/doc/set/modifyDeviceParam/v1"
GATEWAY_ADDRESS_ITEM_ID = "20100024"
PATH_UPDATE_PARENT = "/devArchManager/doc/set/updateDeviceParent/v1"
PATH_GET_DEVICE_TREE = "/devArchManager/doc/get/getDeviceTree/v1"
PATH_GET_DEVICE_LIST_BY_PID = "/devArchManager/doc/get/getDeviceListByPId/v1"
PATH_GET_DEVICE_LIST = "/devArchManager/doc/get/getDeviceList/v1"
# 感知事件数据查询（照明/配电房在线判定：时间窗内该设备有上报即在线）
PATH_SMART_EVENT = "/dataCenter/data/get/getSmartEventData/v1"
PATH_CALL_DEVICE_DATA = "/sysConfigServer/comm/get/callDeviceData/v1"
PATH_SET_DEVICE_PARAM = "/sysConfigServer/comm/set/setDeviceParam/v1"
# 网关时钟召测只传devId，不附加猜测的itemId。
PATH_CALL_CLOCK = "/devArchManager/clock/action/callClock/v1"
# 监测点运维调试召测（实测契约：itemId=31800006，dataItem 包裹结构）
PATH_CALL_DEVICE_PARAM = (
    "/sysConfigServer/comm/get/callDeviceParam/v1"
)
# 监测点召测固定数据项（实测 31800006）
MONITOR_DEBUG_ITEM_ID = "31800006"


def _err(message: str, **extra) -> dict:
    """构造统一错误返回。"""
    payload = {"ok": False, "error": True, "message": message}
    payload.update(extra)
    return payload


def _action_result(action: str, summary: dict, resp: dict) -> dict:
    """将边缘响应归一化为写入类工具返回结构。

    Args:
        action: 动作名。
        summary: 关键入参摘要（已脱敏）。
        resp: EdgeDeviceClient 归一化响应。

    Returns:
        含 action / request_summary / rtnCode / rtnMsg / ok / data 的字典。
    """
    return {
        "ok": bool(resp.get("ok")),
        "error": not bool(resp.get("ok")),
        "action": action,
        "request_summary": summary,
        "rtnCode": resp.get("rtnCode"),
        "rtnMsg": resp.get("rtnMsg", ""),
        "data": resp.get("data"),
        "http_status": resp.get("http_status"),
        "transport_stage": resp.get("stage"),
    }


class EdgeSession:
    """一次自动建档任务的服务端会话状态。

    Attributes:
        template: 解析后的任务模板（含边缘凭据，不外泄）。
        owner_id: 归属身份摘要（由 MCP Token 派生）。
        file_id: 关联的快照 ID（可为空，兼容旧路径入口）。
        created_at: 创建时间（ISO 字符串）。
        expires_at: 到期时间（ISO 字符串，默认 24 小时）。
    """

    # 会话有效期（秒）
    SESSION_TTL_SECONDS = 24 * 3600

    def __init__(
        self,
        template: ArchiveTemplate | None = None,
        *,
        owner_id: str = "",
        file_id: str = "",
    ) -> None:
        """初始化会话。

        Args:
            template: 解析后的任务模板（含边缘凭据，不外泄）。
                独立登录场景（edge_get_token）可为 None。
            owner_id: 归属身份摘要。
            file_id: 关联的快照 ID。
        """
        self.template = template
        self.owner_id = owner_id
        self.file_id = file_id
        now = datetime.now(timezone.utc)
        self.created_at = now.isoformat(timespec="seconds")
        self.expires_at = (
            now.replace(second=0, microsecond=0)
            + timedelta(seconds=self.SESSION_TTL_SECONDS)
        ).isoformat(timespec="seconds")
        self.client: EdgeDeviceClient | None = None
        self.recorder = CompensationRecorder()
        self.key_to_device_id: dict[str, str] = {}
        self.last_plan: dict = {}
        # design §7：已完成动作追踪（幂等重试）
        self.completed_actions: dict[str, dict] = {}
        # 当前有效 plan_id
        self.active_plan_id: str = ""
        # design §7：阶段失败记录（阻止后续下发）
        self.stage_failures: dict[str, str] = {}
        # design §7.5：下发摘要供变更检测
        self.last_deploy_summary: dict = {}
        # design §8：网关时钟时间参考（gateway_dev_id → clock_time）
        self.gateway_clock_times: dict[str, str] = {}
        self.action_lock = threading.RLock()
        self.report_id = ""
        self.actions: list[dict] = []
        self.stages: dict[str, StageOrchestrator] = {}
        self.pending_action: dict | None = None
        self.action_outcomes: dict[str, dict] = {}
        self.evidence_revision = 0

    def is_expired(self) -> bool:
        """判断会话是否已过期。"""
        try:
            exp = datetime.fromisoformat(self.expires_at)
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) > exp
        except ValueError:
            return True


class EdgeSessionStore:
    """内存会话存储，task_id -> EdgeSession。

    支持归属校验与过期回收：
      - get() 检查归属 owner_id 与会话有效期
      - drop() 关闭边缘客户端连接
      - 重启不恢复写操作（内存存储，进程重启即清空）
    """

    def __init__(self) -> None:
        """初始化空存储。"""
        self._sessions: dict[str, EdgeSession] = {}
        self._lock = threading.Lock()

    def create(
        self,
        template: ArchiveTemplate | None = None,
        *,
        owner_id: str = "",
        file_id: str = "",
    ) -> str:
        """创建会话并返回 task_id。

        Args:
            template: 解析后的任务模板。独立登录场景可为 None。
            owner_id: 归属身份摘要。
            file_id: 关联的快照 ID。
        """
        task_id = "xlpa_task_" + secrets.token_hex(8)
        with self._lock:
            self._sessions[task_id] = EdgeSession(
                template, owner_id=owner_id, file_id=file_id,
            )
        return task_id

    def create_token_session(
        self,
        *,
        owner_id: str = "",
    ) -> str:
        """创建无模板的独立登录会话并返回 task_id。

        用于 ``edge_get_token`` 工具：仅持有已登录的边缘客户端，
        不关联建档模板。

        Args:
            owner_id: 归属身份摘要。
        """
        task_id = "edge_token_" + secrets.token_hex(8)
        with self._lock:
            self._sessions[task_id] = EdgeSession(
                None, owner_id=owner_id,
            )
        return task_id

    def get(
        self, task_id: str, *, owner_id: str = "",
    ) -> EdgeSession | None:
        """按 task_id 取会话，检查归属与有效期。

        Args:
            task_id: 任务 ID。
            owner_id: 请求方归属（非空时强制校验）。

        Returns:
            存在且有效返回 EdgeSession，否则 None。
        """
        with self._lock:
            session = self._sessions.get(task_id)
        if session is None:
            return None
        if session.is_expired():
            self.drop(task_id)
            return None
        if owner_id and session.owner_id and session.owner_id != owner_id:
            return None
        return session

    def drop(self, task_id: str) -> bool:
        """删除会话并关闭其边缘客户端。"""
        with self._lock:
            session = self._sessions.pop(task_id, None)
        if session and session.client:
            session.client.close()
            return True
        return session is not None

    def purge_expired(self) -> int:
        """清理已过期会话。"""
        expired_ids = []
        with self._lock:
            for tid, sess in self._sessions.items():
                if sess.is_expired():
                    expired_ids.append(tid)
        for tid in expired_ids:
            self.drop(tid)
        return len(expired_ids)


edge_sessions = EdgeSessionStore()

# 模板快照私有存储（design §2）
template_store = SnapshotStore()


def _current_owner_id() -> str:
    """从当前 MCP Token 派生归属身份摘要。"""
    return _derive_snapshot_owner(mcp_token_var.get(""))


def _generate_template_bytes(**kwargs) -> bytes:
    """生成 v14 模板并返回字节（不写用户可见路径）。

    Args:
        **kwargs: 透传给 generate_template 的字典参数。

    Returns:
        模板 XLSX 字节。
    """
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        generate_template(tmp_path, **kwargs)
        return Path(tmp_path).read_bytes()
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _client_for(session: EdgeSession) -> EdgeDeviceClient:
    """惰性创建并登录边缘客户端。

    代理模式下自动启用门户代理转发，无需调用方感知。
    代理地址未配置或缺少手机号/验证码时拒绝代理模式请求。

    Args:
        session: 会话状态。

    Returns:
        已登录的 EdgeDeviceClient。

    Raises:
        EdgeApiError: 登录失败、网络错误、代理地址未配置或缺少凭据。
    """
    if session.client is None:
        if session.template is None:
            raise EdgeApiError(
                "当前会话未绑定建档模板（edge_get_token 会话），"
                "不支持需要惰性登录的建档工具",
            )
        cfg = session.template.task_config
        if cfg.proxy_mode and not PORTAL_PROXY_API_URL:
            raise EdgeApiError(
                "门户代理未配置，无法连接 20.* 网段的边缘后端。"
                "请联系服务端管理员配置门户代理后重试。",
            )
        if cfg.proxy_mode and (not cfg.phone or not cfg.captcha):
            raise EdgeApiError(
                "20.* 网段建档需要手机号和验证码，"
                "请在模板「系统连接」sheet 填写手机号和验证码。",
            )
        client = EdgeDeviceClient(
            cfg.edge_base_url,
            cfg.login_name,
            cfg.password,
            request_timeout=cfg.request_timeout,
            link_timeout=cfg.link_timeout,
            proxy_mode=cfg.proxy_mode,
            phone=cfg.phone,
            captcha=cfg.captcha,
        )
        client.login()
        session.client = client
    return session.client


def _resolve_node(session: EdgeSession, node_key: str):
    """按节点键解析 profile 与明细，返回 (node, profile, detail, error)。"""
    if session.template is None:
        return None, None, {}, _err(
            "当前会话未绑定建档模板，此工具需要模板会话"
            "（通过 read_device_archive_template 创建）",
        )
    node = session.template.node_map().get(node_key)
    if node is None:
        return None, None, {}, _err(f"节点键 {node_key} 未在模板拓扑总览中定义")
    profile, lookup_err = default_registry.resolve(node.device_type, "")
    if profile is None or not getattr(profile, "supported", True):
        return node, None, {}, _err(lookup_err or f"设备类型 {node.device_type} 不可用")
    if profile.is_gateway:
        detail = session.template.gateway_details.get(node_key, {})
    else:
        # 非网关即监测点（XLBA/照明/配电房）：明细照常加载
        detail = session.template.meter_details.get(node_key, {})
    return node, profile, detail, None


def _validate_plan_guard(
    session: EdgeSession,
    plan_id: str,
    confirm: bool,
    node_key: str,
    expected_action: str,
) -> dict | None:
    """计划动作守卫：校验 plan_id、confirm、动作资格与幂等。

    design §7：写入类原子工具增加 plan_id 与 confirm，
    服务端校验计划、调用者、节点、阶段和允许标志。

    Args:
        session: 会话状态。
        plan_id: 调用方传入的计划 ID。
        confirm: 调用方是否已确认。
        node_key: 目标节点键。
        expected_action: 期望动作（create/skip）。

    Returns:
        校验失败返回错误字典；通过返回 None。
    """
    qualify_err = _validate_plan_guard_qualify(
        session, plan_id, confirm, node_key, expected_action,
    )
    if qualify_err is not None:
        return qualify_err
    return _validate_plan_guard_idempotent(session, expected_action, node_key)


def _validate_plan_guard_qualify(
    session: EdgeSession,
    plan_id: str,
    confirm: bool,
    node_key: str,
    expected_action: str = "create",
) -> dict | None:
    """校验 plan_id、confirm 与计划动作资格（不含幂等检查）。

    Args:
        session: 会话状态。
        plan_id: 计划 ID。
        confirm: 是否已确认。
        node_key: 目标节点键。
        expected_action: 期望动作。

    Returns:
        校验失败返回错误字典；通过返回 None。
    """
    if not confirm:
        return _err("写入操作需用户确认（confirm=true）")
    if not session.active_plan_id:
        return _err("未生成计划，请先调用 plan_device_archive")
    if plan_id != session.active_plan_id:
        return _err(
            f"plan_id 不匹配（期望 {session.active_plan_id}，"
            f"实际 {plan_id}），计划可能已过期"
        )
    if not session.last_plan.get("executable", False):
        return _err("计划存在冲突或模板错误，禁止执行")
    plan_items = session.last_plan.get("items", [])
    node_action = None
    for item in plan_items:
        if item.get("node_key") == node_key:
            node_action = item.get("action")
            break
    if node_action is None:
        return _err(f"节点 {node_key} 未在计划中定义")
    if node_action != expected_action:
        if node_action == "skip":
            return _err(
                f"节点 {node_key} 计划动作为 SKIP，"
                f"不执行 {expected_action}"
            )
        return _err(
            f"节点 {node_key} 计划动作 {node_action} "
            f"与期望 {expected_action} 不符"
        )
    return None


def _validate_plan_guard_idempotent(
    session: EdgeSession,
    action_prefix: str,
    node_key: str,
) -> dict | None:
    """幂等检查：已完成动作返回缓存记录。

    Args:
        session: 会话状态。
        action_prefix: 动作前缀（create/mount/deploy 等）。
        node_key: 目标节点键。

    Returns:
        幂等命中返回缓存字典（含 idempotent_hit=True）；未命中返回 None。
    """
    action_key = f"{session.active_plan_id}:{action_prefix}:{node_key}"
    if action_key in session.completed_actions:
        cached = dict(session.completed_actions[action_key])
        cached["idempotent_hit"] = True
        return cached
    return None


def _plan_item(session: EdgeSession, node_key: str) -> dict:
    """查找当前计划中唯一的节点动作。"""
    return next(
        (item for item in session.last_plan.get("items", [])
         if item.get("node_key") == node_key),
        {},
    )


def _parse_stages(stages: str) -> dict[str, bool]:
    """解析 stages 字符串为各阶段开关。

    逗号分隔、去空白、转小写；为空或含 all 时档案与三联通阶段全开；
    否则仅按 clock/deploy/monitor 命中，档案阶段关闭（供联通重试）。

    Args:
        stages: all/clock/deploy/monitor 的组合（逗号分隔）。

    Returns:
        含 archive/clock/deploy/monitor 四个布尔的字典。
    """
    tokens = {t.strip().lower() for t in (stages or "").split(",") if t.strip()}
    known = tokens & {"all", "clock", "deploy", "monitor"}
    if not known or "all" in known:
        return {
            "archive": True, "clock": True, "deploy": True, "monitor": True,
        }
    return {
        "archive": False,
        "clock": "clock" in known,
        "deploy": "deploy" in known,
        "monitor": "monitor" in known,
    }


def _stage_succeeded(session: EdgeSession, key: str, stage: str) -> bool:
    """某节点某阶段本任务内是否已 SUCCEEDED（供续跑跳过已完成阶段）。"""
    orch = session.stages.get(key)
    if orch is None:
        return False
    rec = orch.records.get(stage)
    return rec is not None and rec.state == StageState.SUCCEEDED


def _stage_for(session: EdgeSession, node_key: str) -> StageOrchestrator:
    """获取节点的适用阶段，未执行阶段必须显式出现在报告中。"""
    if node_key not in session.stages:
        node, profile, _, _ = _resolve_node(session, node_key)
        stages = ["archive_read", "parameter_save"]
        if profile and profile.is_gateway:
            stages.append("gateway_clock")
            if any(
                batch.get("gateway_key") == node_key and batch.get("meter_keys")
                for batch in session.last_plan.get("deploy_batches", [])
            ):
                stages.append("param_deploy")
        else:
            stages.extend(["param_deploy", "monitor_debug"])
        session.stages[node_key] = StageOrchestrator(required_stages=tuple(stages))
        for name in stages:
            session.stages[node_key].record_stage(
                name, StageState.NOT_RUN, "尚无本任务执行回执，等待前置条件和独立确认",
            )
    return session.stages[node_key]


def _persist_report(task_id: str, session: EdgeSession) -> str:
    """在执行前后持久化同一份脱敏报告。"""
    # 独立会话无 template，使用空值
    if session.template is not None:
        cfg = session.template.task_config
        sensitive = (cfg.password, cfg.captcha, cfg.phone, mcp_token_var.get(""))
        stages_dict = {
            node.node_key: sanitize_report(
                _stage_for(session, node.node_key).summary(), sensitive,
            )
            for node in session.template.nodes
        }
    else:
        sensitive = ("", "", "", mcp_token_var.get(""))
        stages_dict = {}
    report = TaskReportStore().save(
        task_id=task_id,
        owner_id=session.owner_id,
        report_id=session.report_id,
        plan_summary=sanitize_report(session.last_plan, sensitive),
        actions=sanitize_report(session.actions, sensitive),
        compensation=sanitize_report(session.recorder.plan.to_dict(), sensitive),
        stage_failures=sanitize_report(session.stage_failures, sensitive),
        stages=stages_dict,
    )
    session.report_id = report.report_id
    return report.report_id


_EDGE_STATE_MAP = {
    "SUCCEEDED": "SUCCESS", "FAILED": "ERROR", "BLOCKED": "ERROR",
    "UNVERIFIED": "UNVERIFIED", "PARTIAL": "PARTIAL",
}


def _action_duration_ms(action: dict) -> int:
    """由动作起止时间推算耗时（毫秒），不可解则返回 0。"""
    try:
        start = datetime.fromisoformat(action["started_at"])
        end = datetime.fromisoformat(action["finished_at"])
        return max(0, int((end - start).total_seconds() * 1000))
    except (KeyError, TypeError, ValueError):
        return 0


def _record_edge_action(tool_name: str, action: dict, result: Any, args: Any) -> dict:
    """将 _tracked_action 的动作落入写操作日志并返回内联摘要（fail-open）。"""
    try:
        mcp_token = mcp_token_var.get("")
        owner_id = _current_owner_id()
        state = str(action.get("state") or "")
        status = _EDGE_STATE_MAP.get(state, "UNKNOWN")
        code = str((result.get("code") if isinstance(result, dict) else "") or state)
        # 下钻证据：把逐请求的实际报文（含 path/状态/指纹/payload）随日志
        # 一并留存（边缘为 JSON 接口，无原始 Modbus 字节帧；payload 落库时经脱敏）。
        logged = result
        if isinstance(result, dict):
            dispatches = [d for d in (action.get("dispatches") or []) if isinstance(d, dict)]
            if dispatches:
                logged = {**result, "dispatches": [
                    {"path": d.get("path"), "state": d.get("state"),
                     "payload_digest": d.get("payload_digest"), "payload": d.get("payload")}
                    for d in dispatches
                ]}
        entry = _op_store.record(
            mcp_token=mcp_token, tool=tool_name, status=status, code=code,
            args=args, result=logged, source="edge", access_level="user",
            duration_ms=_action_duration_ms(action),
            started_at=str(action.get("started_at", "")), secrets_=(mcp_token,),
        )
        return {
            "entry_id": entry.entry_id, "trace_id": entry.trace_id,
            "status": entry.status, "code": entry.code,
            "duration_ms": entry.duration_ms,
        }
    except Exception as exc:  # noqa: BLE001 - 日志子系统不得影响业务
        print(f"[WARNING] 边缘写操作日志记录失败({tool_name}): {exc}")
        return {}


def _tracked_action(
    stage: str, key_argument: str, require_template: bool = True,
    dedup: bool = True,
) -> Callable[[Callable[..., dict]], Callable[..., dict]]:
    """为原子动作添加串行执行、持久化意图、结果和防重发。

    Args:
        stage: 阶段名称。
        key_argument: 关键参数名称。
        require_template: 是否要求会话绑定建档模板，默认 True。
            设为 False 时允许独立登录会话执行。
        dedup: 是否对同参数重复调用做幂等去重与档案变更失效
            拦截，默认 True。联通类普通操作（下发/召测/时钟）
            设为 False：每次真实发送、不查缓存、不因档案变更被拦。
    """
    def decorate(function: Callable[..., dict]) -> Callable[..., dict]:
        signature = inspect.signature(function)

        @wraps(function)
        def tracked(*args, **kwargs) -> dict:
            arguments = signature.bind(*args, **kwargs)
            arguments.apply_defaults()
            values = arguments.arguments
            task_id = values["task_id"]
            session = edge_sessions.get(task_id, owner_id=_current_owner_id())
            if session is None:
                return _err("会话不存在或已过期")
            if require_template and session.template is None:
                return _err(
                    "当前会话未绑定建档模板，此工具仅支持模板驱动的会话"
                    "（通过 read_device_archive_template 创建）",
                )
            with session.action_lock:
                if not _current_owner_id() or session.owner_id != _current_owner_id():
                    return _err("无法确认动作归属")
                key = str(values.get(key_argument, ""))
                if key_argument == "device_id":
                    key = next(
                        (nk for nk, did in session.key_to_device_id.items() if did == key), "",
                    )
                fingerprint = hashlib.sha256(
                    json.dumps(dict(values), sort_keys=True, ensure_ascii=False).encode()
                ).hexdigest()
                cache_values = dict(values)
                cache_values.pop("allow_poll", None)
                # 独立会话无 template，跳过 parent_device_id 补全
                if ("parent_device_id" in cache_values
                        and not cache_values["parent_device_id"]
                        and session.template is not None):
                    node = session.template.node_map().get(key)
                    if node:
                        cache_values["parent_device_id"] = session.key_to_device_id.get(
                            node.parent_key, "",
                        )
                if "meter_node_keys" in cache_values:
                    cache_values["meter_node_keys"] = sorted(
                        part.strip() for part in cache_values["meter_node_keys"].split(",")
                        if part.strip()
                    )
                cache_digest = hashlib.sha256(
                    json.dumps(cache_values, sort_keys=True, ensure_ascii=False).encode()
                ).hexdigest()
                # 稳定幂等键：去 plan_id，用动作名+入参内容摘要。
                # 使跨重规划的续跑仍能命中已完成结果；入参变化则摘要变、不串用（D4）。
                cache_key = f"{function.__name__}:{cache_digest}"
                # 独立会话无 active_plan_id，跳过缓存检查
                if (dedup and session.active_plan_id
                        and cache_key in session.action_outcomes):
                    cached = session.action_outcomes[cache_key]
                    if cached.get("evidence_revision") != session.evidence_revision:
                        return _err(
                            "档案变更已使旧回执失效，请重新计划并确认",
                            stage_state="BLOCKED", idempotent_hit=True,
                            report_id=session.report_id, request_sent=False,
                        )
                    # 独立会话无 template，使用空值
                    if session.template is not None:
                        cfg = session.template.task_config
                        return sanitize_report(
                            dict(cached, idempotent_hit=True),
                            (cfg.password, cfg.captcha, cfg.phone,
                             mcp_token_var.get("")),
                        )
                    return dict(cached, idempotent_hit=True)
                action = {
                    "operation_id": secrets.token_hex(12),
                    "action": function.__name__, "node_key": key,
                    "plan_id": values.get("plan_id", ""),
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "state": "UNVERIFIED", "reason": "动作意图已记录，尚无完成回执",
                    "request_sent": False, "dispatches": [],
                    "request_digest": fingerprint,
                }
                session.actions.append(action)
                session.pending_action = action
                try:
                    _persist_report(task_id, session)
                except (OSError, TaskReportError) as exc:
                    session.pending_action = None
                    action.update(state="BLOCKED", reason="执行前报告保存失败，未调用后端")
                    # 独立会话无 template，使用空值
                    if session.template is not None:
                        cfg = session.template.task_config
                        return sanitize_report(
                            _err(f"执行前报告保存失败，未调用后端: {exc}",
                                 stage_state="BLOCKED", request_sent=False),
                            (cfg.password, cfg.captcha, cfg.phone,
                             mcp_token_var.get("")),
                        )
                    return _err(
                        f"执行前报告保存失败，未调用后端: {exc}",
                        stage_state="BLOCKED", request_sent=False,
                    )
                try:
                    result = function(*args, **kwargs)
                except Exception as exc:
                    result = _err(f"动作异常，须检查回读后重新计划: {exc}")
                finally:
                    session.pending_action = None
                result["request_sent"] = action["request_sent"]
                state = result.get("stage_state")
                if not state:
                    if action["request_sent"] and result.get("http_status") == 200:
                        state = (
                            "FAILED" if result.get("rtnCode") not in (None, 0, "0")
                            else "UNVERIFIED"
                        )
                    else:
                        state = "UNVERIFIED" if action["request_sent"] else "BLOCKED"
                result["stage_state"] = state
                if state != "SUCCEEDED":
                    result.update(ok=False, error=True)
                reason = (
                    result.get("detail") or result.get("message") or result.get("rtnMsg")
                    or ("已取得回读验证证据" if state == "SUCCEEDED" else "缺少完成证据")
                )
                if key and session.template is not None:
                    previous = _stage_for(session, key).records.get(stage)
                    if (
                        state != "BLOCKED" or previous is None
                        or previous.state != StageState.SUCCEEDED
                    ):
                        node = session.template.node_map().get(key)
                        _stage_for(session, key).record_stage(
                            stage, StageState(state), reason, detail=result,
                            gateway_key=(node.parent_key or key) if node else key,
                        )
                action.update({
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "state": state, "reason": reason, "result": result,
                })
                try:
                    result["report_id"] = _persist_report(task_id, session)
                except (OSError, TaskReportError) as exc:
                    result.update(ok=False, error=True, report_error=str(exc))
                    result["stage_state"] = "UNVERIFIED"
                    action.update(state="UNVERIFIED", reason="执行后报告保存失败")
                    if key:
                        _stage_for(session, key).record_stage(
                            stage, StageState.UNVERIFIED, "执行后报告保存失败", detail=result,
                        )
                result["evidence_revision"] = session.evidence_revision
                # 独立会话无 template，跳过脱敏处理
                if session.template is not None:
                    cfg = session.template.task_config
                    result = sanitize_report(
                        result,
                        (cfg.password, cfg.captcha, cfg.phone,
                         mcp_token_var.get("")),
                    )
                if action["request_sent"]:
                    session.action_outcomes[cache_key] = dict(result)
                inline = _record_edge_action(function.__name__, action, result, values)
                if inline and isinstance(result, dict):
                    result.setdefault("operation_log", inline)
                return result
        return tracked
    return decorate


def _call_action(
    task_id: str, session: EdgeSession, path: str, payload: dict, *, link: bool = False,
) -> dict:
    """先记下每次副作用请求的摘要，再调用后端；从不自动重试。"""
    if session.pending_action is None:
        raise RuntimeError("副作用请求缺少动作意图记录")
    dispatch = {
        "path": path, "state": "PREPARED",
        "reason": "发送前意图；若缺少后续回执，发送及完成情况均无法确认",
        "payload_digest": hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest(),
        # 实际请求报文（落库/展示时经脱敏，authParam/password 等凭证字段自动 ***）
        "payload": payload,
    }
    session.pending_action["dispatches"].append(dispatch)
    if path in (
        PATH_MODIFY_DEVICE, PATH_MODIFY_DEVICE_PARAM, PATH_UPDATE_PARENT, DELETE_DEVICE_PATH,
    ):
        # 判断当前操作是否为监测点级别（非网关），不影响网关时钟同步状态
        current_node_key = session.pending_action.get("node_key", "")
        current_node = (
            session.template.node_map().get(current_node_key)
            if session.template else None
        )
        is_monitor_point_save = (
            current_node is not None
            and bool(current_node.parent_key)
            and path != DELETE_DEVICE_PATH
        )
        # 任何重新保存都使既有通信证据失效，不沿用旧下发结果
        session.evidence_revision += 1
        if is_monitor_point_save:
            # 监测点参数保存：只失效当前监测点的 param_deploy 和 monitor_debug
            # 不影响网关的 gateway_clock（时钟同步是网关级操作）
            session.last_deploy_summary.clear()
            orchestrator = _stage_for(session, current_node_key)
            for name in ("param_deploy", "monitor_debug"):
                if name in orchestrator.records:
                    orchestrator.record_stage(
                        name, StageState.NOT_RUN, "档案变更，需重新验收",
                    )
        else:
            # 网关参数保存/建档/挂载/删除：失效所有节点的相关阶段
            session.gateway_clock_times.clear()
            session.last_deploy_summary.clear()
            for orchestrator in session.stages.values():
                for name in ("gateway_clock", "param_deploy", "monitor_debug"):
                    if name in orchestrator.records:
                        orchestrator.record_stage(
                            name, StageState.NOT_RUN, "档案变更，需重新验收",
                        )
        if path == DELETE_DEVICE_PATH:
            for key in session.key_to_device_id:
                for stage in ("archive_read", "parameter_save"):
                    _stage_for(session, key).record_stage(
                        stage, StageState.UNVERIFIED, "补偿请求已准备，需重新计划与回读",
                    )
        target = session.pending_action.get("node_key", "")
        if target:
            _stage_for(session, target).record_stage(
                "parameter_save", StageState.UNVERIFIED, "保存正在执行，等待回读",
            )
    _persist_report(task_id, session)
    client = _client_for(session)
    session.pending_action["request_sent"] = True
    dispatch.update(state="DISPATCHED", reason="已进入客户端调用，等待回执")
    return client.call_link(path, payload) if link else client.call(path, payload)


def _require_stages(session: EdgeSession, node_key: str, stages: tuple[str, ...]) -> dict | None:
    """校验指定节点的前置阶段，缺少回执即阻止。"""
    records = _stage_for(session, node_key).records
    for name in stages:
        record = records.get(name)
        if record is None or record.state != StageState.SUCCEEDED:
            return _err(f"节点 {node_key} 前置阶段 {name} 尚未验证成功", stage_state="BLOCKED")
    return None





def _collect_descendants_leaf_first(tree_data, target_id: str) -> tuple[list[dict], bool]:
    """在设备树中查找目标节点并按叶子优先顺序收集全部后代。

    Args:
        tree_data: getDeviceTree 的 rtnData（树节点列表）。
        target_id: 目标设备 deviceId。

    Returns:
        二元组 ``(descendants, found)``：
          - descendants: 叶子优先排序的节点列表（目标自身在末尾）。
          - found: 是否在树中找到目标节点。
    """
    result: list[dict] = []
    found = False

    def walk(nodes: list) -> bool:
        for node in (nodes or []):
            if not isinstance(node, dict):
                continue
            node_id = str(
                node.get("id") or node.get("deviceId") or ""
            )
            children = node.get("children") or []
            child_ids: list[dict] = []
            if children:
                child_ids = _flatten_devices(children)
            if node_id == target_id:
                result.extend(reversed(child_ids))
                result.append(node)
                return True
            if children and walk(children):
                return True
        return False

    found = walk(tree_data)
    return result, found


def _online_smart_event(session, device_id: str, st_time: str, end_time: str) -> dict:
    """按感知事件判在线（时间窗内该 deviceId 有任意上报即在线）。

    模板与免模板会话共用，避免选路查询逻辑分叉。

    Args:
        session: 已登录的边缘会话。
        device_id: 目标 deviceId。
        st_time: 起始时间（空=今天 00:00:00）。
        end_time: 结束时间（空=今天 23:59:59）。

    Returns:
        ``{ok, online, method, device_id, window, detail}`` 或错误体。
    """
    today = datetime.now().strftime("%Y-%m-%d")
    st = st_time or f"{today} 00:00:00"
    et = end_time or f"{today} 23:59:59"
    summary = {"deviceId": device_id, "dataStTime": st, "dataEndTime": et}
    try:
        resp = _client_for(session).call(
            PATH_SMART_EVENT,
            {"dataStTime": st, "dataEndTime": et, "deviceIds": [device_id]},
        )
    except EdgeApiError as exc:
        return _err(
            f"感知事件查询失败: {exc}", method="smart_event",
            request_summary=summary,
        )
    online = _parse_smart_event_online(resp, device_id)
    return {
        "ok": True, "online": online, "method": "smart_event",
        "device_id": device_id, "window": {"st": st, "end": et},
        "detail": "时间窗内存在感知事件记录=在线（不阻塞）",
    }


def _resolve_profile_and_type(session, node_key: str, device_id: str):
    """解析设备 profile 与类型名，供类型相关的读/判定复用。

    模板会话按 node_key→_resolve_node；免模板按 device_id 读档案→registry。

    Args:
        session: 边缘会话。
        node_key: 模板会话节点键（可为空）。
        device_id: 目标 deviceId（可为空，模板会话下用 node_key 解析）。

    Returns:
        ``(profile, device_type, error)``；error 非空时为一个错误字典。
    """
    if node_key and session.template is not None:
        node, profile, _, err = _resolve_node(session, node_key)
        if err:
            return None, "", err
        return profile, str(getattr(node, "device_type", "") or ""), None
    dev = str(device_id or "").strip()
    if not dev:
        return None, "", _err("需要 device_id 或 node_key 才能确定设备类型")
    try:
        record = _read_device_record(session, dev)
    except EdgeApiError as exc:
        return None, "", _err(f"读取设备档案失败: {exc}")
    dtype = str(record.get("deviceType") or "")
    tid = str(record.get("deviceTypeId") or "")
    prof, _ = default_registry.resolve(dtype, tid)
    return prof, dtype or tid, None


def register_edge_tools(mcp, template_dict_source=None) -> None:
    """将自动建档原子工具注册到 FastMCP 实例。

    Args:
        mcp: FastMCP 实例。
        template_dict_source: 可选异步回调 ``async () -> dict``，返回
            ``generate_template`` 所需的平台字典 kwargs（device_types /
            user_big_nos / comm_modes / brands / models_by_brand）。
            为 None 时生成空字典模板（无平台列）。由 server 注入用系统
            超管 token 拉取字典，从而使用户侧与服务器侧拿到同一份完整模板。
    """

    @mcp.tool()
    def convert_comm_address_tool(identifier: str) -> dict:
        """将设备条码转换为 12 位通讯地址。

        规则：去掉条码第 1、2、7 位后在中间补 3 个 0。
        示例 224356000099 -> 435600000099。

        Args:
            identifier: 12 位纯数字设备条码。
        """
        try:
            return {"ok": True, "identifier": identifier,
                    "deviceAddress": convert_comm_address(identifier)}
        except AddressConversionError as exc:
            return _err(str(exc))

    @mcp.tool()
    async def generate_device_archive_template() -> dict:
        """生成空白自动建档模板并返回文件引用。

        生成时通过服务端内置超管账号拉取平台全量字典（设备类型、用户大
        分类、品牌、型号、代理通信方式），因此无论用户侧还是服务器侧调用，
        拿到的都是含完整平台字典的模板。不创建现场任务，不调用现场接口。
        生成的模板保存在服务端私有目录，后续通过
        get_device_archive_template_download 获取下载信息。

        Returns:
            含 file_id / file_name / size_bytes / sha256 / expires_at 的字典。
        """
        import hashlib
        token = mcp_token_var.get("")
        owner_id = _derive_snapshot_owner(token)
        if not owner_id:
            return _err("无法确定归属身份，请确认已登录")
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        # YYYYMMDDHHMMSS（14 位本地时间戳）
        stamp = "".join(
            c for c in now_iso[:19] if c not in "-T:"
        )
        file_name = f"设备建档模板_{stamp}.xlsx"
        dict_kwargs = {}
        dict_warning = ""
        if template_dict_source is not None:
            try:
                dict_kwargs = await template_dict_source()
            except Exception as exc:  # noqa: BLE001 - 拉取失败降级为空字典模板
                dict_warning = f"平台字典拉取失败，已降级为空字典模板: {exc}"
        try:
            tpl_bytes = _generate_template_bytes(**dict_kwargs)
        except Exception as exc:
            return _err(f"模板生成失败: {exc}")
        snapshot = TemplateSnapshot(
            version=TEMPLATE_VERSION,
            field_contract_version="1.0",
            source_time=now_iso,
        )
        try:
            record = template_store.save(
                snapshot,
                owner_id=owner_id,
                template_bytes=tpl_bytes,
                template_name=file_name,
            )
        except Exception as exc:
            return _err(f"模板存储失败: {exc}")
        # 同一归属只保留最新一份，清理旧快照
        try:
            template_store.purge_old_for_owner(owner_id)
        except Exception:  # noqa: BLE001 - 清理失败不影响主流程
            pass
        result = {
            "ok": True,
            "file_id": record.snapshot_id,
            "file_name": record.template_name,
            "size_bytes": len(tpl_bytes),
            "sha256": hashlib.sha256(tpl_bytes).hexdigest(),
            "expires_at": record.expires_at,
        }
        if dict_warning:
            result["warning"] = dict_warning
        return result

    @mcp.tool()
    def get_device_archive_template_download(file_id: str) -> dict:
        """获取模板下载信息（文件引用、展示名、大小、摘要、有效期）。

        Args:
            file_id: generate_device_archive_template 返回的文件引用。
        """
        import hashlib
        token = mcp_token_var.get("")
        owner_id = _derive_snapshot_owner(token)
        if not owner_id:
            return _err("无法确定归属身份")
        try:
            record = template_store.load(file_id, owner_id=owner_id)
        except Exception as exc:
            return _err(str(exc))
        try:
            tpl_bytes = template_store.read_template_bytes(
                file_id, owner_id=owner_id
            )
        except Exception as exc:
            return _err(f"模板文件读取失败: {exc}")
        return {
            "ok": True,
            "file_id": record.snapshot_id,
            "file_name": record.template_name,
            "size_bytes": len(tpl_bytes),
            "sha256": hashlib.sha256(tpl_bytes).hexdigest(),
            "expires_at": record.expires_at,
            "download_url": (
                f"/api/archive/templates/{record.snapshot_id}"
                f"?owner={owner_id}"
            ),
        }

    @mcp.tool()
    def upload_device_archive_template(
        file_content_base64: str,
        file_name: str = "",
        upload_id: str = "",
        seq: int = -1,
        is_last: bool = False,
    ) -> dict:
        """上传已填建档模板（Base64），返回新的 file_id。

        两种模式：
          - 单次（默认、向后兼容）：直接传完整 Base64。
          - 分块：同时给 upload_id 与非负 seq，每片携带该段
            Base64；末片 is_last=true 后服务端合并并复用与单次
            上传相同的完整校验，产出等价 file_id。用于绕过客户端
            内联/命令行参数大小上限，无需本地传输脚本。

        校验与归属逻辑同 REST /api/archive/uploads：以 MCP 接入 Token
        派生归属、校验 OOXML 结构、存入服务端快照存储。

        Args:
            file_content_base64: 完整或分片内容的 Base64。
            file_name: 展示文件名。
            upload_id: 分块会话 ID（与 seq 成套提供则进入分块模式）。
            seq: 分片序号（非负）。
            is_last: 是否末片（触发合并与校验）。
        """
        import base64
        token = mcp_token_var.get("")
        owner_id = _derive_snapshot_owner(token)
        if not owner_id:
            return _err("无法确定归属身份，请确认已登录")

        def _finalize(body: bytes) -> dict:
            """对完整字节套用单次上传的校验与存储管线。"""
            from archiving.ooxml_validator import (
                validate_ooxml, OOXMLValidationError,
            )
            try:
                zf = validate_ooxml(body)
                zf.close()
            except OOXMLValidationError as exc:
                return _err(f"工作簿结构校验失败: {exc}")
            try:
                record = template_store.save(
                    TemplateSnapshot(version=TEMPLATE_VERSION),
                    owner_id=owner_id,
                    template_bytes=body,
                    template_name=file_name or "upload.xlsx",
                )
            except Exception as exc:  # noqa: BLE001 - 存储失败返回错误
                return _err(f"模板存储失败: {exc}")
            try:
                template_store.purge_old_for_owner(owner_id)
            except Exception:  # noqa: BLE001 - 清理失败不影响主流程
                pass
            return {
                "ok": True,
                "file_id": record.snapshot_id,
                "file_name": record.template_name,
                "size_bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "expires_at": record.expires_at,
            }

        chunk_mode = bool(upload_id) or seq >= 0
        if not chunk_mode:
            try:
                body = base64.b64decode(file_content_base64)
            except Exception as exc:  # noqa: BLE001 - 非法 Base64 统一拒绝
                return _err(f"file_content_base64 不是合法 Base64: {exc}")
            return _finalize(body)

        # 分块模式：upload_id 与非负 seq 必须成套提供
        if not upload_id or seq < 0:
            return _err("分块续传需同时提供 upload_id 与非负 seq")
        try:
            data = base64.b64decode(file_content_base64)
        except Exception as exc:  # noqa: BLE001 - 非法 Base64 统一拒绝
            return _err(f"file_content_base64 不是合法 Base64: {exc}")
        from archiving.snapshot_store import (
            ChunkedUploadError, UploadIncompleteError,
        )
        try:
            state = template_store.append_chunk(
                owner_id, upload_id, seq, data, is_last=is_last,
            )
        except ChunkedUploadError as exc:
            return _err(f"分块上传失败: {exc}")
        if not is_last:
            result = {"ok": True, "mode": "chunk"}
            result.update(state)
            result["message"] = "分块已缓存，等待末片提交"
            return result
        try:
            merged = template_store.read_merged_upload(owner_id, upload_id)
        except UploadIncompleteError as exc:
            return _err(f"分块不完整: {exc}")
        except ChunkedUploadError as exc:
            return _err(f"分块上传失败: {exc}")
        result = _finalize(merged)
        if result.get("ok"):
            result["mode"] = "chunk"
            result["upload_id"] = upload_id
            template_store.discard_upload(owner_id, upload_id)
        return result

    @mcp.tool()
    def migrate_device_archive_template(file_id: str) -> dict:
        """将旧版本建档模板迁移为当前版本。

        服务端把旧版 XLSX 中的用户数据搬运到当前版骨架，补入
        新增 sheet（空表头），更新版本标签后存储为新 file_id。
        客户端随后用 new_file_id 调用 read_device_archive_template。

        Args:
            file_id: 已上传的旧版本模板快照 ID。

        Returns:
            迁移结果字典，含 new_file_id / from_version / to_version /
            added_sheets。版本已是当前时返回原 file_id。
        """
        owner_id = _current_owner_id()
        if not owner_id:
            return _err("无法确定归属身份")
        try:
            old_bytes = template_store.read_template_bytes(
                file_id, owner_id=owner_id,
            )
        except Exception as exc:
            return _err(f"模板不可用: {exc}")
        try:
            skeleton_bytes = _generate_template_bytes()
        except Exception as exc:
            return _err(f"骨架生成失败: {exc}")
        result = migrate_template(old_bytes, skeleton_bytes)
        if result.status == MigrateStatus.ALREADY_CURRENT:
            return {
                "ok": True,
                "new_file_id": file_id,
                "from_version": result.from_version,
                "to_version": result.to_version,
                "added_sheets": [],
                "message": result.reason,
            }
        if result.status == MigrateStatus.REJECTED:
            return _err(result.reason)
        # OK：存储迁移产物
        now_iso = datetime.now(timezone.utc).isoformat()
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        file_name = f"设备建档模板_迁移_{stamp}.xlsx"
        snapshot = TemplateSnapshot(
            version=TEMPLATE_VERSION,
            field_contract_version="1.0",
            source_time=now_iso,
        )
        try:
            record = template_store.save(
                snapshot,
                owner_id=owner_id,
                template_bytes=result.migrated_bytes,
                template_name=file_name,
            )
        except Exception as exc:
            return _err(f"迁移产物存储失败: {exc}")
        return {
            "ok": True,
            "new_file_id": record.snapshot_id,
            "from_version": result.from_version,
            "to_version": result.to_version,
            "added_sheets": result.added_sheets,
        }

    @mcp.tool()
    def read_device_archive_template(
        excel_path: str = "",
        file_id: str = "",
    ) -> dict:
        """解析自动建档 Excel 任务模板并创建会话。

        支持两种入口：
          - file_id（推荐）：从快照存储读取，验证归属与有效期。
          - excel_path（兼容）：服务端本地文件路径。

        返回脱敏后的任务配置、结构化校验结果、节点摘要与 task_id。
        password 等敏感字段不会出现在返回中。

        Args:
            excel_path: 服务端可访问的 .xlsx 模板路径（兼容旧入口）。
            file_id: 快照存储中的文件引用（推荐入口）。
        """
        token = mcp_token_var.get("")
        owner_id = _derive_snapshot_owner(token)
        if file_id:
            # file_id 入口：验证归属、有效期、OOXML 结构
            if not owner_id:
                return _err("无法确定归属身份")
            try:
                tpl_bytes = template_store.read_template_bytes(
                    file_id, owner_id=owner_id,
                )
            except Exception as exc:
                return _err(f"模板不可用: {exc}")
            # OOXML 结构校验
            from archiving.ooxml_validator import (
                validate_ooxml, OOXMLValidationError,
            )
            try:
                zf = validate_ooxml(tpl_bytes)
                zf.close()
            except OOXMLValidationError as exc:
                return _err(f"工作簿结构校验失败: {exc}")
            # 写入临时文件供解析
            with tempfile.NamedTemporaryFile(
                suffix=".xlsx", delete=False,
            ) as tmp:
                tmp.write(tpl_bytes)
                tmp_path = tmp.name
            try:
                template = read_archive_template(tmp_path)
            except TemplateReadError as exc:
                return _err(str(exc))
            finally:
                Path(tmp_path).unlink(missing_ok=True)
            task_id = edge_sessions.create(
                template, owner_id=owner_id, file_id=file_id,
            )
        elif excel_path:
            # 兼容旧入口：本地文件路径
            try:
                template = read_archive_template(excel_path)
            except TemplateReadError as exc:
                return _err(str(exc))
            task_id = edge_sessions.create(
                template, owner_id=owner_id,
            )
        else:
            return _err("必须提供 file_id 或 excel_path")
        return {
            "ok": template.ok,
            "error": not template.ok,
            "task_id": task_id,
            "file_id": file_id,
            "task_config": template.task_config.to_dict(redact=True),
            "node_count": len(template.nodes),
            "nodes": [
                {
                    "node_key": n.node_key,
                    "parent_key": n.parent_key,
                    "device_name": n.device_name,
                    "device_type": n.device_type,
                    "device_id": n.device_id,
                    "road_no": n.road_no,
                }
                for n in template.nodes
            ],
            "supported_types": default_registry.supported_types(),
            "errors": template.errors,
            "warnings": template.warnings,
        }

    @mcp.tool()
    def plan_device_archive(task_id: str) -> dict:
        """基于现有设备树与模板生成 dry-run 计划。

        Args:
            task_id: read_device_archive_template 返回的会话 ID。
        """
        session = edge_sessions.get(task_id, owner_id=_current_owner_id())
        if session is None:
            return _err(f"会话不存在或已过期: {task_id}")
        if session.template is None:
            return _err(
                "当前会话未绑定建档模板，计划工具需要模板会话"
                "（通过 read_device_archive_template 创建）",
            )
        with session.action_lock:
            try:
                client = _client_for(session)
                tree = client.call(PATH_GET_DEVICE_TREE, {})
                if not tree.get("ok") or not isinstance(tree.get("data"), list):
                    return _err("设备树查询未成功，不得当作空现场规划新建")
                existing = _flatten_devices(tree["data"])
                names = {node.device_name for node in session.template.nodes}
                for row in existing:
                    if (row.get("deviceName") or row.get("name")) in names:
                        device_id = str(row.get("deviceId") or row.get("id") or "")
                        row.update(_read_device_record(session, device_id))
                index = build_existing_index(existing)
            except EdgeApiError as exc:
                return _err(f"读取现有档案失败: {exc}")
            plan = build_plan(session.template, index, default_registry)
            session.key_to_device_id = dict(plan.node_key_to_device_id)
            session.last_plan = plan.to_dict()
            session.active_plan_id = plan.plan_id
            # 续跑保留进度：不清空已完成阶段，仅剪除已不在新计划中的节点；
            # 已 SUCCEEDED 的阶段得以延续（D4）。
            new_node_keys = {it.node_key for it in plan.items}
            for k in list(session.stages.keys()):
                if k not in new_node_keys:
                    session.stages.pop(k, None)
            for k in list(session.stage_failures.keys()):
                if k not in new_node_keys:
                    session.stage_failures.pop(k, None)
            # 时钟时间参考与下发汇总与本次计划强相关，重新规划时重置。
            session.gateway_clock_times.clear()
            session.last_deploy_summary.clear()
            # 为已存在档案的节点自动标记 archive_read 为成功
            for item in session.last_plan["items"]:
                node_key = item.get("node_key", "")
                device_id = item.get("device_id", "")
                action = item.get("action", "")
                # skip 动作：档案已存在且一致
                # create/update 动作但 device_id 已存在：档案已存在，可能需要更新
                if node_key and (action == "skip" or device_id):
                    _stage_for(session, node_key).record_stage(
                        "archive_read", StageState.SUCCEEDED,
                        f"档案已存在（action={action}），自动标记",
                    )
            for item in session.last_plan["items"]:
                node, profile, detail, error = _resolve_node(session, item["node_key"])
                if error:
                    continue
                resolved = profile.resolve(node, session.template.task_config, detail)
                if profile.is_gateway:
                    item["parameter_payload"] = {
                        "itemId": GATEWAY_ADDRESS_ITEM_ID,
                        "itemBody": {
                            "commAddr": resolved.base_payload.get("deviceAddress", ""),
                            "identifier": node.identifier,
                        },
                    }
                    item["parameter_action"] = "save_and_verify"
                    if item.get("device_id"):
                        try:
                            current = _read_gateway_address_body(session, item["device_id"])
                            expected = item["parameter_payload"]["itemBody"]
                            item["parameter_current"] = current
                            item["parameter_differences"] = {
                                key: {"current": current.get(key), "expected": value}
                                for key, value in expected.items()
                                if key not in current or str(current[key]) != str(value)
                            }
                            if not item["parameter_differences"]:
                                item["parameter_action"] = "verify_only"
                        except EdgeApiError as exc:
                            item["parameter_action"] = "blocked"
                            item["parameter_error"] = str(exc)
                else:
                    item["parameter_payload"] = {"extInfos": resolved.ext_infos}
                    item["deploy_item_body"] = resolved.deploy_item_body
                    item["parameter_action"] = "verify_after_upsert"
            try:
                report_id = _persist_report(task_id, session)
            except (OSError, TaskReportError) as exc:
                session.active_plan_id = ""
                return _err(f"计划报告保存失败，禁止执行: {exc}")
            return {
                "ok": True, "task_id": task_id, "plan_id": plan.plan_id,
                "plan": sanitize_report(session.last_plan), "report_id": report_id,
            }

    def _order_node_keys(session: EdgeSession, keys: list[str]) -> list[str]:
        """按当前计划 items 拓扑序对 node 键排序去重（未知键置末尾）。"""
        order = [
            it.get("node_key", "")
            for it in (session.last_plan or {}).get("items", [])
        ]
        rank = {nk: i for i, nk in enumerate(order)}
        uniq = [k for k in dict.fromkeys(keys) if k]
        return sorted(uniq, key=lambda k: rank.get(k, len(rank) + 1))

    def _write_batched(
        single_fn, task_id: str, node_key: str, node_keys: str,
        plan_id: str, confirm: bool, include_details: bool = True,
    ) -> dict:
        """按单节点或 node_keys 批量调用 single_fn，聚合逐节点 verdict。

        single_fn(node_key, plan_id, confirm) 返回单节点结果 dict；单节点
        与非连坐批量共用同一 tracked 单元，与逐个调用等价。
        """
        session = edge_sessions.get(task_id, owner_id=_current_owner_id())
        if session is None:
            return _err("会话不存在或已过期")
        keys = [k.strip() for k in (node_keys or "").split(",") if k.strip()]
        if node_key and keys:
            return _err("node_key 与 node_keys 只能二选一")
        if not node_key and not keys:
            return _err("必须提供 node_key 或 node_keys")
        if node_key:
            return single_fn(node_key, plan_id, confirm)
        ordered = _order_node_keys(session, keys)
        per_node: list[dict] = []
        ok_n = fail_n = 0
        for nk in ordered:
            r = single_fn(nk, plan_id, confirm)
            verdict = {
                "node_key": nk, "ok": bool(r.get("ok")),
                "stage_state": r.get("stage_state"),
            }
            for extra in (
                "device_id", "requires_mount", "agent_num_fixed",
                "readback_verified",
            ):
                if extra in r:
                    verdict[extra] = r[extra]
            if not r.get("ok"):
                mm = r.get("mismatches")
                verdict["reason"] = (
                    "；".join(str(x) for x in mm)
                    if isinstance(mm, list) and mm
                    else str(r.get("message") or r.get("detail") or "")
                )
                fail_n += 1
            else:
                ok_n += 1
            per_node.append(verdict)
        details = per_node if include_details else [
            d for d in per_node if not d["ok"]
        ]
        return {
            "ok": fail_n == 0, "mode": "batch", "task_id": task_id,
            "plan_id": plan_id,
            "summary": {
                "total": len(ordered), "succeeded": ok_n, "failed": fail_n,
            },
            "report_id": session.report_id, "details": details,
        }

    def _upsert_one_core(
        task_id: str,
        node_key: str,
        plan_id: str = "",
        confirm: bool = False,
    ) -> dict:
        """建档/更新单节点核心（modifyDevice），由分派器逐节点调用。"""
        session = edge_sessions.get(task_id, owner_id=_current_owner_id())
        if session is None:
            return _err(f"会话不存在或已过期: {task_id}")
        item = _plan_item(session, node_key)
        action = item.get("action", "")
        if action not in ("create", "update"):
            return _err("仅 CREATE/UPDATE 计划可写入；SKIP 使用参数保存工具校验")
        guard_err = _validate_plan_guard(
            session, plan_id, confirm, node_key, action,
        )
        if guard_err is not None:
            # 幂等命中：已完成动作返回记录
            if guard_err.get("idempotent_hit"):
                return guard_err
            return guard_err
        node, profile, detail, err = _resolve_node(session, node_key)
        if err:
            return err
        resolved = profile.resolve(node, session.template.task_config, detail)
        if resolved.errors:
            return _err("；".join(resolved.errors), node_key=node_key)
        prior_id = str(item.get("device_id", ""))
        is_create = action == "create"
        if not is_create and (not prior_id or session.key_to_device_id.get(node_key) != prior_id):
            return _err("UPDATE 缺少计划绑定的唯一设备ID，请重新计划")
        if node.device_id and node.device_id != prior_id:
            return _err("节点设备ID与已确认计划不符")
        if is_create and session.key_to_device_id.get(node_key):
            return _err("节点已有写入结果，须回读并重新计划，禁止重复新建")
        if not is_create:
            current = _read_device_record(session, prior_id)
            expected_parent = str(item.get("parent_device_id", ""))
            if str(current.get("parentId", "")) != expected_parent:
                return _err("设备父级已变化，请重新计划；不会自动迁移")
            if str(current.get("deviceName", "")) != node.device_name:
                return _err("设备名称已变化，请重新计划")
        payload = {
            key: value for key, value in resolved.base_payload.items()
            if value is not None and value != ""
        }
        ext_list = _ext_infos_to_list(resolved.ext_infos, include_empty=False)
        if not is_create:
            # 保留未填写的档案属性，不能假定后端一定按字段合并。
            mutable_keys = set(resolved.base_payload) | {
                "parentId", "collectorAddress", "proxyCommPort", "measuredPointNum",
                "protocolNumber", "agentNum", "deviceAddress", "baudRate",
                "stopDigit", "checkDigit", "dataDigit", "identifier", "proxyCommType",
            }
            preserved = {key: value for key, value in current.items() if key in mutable_keys}
            preserved.update(payload)
            payload = preserved
            existing_ext = {
                row["propertyCode"]: row.get("propertyValue")
                for row in current.get("extInfos", [])
                if isinstance(row, dict) and "propertyCode" in row
            }
            existing_ext.update(resolved.ext_infos)
            ext_list = _ext_infos_to_list(existing_ext, include_empty=True)
        if ext_list:
            payload["extInfos"] = ext_list
        if prior_id and "deviceId" not in payload:
            payload["deviceId"] = prior_id
        summary = {
            "node_key": node_key,
            "deviceName": payload.get("deviceName"),
            "deviceTypeId": payload.get("deviceTypeId"),
            "deviceAddress": payload.get("deviceAddress"),
            "is_create": is_create,
            "ext_info_count": len(ext_list),
        }
        try:
            client = _client_for(session)
            resp = _call_action(task_id, session, PATH_MODIFY_DEVICE, payload)
        except EdgeApiError as exc:
            return _err(f"建档调用失败: {exc}", action="upsert_device",
                        request_summary=summary)
        result = _action_result("upsert_device", summary, resp)
        if not resp.get("ok"):
            return result
        data = resp.get("data")
        new_id = prior_id
        if is_create:
            if isinstance(data, dict):
                new_id = str(data.get("deviceId") or "")
            elif isinstance(data, (str, int)) and not isinstance(data, bool):
                new_id = str(data)
        # modifyDevice 新建不回传 deviceId，回查设备树按条码解析
        resolve_issues: list[str] = []
        if is_create and not new_id:
            new_id, resolve_issues = _resolve_new_device_id(client, node)
        if new_id:
            session.key_to_device_id[node_key] = new_id
            result["device_id"] = new_id
        if resolve_issues:
            result["resolve_issues"] = resolve_issues
        if is_create and new_id:
            # 分路号/测量点号的修正放在挂载之后（updateDeviceParent 会重置为 1）
            parent_id = session.key_to_device_id.get(node.parent_key, "")
            session.recorder.record_created(
                node_key, new_id, node.device_name, parent_id
            )
        verified, mismatches = (
            _readback_verify_device(session, node, new_id) if new_id
            else (False, ["写入返回后未能唯一确定设备ID"])
        )
        result.update(
            ok=verified, error=not verified,
            readback_verified=verified, mismatches=mismatches,
            stage_state="SUCCEEDED" if verified else "UNVERIFIED",
            requires_mount=bool(is_create and node.parent_key),
            idempotent_hit=False,
        )
        if verified and new_id:
            actual = _read_device_record(session, new_id)
            all_ext = {
                row["propertyCode"]: row["propertyValue"] for row in ext_list
            }
            mismatches = _compare_archive_fields(payload, all_ext, actual)
            verified = not mismatches
            result.update(
                ok=verified, error=not verified, readback_verified=verified,
                mismatches=mismatches, stage_state="SUCCEEDED" if verified else "UNVERIFIED",
            )
        if not verified:
            session.stage_failures[node_key] = "；".join(mismatches)
            result["detail"] = "已返回写入回执，但档案回读未通过；不能视为建档验收完成"
        else:
            session.stage_failures.pop(node_key, None)
        # 网关 CREATE 成功后立即保存通讯地址参数（20100024）
        if (
            is_create and verified and new_id
            and profile.is_gateway
        ):
            gw_auto = _save_gateway_parameters_auto(
                session, node, new_id, resolved, task_id,
            )
            result["parameter_auto_save"] = gw_auto
            if gw_auto.get("mismatches"):
                result.update(
                    ok=False, error=True, readback_verified=False,
                    stage_state="UNVERIFIED",
                )
                result["detail"] = (
                    "建档回读通过，但通讯地址参数自动保存未通过"
                )
                session.stage_failures[node_key] = (
                    "；".join(gw_auto["mismatches"])
                )
            else:
                session.stage_failures.pop(node_key, None)
        session.completed_actions[f"{plan_id}:{action}:{node_key}"] = dict(result)
        return result

    # 审计/幂等按工具名记账：批处理逐节点复用同一 tracked 单元，
    # 与逐个调用 edge_upsert_device 完全等价。
    _upsert_one_core.__name__ = "edge_upsert_device"
    _upsert_tracked = _tracked_action("archive_read", "node_key")(_upsert_one_core)

    @mcp.tool()
    def edge_upsert_device(
        task_id: str,
        node_key: str = "",
        node_keys: str = "",
        plan_id: str = "",
        confirm: bool = False,
        include_details: bool = True,
    ) -> dict:
        """建档或更新设备（modifyDevice），支持单节点或 node_keys 批量。

        单节点传 node_key；批量传逗号分隔 node_keys（服务端按当前计划
        拓扑序逐节点写入，返回逐节点 verdict，非连坐）。两模式共用同一
        tracked 单元，守卫/幂等/回读/审计/补偿与逐个调用等价。

        Args:
            task_id: 会话 ID。
            node_key: 单个拓扑节点键（与 node_keys 二选一）。
            node_keys: 逗号分隔的批量节点键（与 node_key 二选一）。
            plan_id: 计划 ID（来自 plan_device_archive 返回）。
            confirm: 用户是否已确认执行。
            include_details: 批量时是否返回逐节点全量（false 仅失败项）。
        """
        def single(nk: str, pid: str, cf: bool) -> dict:
            return _upsert_tracked(
                task_id=task_id, node_key=nk, plan_id=pid, confirm=cf,
            )
        return _write_batched(
            single, task_id, node_key, node_keys, plan_id, confirm,
            include_details,
        )

    def _mount_one_core(
        task_id: str,
        node_key: str,
        parent_device_id: str = "",
        plan_id: str = "",
        confirm: bool = False,
    ) -> dict:
        """挂载单节点核心（updateDeviceParent），由分派器逐节点调用。"""
        session = edge_sessions.get(task_id, owner_id=_current_owner_id())
        if session is None:
            return _err(f"会话不存在或已过期: {task_id}")
        # 计划守卫（仅 CREATE 节点可挂载）
        # 先校验资格（用 create 检查计划动作是否为 create）
        guard_err = _validate_plan_guard_qualify(
            session, plan_id, confirm, node_key,
        )
        if guard_err is not None:
            return guard_err
        # 幂等检查用 mount
        idempotent_err = _validate_plan_guard_idempotent(
            session, "mount", node_key,
        )
        if idempotent_err is not None:
            return idempotent_err
        node = session.template.node_map().get(node_key)
        if node is None:
            return _err(f"节点键 {node_key} 未在模板中定义")
        device_id = session.key_to_device_id.get(node_key, "") or node.device_id
        if not device_id:
            return _err(f"节点 {node_key} 尚未建档，无 deviceId 可挂载")
        parent_id = session.key_to_device_id.get(node.parent_key, "")
        if parent_device_id and parent_device_id != parent_id:
            return _err("父设备ID不在确认的挂载关系中，禁止改挂载")
        if not parent_id:
            return _err(f"节点 {node_key} 缺少父设备 deviceId")
        summary = {"node_key": node_key, "deviceId": device_id, "parentId": parent_id}
        try:
            client = _client_for(session)
            resp = _call_action(
                task_id, session, PATH_UPDATE_PARENT,
                {"deviceId": device_id, "parentId": parent_id},
            )
        except EdgeApiError as exc:
            return _err(f"挂载调用失败: {exc}", action="mount_device",
                        request_summary=summary)
        result = _action_result("mount_device", summary, resp)
        if resp.get("ok"):
            # updateDeviceParent 会把分路号/测量点号重置为 1，挂载后重新写入
            fixed = _reapply_agent_num_after_mount(session, node, device_id, task_id=task_id)
            if fixed is not None:
                result["agent_num_fixed"] = fixed
                if fixed is False:
                    # design §7：恢复失败记录为阶段失败，阻止后续下发
                    session.stage_failures[node_key] = (
                        "挂载后分路号/测量点号恢复失败"
                    )
                    result["stage_failure"] = True
        verified, mismatches = _readback_verify_device(session, node, device_id)
        verified = bool(resp.get("ok")) and verified and not result.get("stage_failure", False)
        result.update(
            ok=verified, error=not verified, readback_verified=verified,
            mismatches=mismatches, stage_state="SUCCEEDED" if verified else "UNVERIFIED",
        )
        if verified:
            session.stage_failures.pop(node_key, None)
        else:
            session.stage_failures[node_key] = "；".join(mismatches) or "挂载/编号恢复未验证"
        # 监测点 CREATE+MOUNT 成功后立即保存基本参数
        item = _plan_item(session, node_key)
        is_create = item.get("action") == "create"
        profile, _lookup_err = default_registry.resolve(
            node.device_type, "",
        )
        if (
            is_create and verified and device_id
            and profile and not profile.is_gateway
        ):
            detail = session.template.meter_details.get(node_key, {})
            resolved = profile.resolve(
                node, session.template.task_config, detail,
            )
            meter_auto = _save_meter_parameters_auto(
                session, node, device_id, resolved, detail, task_id,
            )
            result["parameter_auto_save"] = meter_auto
            if meter_auto.get("mismatches"):
                result.update(
                    ok=False, error=True, readback_verified=False,
                    stage_state="UNVERIFIED",
                )
                session.stage_failures[node_key] = (
                    "；".join(meter_auto["mismatches"])
                )
            else:
                session.stage_failures.pop(node_key, None)
        session.completed_actions[f"{plan_id}:mount:{node_key}"] = dict(result)
        return result

    # 审计/幂等按工具名记账：批处理逐节点复用同一 tracked 单元。
    _mount_one_core.__name__ = "edge_mount_device"
    _mount_tracked = _tracked_action("archive_read", "node_key")(_mount_one_core)

    @mcp.tool()
    def edge_mount_device(
        task_id: str,
        node_key: str = "",
        node_keys: str = "",
        parent_device_id: str = "",
        plan_id: str = "",
        confirm: bool = False,
        include_details: bool = True,
    ) -> dict:
        """挂载设备到父节点（updateDeviceParent），支持单节点或 node_keys 批量。

        仅挂载本次新建（CREATE）节点；批量按当前计划拓扑序逐节点挂载、
        非连坐，挂载成功后自动恢复分路号/测量点号。与逐个调用等价。

        Args:
            task_id: 会话 ID。
            node_key: 待挂载节点键（与 node_keys 二选一）。
            node_keys: 逗号分隔的批量节点键（与 node_key 二选一）。
            parent_device_id: 父设备 deviceId；留空则用父节点键映射结果。
            plan_id: 计划 ID。
            confirm: 用户是否已确认执行。
            include_details: 批量时是否返回逐节点全量（false 仅失败项）。
        """
        def single(nk: str, pid: str, cf: bool) -> dict:
            return _mount_tracked(
                task_id=task_id, node_key=nk,
                parent_device_id=parent_device_id, plan_id=pid, confirm=cf,
            )
        return _write_batched(
            single, task_id, node_key, node_keys, plan_id, confirm,
            include_details,
        )

    def _save_one_core(
        task_id: str, node_key: str, plan_id: str = "", confirm: bool = False,
    ) -> dict:
        """参数保存与回读单节点核心，由分派器逐节点调用。"""
        session = edge_sessions.get(task_id, owner_id=_current_owner_id())
        if session is None:
            return _err("会话不存在或已过期")
        item = _plan_item(session, node_key)
        action = item.get("action", "")
        if action not in ("create", "update", "skip"):
            return _err("参数保存节点不在可执行计划中")
        if item.get("parameter_error"):
            return _err("计划未能确定原参数，请恢复查询后重新计划")
        error = _validate_plan_guard_qualify(session, plan_id, confirm, node_key, action)
        if error:
            return error
        node, profile, detail, error = _resolve_node(session, node_key)
        if error:
            return error
        device_id = session.key_to_device_id.get(node_key, "")
        if not device_id:
            return _err("节点尚未取得设备ID")
        if action != "create" and device_id != str(item.get("device_id", "")):
            return _err("参数目标ID与当前计划绑定不一致")
        resolved = profile.resolve(node, session.template.task_config, detail)
        if resolved.errors:
            return _err("；".join(resolved.errors))
        verified, mismatches = _readback_verify_device(session, node, device_id)
        if not verified:
            _stage_for(session, node_key).record_stage(
                "archive_read", StageState.UNVERIFIED, "；".join(mismatches),
            )
            return _err(
                "基本档案回读未通过，先完成CREATE/UPDATE及挂载",
                mismatches=mismatches, stage_state="UNVERIFIED",
            )
        _stage_for(session, node_key).record_stage(
            "archive_read", StageState.SUCCEEDED, "全部已写字段及父级回读一致",
            detail={"device_id": device_id, "readback_verified": True},
        )
        if profile.is_gateway:
            current = _read_device_record(session, device_id)
            body = _read_gateway_address_body(session, device_id)
            if "parameter_current" in item and body != item["parameter_current"]:
                return _err("地址参数自计划后发生变化，请重新计划后确认")
            body = dict(body)
            body.update(
                commAddr=resolved.base_payload["deviceAddress"],
                identifier=resolved.base_payload["identifier"],
            )
            params = {
                "deviceId": device_id, "parentId": current.get("parentId"),
                "params": [{
                    "deviceId": device_id, "itemId": GATEWAY_ADDRESS_ITEM_ID,
                    "itemBody": body,
                }],
            }
            if params["parentId"] is None:
                return _err("无法回读网关实际父级，禁止猜测参数保存parentId")
            if item.get("parameter_action") != "verify_only":
                resp = _call_action(task_id, session, PATH_MODIFY_DEVICE_PARAM, params)
                if not resp.get("ok"):
                    return _action_result("save_device_parameters", {"node_key": node_key}, resp)
            mismatches = _verify_gateway_address(session, device_id, body)
        else:
            # 监测点基本参数保存（modifyDevice 参数设置版）
            mismatches = _save_meter_parameters(
                session, node, device_id, resolved, detail,
                task_id,
            )
        result = {
            "ok": not mismatches, "error": bool(mismatches), "node_key": node_key,
            "device_id": device_id, "readback_verified": not mismatches,
            "mismatches": mismatches,
            "stage_state": "UNVERIFIED" if mismatches else "SUCCEEDED",
        }
        return result

    # 审计/幂等按工具名记账：批处理逐节点复用同一 tracked 单元。
    _save_one_core.__name__ = "edge_save_device_parameters"
    _save_tracked = _tracked_action("parameter_save", "node_key")(_save_one_core)

    @mcp.tool()
    def edge_save_device_parameters(
        task_id: str,
        node_key: str = "",
        node_keys: str = "",
        plan_id: str = "",
        confirm: bool = False,
        include_details: bool = True,
    ) -> dict:
        """保存并回读参数页字段，支持单节点或 node_keys 批量。

        网关写 20100024，XLBA 验证已写扩展参数；批量按当前计划拓扑序
        逐节点保存、非连坐，与逐个调用等价。

        Args:
            task_id: 模板会话 ID。
            node_key: 当前计划节点键（与 node_keys 二选一，含 SKIP）。
            node_keys: 逗号分隔的批量节点键（与 node_key 二选一）。
            plan_id: 已确认计划 ID。
            confirm: 参数保存的独立确认。
            include_details: 批量时是否返回逐节点全量（false 仅失败项）。
        """
        def single(nk: str, pid: str, cf: bool) -> dict:
            return _save_tracked(
                task_id=task_id, node_key=nk, plan_id=pid, confirm=cf,
            )
        return _write_batched(
            single, task_id, node_key, node_keys, plan_id, confirm,
            include_details,
        )

    @mcp.tool()
    def edge_get_device_tree(task_id: str) -> dict:
        """读取边缘后端完整设备树（getDeviceTree）。

        Args:
            task_id: 会话 ID。
        """
        session = edge_sessions.get(task_id, owner_id=_current_owner_id())
        if session is None:
            return _err(f"会话不存在或已过期: {task_id}")
        try:
            client = _client_for(session)
            resp = client.call(PATH_GET_DEVICE_TREE, {})
        except EdgeApiError as exc:
            return _err(f"读取设备树失败: {exc}")
        return _action_result("get_device_tree", {}, resp)

    @mcp.tool()
    def edge_get_device_list(task_id: str, device_id: str, recursive: bool = True) -> dict:
        """读取设备档案列表。

        Args:
            task_id: 会话 ID。
            device_id: 目标设备 deviceId。
            recursive: True 用 getDeviceListByPId 返回自身+全部递归后代；
                False 用 getDeviceList 返回单设备档案字段。
        """
        session = edge_sessions.get(task_id, owner_id=_current_owner_id())
        if session is None:
            return _err(f"会话不存在或已过期: {task_id}")
        path = PATH_GET_DEVICE_LIST_BY_PID if recursive else PATH_GET_DEVICE_LIST
        summary = {"deviceId": device_id, "recursive": recursive}
        try:
            client = _client_for(session)
            resp = client.call(path, {"deviceId": device_id})
        except EdgeApiError as exc:
            return _err(f"读取设备列表失败: {exc}", request_summary=summary)
        return _action_result("get_device_list", summary, resp)

    @mcp.tool()
    def edge_get_device_parameters(
        task_id: str,
        device_id: str = "",
        node_key: str = "",
        item_ids: str = "",
    ) -> dict:
        """通用读取设备当前已配置的参数项（getDeviceParam）。

        模板与免模板会话均可，直连与代理都支持。读到的内容随设备类型
        而不同：网关默认读 20100024（通讯地址），监测点（XLBA/照明/
        配电房）默认读 20200002（抄表运行参数）。可用 item_ids（逗号
        分隔）显式读取任意数据项（可多个）。宽松读取：项缺失记
        present=false，不报错、不回退模板值。

        Args:
            task_id: 会话 ID。
            device_id: 目标 deviceId（免模板必填；模板可缺省用 node_key）。
            node_key: 模板会话节点键（用于解析类型与 deviceId）。
            item_ids: 显式数据项 ID 列表（逗号分隔）；留空按设备类型取默认项。

        Returns:
            {ok, device_id, itemIds, deviceType, params:[{itemId, present,
            count, itemBody}]}。
        """
        session = edge_sessions.get(task_id, owner_id=_current_owner_id())
        if session is None:
            return _err(f"会话不存在或已过期: {task_id}")
        dev = str(device_id or "").strip()
        if not dev and node_key and session.template is not None:
            node, _, _, _ = _resolve_node(session, node_key)
            dev = str(
                session.key_to_device_id.get(node_key, "")
                or (getattr(node, "device_id", "") if node else "") or ""
            )
        if not dev:
            return _err("缺少 deviceId：请提供 device_id 或（模板会话）node_key")

        ids = [x.strip() for x in (item_ids or "").split(",") if x.strip()]
        device_type = ""
        if not ids:
            prof, dtype, err = _resolve_profile_and_type(session, node_key, dev)
            if err is not None:
                return err
            device_type = dtype
            if prof is not None and getattr(prof, "is_gateway", False):
                ids = [GATEWAY_ADDRESS_ITEM_ID]
            elif prof is not None and getattr(prof, "deploy_item_id", ""):
                ids = [str(prof.deploy_item_id)]
            else:
                ids = [METER_DEPLOY_ITEM_ID]

        summary = {"deviceId": dev, "itemIdS": ids}
        try:
            client = _client_for(session)
            resp = client.call(PATH_GET_DEVICE_PARAM, {"deviceId": dev, "itemIdS": ids})
        except EdgeApiError as exc:
            return _err(f"读取参数失败: {exc}", request_summary=summary)
        raw = resp.get("data") if isinstance(resp.get("data"), list) else []
        params: list[dict] = []
        for iid in ids:
            matched = [
                it for it in raw if isinstance(it, dict)
                and str(it.get("itemId")) == str(iid)
            ]
            # itemBody 原样透传：后端实测为 list（如电表通信参数），
            # 也可为 dict/标量；不得假定结构或丢弃。
            body = matched[0].get("itemBody") if matched else None
            present = bool(body) and body not in ({}, [])
            params.append({
                "itemId": iid,
                "count": len(matched),
                "present": present,
                "itemBody": body,
            })
        return {
            "ok": bool(resp.get("ok")),
            "device_id": dev,
            "itemIds": ids,
            "deviceType": device_type,
            "params": params,
            "detail": "读取设备当前已配置参数项（不阻塞、不回退模板值）",
        }

    @mcp.tool()
    def edge_delete_device(
        task_id: str, device_id: str, confirm: bool = False,
    ) -> dict:
        """删除设备（自动递归删除子设备，叶子优先顺序）。

        若目标设备有子设备，按叶子优先顺序逐个删除后再删目标。
        confirm=false 时仅返回待删除清单预览，不执行删除。

        Args:
            task_id: 会话 ID。
            device_id: 目标设备 deviceId。
            confirm: 用户是否已确认删除（不可逆）。
        """
        session = edge_sessions.get(task_id, owner_id=_current_owner_id())
        if session is None:
            return _err(f"会话不存在或已过期: {task_id}")
        try:
            client = _client_for(session)
        except EdgeApiError as exc:
            return _err(f"边缘登录失败: {exc}")
        # 获取设备树并查找目标
        tree = client.call(PATH_GET_DEVICE_TREE, {})
        if not tree.get("ok") or not isinstance(tree.get("data"), list):
            return _err("无法读取设备树，禁止删除")
        delete_order, found = _collect_descendants_leaf_first(
            tree["data"], device_id,
        )
        if not found:
            return _err(
                f"设备 {device_id} 未在设备树中找到",
                action="delete_device",
            )
        # 未确认时返回预览
        if not confirm:
            preview = [
                {
                    "deviceId": str(
                        n.get("id") or n.get("deviceId") or ""
                    ),
                    "deviceName": str(n.get("name") or ""),
                }
                for n in delete_order
            ]
            return {
                "ok": False,
                "action": "delete_device",
                "confirmed": False,
                "delete_order": preview,
                "count": len(preview),
                "message": "设备删除不可逆，需用户确认（confirm=true）",
            }
        # 按叶子优先顺序逐个删除
        results: list[dict] = []
        deleted: list[str] = []
        failed: list[str] = []
        for node in delete_order:
            did = str(node.get("id") or node.get("deviceId") or "")
            resp = client.call(
                DELETE_DEVICE_PATH, {"deviceId": did},
            )
            ok = bool(resp.get("ok"))
            results.append({
                "deviceId": did,
                "deviceName": str(node.get("name") or ""),
                "ok": ok,
                "rtnCode": resp.get("rtnCode"),
                "rtnMsg": resp.get("rtnMsg", ""),
            })
            if ok:
                deleted.append(did)
            else:
                failed.append(did)
                break
        remaining = [
            str(n.get("id") or n.get("deviceId") or "")
            for n in delete_order
            if str(n.get("id") or n.get("deviceId") or "")
            not in deleted
        ]
        return {
            "ok": not failed and not remaining,
            "action": "delete_device",
            "confirmed": True,
            "deleted": deleted,
            "failed": failed,
            "remaining": remaining,
            "results": results,
        }

    @mcp.tool()
    def edge_get_token(
        ip: str,
        username: str,
        password: str,
        port: int = 7500,
        phone: str = "",
        captcha: str = "",
    ) -> dict:
        """独立登录边缘后端，返回 task_id 供后续读取/删除类 edge_* 工具使用。

        无需建档模板，直接以 IP/账号/密码登录边缘后端。
        返回的 task_id 可用于 edge_delete_device、edge_get_device_tree、
        edge_get_device_list 等不依赖档案模板的边缘工具。
        联通类下发/召测/时钟与读取、删除类工具均可在本会话执行；
        建档计划与档案写入类工具仍需模板驱动的会话。

        目标 IP 为 20.* 段时自动启用门户代理模式，
        需要额外提供 phone（手机号）和 captcha（验证码）。

        Args:
            ip: 边缘后端 IP 地址。
            username: 登录账号。
            password: 登录密码。
            port: 边缘后端端口（默认 7500）。
            phone: 手机号，20.* 代理模式必填。
            captcha: 验证码，20.* 代理模式必填。
        """
        base_url = f"http://{ip}:{port}"
        # 按 IP 段自动判定连接模式：20.* 走门户代理
        proxy_mode = ip.strip().startswith("20.")
        if proxy_mode and not PORTAL_PROXY_API_URL:
            return _err(
                "门户代理未配置，无法连接 20.* 网段的边缘后端。"
                "请联系服务端管理员配置门户代理后重试。",
            )
        if proxy_mode and (not phone or not captcha):
            return _err(
                "20.* 网段需要门户代理登录，"
                "请提供 phone（手机号）和 captcha（验证码）参数。",
            )
        # 门户代理模式需要更长的超时时间（转发链路较长）
        link_timeout = 30.0 if proxy_mode else None
        client = EdgeDeviceClient(
            base_url,
            username,
            password,
            proxy_mode=proxy_mode,
            phone=phone,
            captcha=captcha,
            link_timeout=link_timeout,
        )
        try:
            client.login()
        except EdgeApiError as exc:
            return _err(f"边缘后端登录失败: {exc}")
        owner_id = _current_owner_id()
        task_id = edge_sessions.create_token_session(owner_id=owner_id)
        session = edge_sessions.get(task_id, owner_id=owner_id)
        if session is not None:
            session.client = client
        # 开启本次操作会话窗：边缘独立登录刷新当前 trace
        _op_store.set_current_trace(owner_id, _op_store.next_trace_id())
        return {
            "ok": True,
            "task_id": task_id,
            "proxy_mode": proxy_mode,
            "message": "边缘后端登录成功，task_id 可用于后续 edge_* 工具",
        }

    @mcp.tool()
    @_tracked_action(
        "param_deploy", "gateway_node_key",
        require_template=False, dedup=False,
    )
    def edge_set_device_param(
        task_id: str,
        gateway_node_key: str,
        confirm: bool = False,
        meter_node_keys: str = "",
        plan_id: str = "",
        check_online: bool = False,
        batch_size: int = 0,
    ) -> dict:
        """向网关机下发监测点参数（支持单/多网关批量/全量下发，通用能力）。

        两种数据源按会话类型分派，互不读取对方信息：
        - 模板会话：下发 plan 中按工程填报值算好的 deploy_item_body。
        - 免模板直连会话（edge_get_token）：逐台实时读后端当前参数
          （getDeviceParam itemId 20200002）并原样回推。
        单台无有效参数（模板侧缺填报值、免模板侧读不到记录）仅跳过
        该台，不连坐其余目标，也不做档案字段兜底。
        支持批量下发和全量下发（meter_node_keys为空时自动收集所有监测点）。
        支持单网关或多网关下发（gateway_node_key 可接受逗号分隔的多个网关）。
        准入仅需 confirm 确认；阶段/计划状态以 warnings 呈现，不阻断。
        支持基于网关时钟召测的可达性检查与分批下发（仅模板会话）。

        Args:
            task_id: 会话 ID。
            gateway_node_key: 目标网关；模板会话为节点键，免模板会话
                为网关标识（name/identifier/deviceId），支持逗号分隔。
            confirm: 用户是否已确认下发；未确认时不执行。
            meter_node_keys: 逗号分隔的监测点，为空表示全量下发；
                免模板会话下按设备标识解析。
            plan_id: 计划 ID（仅记录，不再校验）。
            check_online: 是否要求本会话该网关已成功时钟召测以确认可达（默认False）。
            batch_size: 分批下发数量，0表示不分批（默认0）。

        Returns:
            下发结果。单网关时返回单个网关的结果；多网关时返回汇总结果。
        """
        # 解析多个网关（支持逗号分隔）
        gateway_keys = [
            key.strip() for key in (gateway_node_key or "").split(",") if key.strip()
        ]
        if not gateway_keys:
            return _err("gateway_node_key 不能为空")
        # 向后兼容：单个网关时走原有逻辑
        if len(gateway_keys) == 1:
            return _deploy_to_single_gateway(
                task_id, gateway_keys[0], confirm, meter_node_keys,
                plan_id, check_online, batch_size,
            )
        # 多网关：逐个下发并汇总结果
        results = {}
        all_ok = True
        for gw_key in gateway_keys:
            gw_result = _deploy_to_single_gateway(
                task_id, gw_key, confirm, meter_node_keys,
                plan_id, check_online, batch_size,
            )
            results[gw_key] = gw_result
            if not gw_result.get("ok"):
                all_ok = False
        # 汇总结果
        return {
            "ok": all_ok,
            "error": not all_ok,
            "action": "set_device_param",
            "scope": "multi_gateway",
            "gateway_count": len(gateway_keys),
            "gateway_results": results,
            "message": f"多网关下发完成，总计{len(gateway_keys)}个网关",
        }

    def _deploy_without_template(
        task_id: str,
        session: EdgeSession,
        gateway_node_key: str,
        meter_node_keys: str,
        check_online: bool,
        warnings: list[str],
        batch_size: int = 0,
    ) -> dict:
        """免模板直连会话下发：逐台实时读后端当前参数回推。

        不读取任何模板或计划信息；下发内容为 getDeviceParam 读回的
        itemId 20200002 itemBody 原样回推（仅 authParam 按下发侧形态
        归一）。某台读不到仅跳过该台，不连坐其余目标，
        也不做档案字段兜底。

        Args:
            task_id: 会话 ID。
            session: 已解析的直连会话（template 为 None）。
            gateway_node_key: 网关标识（name/identifier/deviceId）。
            meter_node_keys: 逗号分隔监测点标识，空为全量。
            check_online: 是否要求本会话该网关成功时钟召测过。
            warnings: 告警收集列表（调用方传入）。
            batch_size: 分批大小，免模板路径不分批。

        Returns:
            下发结果，含 included / skipped / device_count 与阶段结论。
        """
        tree_result = edge_get_device_tree(task_id=task_id)
        if not tree_result.get("ok"):
            return _err(
                f"读取设备树失败: {tree_result.get('message', '')}"
            )
        tree = tree_result.get("data")
        if not isinstance(tree, list) or not tree:
            return _err("设备树为空，无法定位网关")
        gateway = _find_device_in_tree(tree, gateway_node_key)
        if gateway is None:
            return _err(f"网关 {gateway_node_key} 不在设备树中")
        gw_id = str(gateway.get("id") or gateway.get("deviceId") or "")
        if not gw_id:
            return _err(f"网关 {gateway_node_key} 无 deviceId")
        # 可达门禁：与模板路径同一判据（本会话成功时钟召测记录）
        if check_online and gw_id not in session.gateway_clock_times:
            return _err(
                f"网关 {gw_id} 本会话尚未成功时钟召测，无法确认可达性；"
                "请先调用 edge_call_clock(task_id, device_id, confirm=true)",
                next_action="edge_call_clock",
                gateway_reachable=False,
            )
        if batch_size > 0:
            warnings.append("免模板下发不分批，本次按整体下发")
        requested = [
            key.strip() for key in (meter_node_keys or "").split(",")
            if key.strip()
        ]
        meters: list[str] = []
        skipped: list[tuple[str, str]] = []
        if requested:
            for item in requested:
                node = _find_device_in_tree(tree, item)
                if node is None:
                    skipped.append((item, "不在设备树中"))
                    continue
                dev_id = str(node.get("id") or node.get("deviceId") or "")
                if not dev_id:
                    skipped.append((item, "无 deviceId"))
                    continue
                if dev_id == gw_id:
                    skipped.append((item, "下发目标不能是网关自身"))
                    continue
                meters.append(dev_id)
        else:
            meters = _collect_meter_device_ids(tree, gateway_node_key, gw_id)
        deduped: list[str] = []
        seen: set[str] = set()
        for meter_id in meters:
            if meter_id not in seen:
                seen.add(meter_id)
                deduped.append(meter_id)
        if not deduped:
            return _err(
                f"网关 {gateway_node_key} 下无可下发的监测点",
                skipped=[{"device_id": k, "reason": r} for k, r in skipped],
            )
        # 逐台取下发参数：先读现成 20200002，读不到则回退从档案组装
        item_bodies: list[dict] = []
        included: list[str] = []
        deploy_sources: dict[str, str] = {}
        for meter_id in deduped:
            body: dict | None = None
            source = "backend_param"
            try:
                body = _read_deploy_param_body(session, meter_id)
            except EdgeApiError:
                body = None
            if not body:
                source = "archive"
                try:
                    body = _build_deploy_body_from_archive(session, meter_id)
                except EdgeApiError as exc:
                    skipped.append((meter_id, f"无现成参数且档案组装失败：{exc}"))
                    continue
            # authParam 归一：现值或档案五段串均转下发侧 12 位十六进制（无来源占位全 E）
            body["authParam"] = normalize_auth_param_for_deploy(
                str(body.get("authParam") or ""),
            )
            # 不注入 deviceId：两份现场抓包均证实 itemBody 条目不带该键，
            # 网关按 commAddr／roadNo 定位目标
            item_bodies.append(body)
            included.append(meter_id)
            deploy_sources[meter_id] = source
        if not item_bodies:
            return _err(
                "所有目标均未查到当前参数（20200002），未发出任何下发请求",
                skipped=[{"device_id": k, "reason": r} for k, r in skipped],
            )
        payload = {
            "deviceId": gw_id,
            "dataItemList": [
                {"itemId": METER_DEPLOY_ITEM_ID, "itemBody": item_bodies},
            ],
        }
        summary = {
            "deviceId": gw_id,
            "gateway": gateway_node_key,
            "itemId": METER_DEPLOY_ITEM_ID,
            "point_count": len(item_bodies),
            "deploy_sources": deploy_sources,
            "archive_built": sum(1 for s in deploy_sources.values() if s == "archive"),
        }
        try:
            client = _client_for(session)
            original_sign_headers = client._sign_headers

            def _sign_headers_with_forward() -> dict:
                """注入下发转发头（与模板路径一致）。"""
                headers = original_sign_headers()
                headers.setdefault("ForwardType", "SmartUnit")
                headers.setdefault("ForwardPort", "7500")
                if not client.proxy_mode:
                    headers.setdefault("ForwardUrl", "http://undefined")
                    headers.setdefault("webSite", "http://undefined")
                headers.setdefault("PhoneNum", "undefined")
                headers.setdefault("Code", "undefined")
                headers.setdefault("SepToken", "null")
                return headers

            client._sign_headers = _sign_headers_with_forward
            try:
                resp = _call_action(
                    task_id, session, PATH_SET_DEVICE_PARAM,
                    payload, link=True,
                )
            finally:
                client._sign_headers = original_sign_headers
        except EdgeApiError as exc:
            return _err(f"下发调用失败: {exc}", request_summary=summary)
        # 成功判据：rtnCode == 0（ok 由 _normalize 派生）
        ok = bool(resp.get("ok"))
        result = _action_result("set_device_param", summary, resp)
        if warnings:
            result["warnings"] = list(warnings)
        result.update(
            ok=ok, error=not ok,
            state="ACCEPTED" if ok else "UNCLEAR",
            stage_state="SUCCEEDED" if ok else "UNVERIFIED",
            message=(
                f"免模板下发成功，总计{len(item_bodies)}个设备"
                if ok
                else f"下发失败: {resp.get('rtnMsg', '未知错误')}"
            ),
            state_explanation="接口已接受请求，设备执行结果未验证，请勿自动重发",
            included=included,
            skipped=[{"device_id": k, "reason": r} for k, r in skipped],
            device_count=len(item_bodies),
            param_source="backend_current",
        )
        return result

    def _deploy_to_single_gateway(
        task_id: str,
        gateway_node_key: str,
        confirm: bool,
        meter_node_keys: str,
        plan_id: str,
        check_online: bool,
        batch_size: int,
    ) -> dict:
        """向单个网关机下发监测点参数（内部函数）。

        模板会话下发内容为 plan 中按填报值算好的 deploy_item_body，
        单台无有效填报值仅跳过该台；准入仅 confirm 守卫，阶段/计划
        状态以 warnings 呈现不阻断。plan_id 仅记录不校验。
        免模板直连会话转 _deploy_without_template 处理。
        """
        session = edge_sessions.get(task_id, owner_id=_current_owner_id())
        if session is None:
            return _err(f"会话不存在或已过期: {task_id}")
        deploy_warnings: list[str] = []
        # design §7：阶段失败改为告警呈现，不再阻断下发
        if session.stage_failures:
            failed_nodes = ", ".join(sorted(session.stage_failures.keys()))
            deploy_warnings.append(
                f"存在阶段失败节点（{failed_nodes}），请人工复核后再下发"
            )
        if not confirm:
            return _err("参数下发写审计日志，需用户二次确认（confirm=true）")
        # 免模板直连会话：实时查后端当前参数逐台回推，不读任何模板信息
        if session.template is None:
            return _deploy_without_template(
                task_id, session, gateway_node_key, meter_node_keys,
                check_online, deploy_warnings, batch_size,
            )
        gw_node = session.template.node_map().get(gateway_node_key)
        if gw_node is None:
            return _err(f"网关节点键 {gateway_node_key} 未在模板中定义")
        gw_id = session.key_to_device_id.get(gateway_node_key, "") or gw_node.device_id
        if not gw_id:
            return _err(f"网关 {gateway_node_key} 尚未建档，无 deviceId")
        _, profile, _, error = _resolve_node(session, gateway_node_key)
        if error or not profile.is_gateway:
            return error or _err("下发目标必须为网关")
        # 记录是否为全量下发（在填充requested_keys之前）
        is_full_deploy = not meter_node_keys
        requested_keys = [
            key.strip() for key in (meter_node_keys or "").split(",") if key.strip()
        ]
        # 允许空值表示全量下发，自动收集网关下所有监测点节点
        if not requested_keys:
            all_point_keys = _collect_all_monitor_point_keys(session, gateway_node_key)
            if not all_point_keys:
                return _err(f"网关 {gateway_node_key} 下无可下发的监测点")
            requested_keys = all_point_keys
        elif len(requested_keys) != len(set(requested_keys)):
            return _err("meter_node_keys包含重复节点")
        # 存在性校验：节点键有效且已建档（deviceId 是实时读参的必要条件）
        for key in requested_keys:
            node = session.template.node_map().get(key)
            if node is None:
                return _err(f"下发节点 {key} 不存在")
            if not (session.key_to_device_id.get(key, "") or node.device_id):
                return _err(f"监测点 {key} 尚未建档，无 deviceId")
            # 档案回读（重试3次）仅用于父级一致性告警，不阻断下发
            record = None
            last_error = None
            for attempt in range(3):
                try:
                    record = _read_device_record(
                        session, session.key_to_device_id.get(key, "")
                    )
                    break
                except Exception as e:
                    last_error = e
                    if attempt < 2:
                        import time
                        time.sleep(1 * (attempt + 1))  # 递增延迟
            if record is None:
                return _err(
                    f"读取设备 {key} 记录失败（重试3次）: {last_error}"
                )
            parent_id = session.key_to_device_id.get(node.parent_key, "")
            actual_parent = str(record.get("parentId", ""))
            if parent_id and actual_parent and actual_parent != parent_id:
                deploy_warnings.append(
                    f"设备 {key} 实际归属({actual_parent})与模板({parent_id})"
                    "不一致，已按模板网关继续下发，请复核拓扑"
                )
        item_bodies_by_item_id, included_keys, skipped = (
            _build_monitor_point_item_body(
                session, gateway_node_key, requested_keys
            )
        )
        if not item_bodies_by_item_id:
            reasons = "；".join(f"{k}: {r}" for k, r in skipped) or "无有效下发目标"
            return _err(
                f"网关 {gateway_node_key} 下无可下发的监测点: {reasons}",
                skipped=[{"node_key": k, "reason": r} for k, r in skipped],
            )
        # 被跳过的目标仅告警，不阻断其余目标下发
        for k, r in skipped:
            deploy_warnings.append(f"监测点 {k} 未纳入下发: {r}")
        # 可达性门禁：本会话该网关存在成功时钟召测记录才放行（不查 43000002）
        if check_online and gw_id not in session.gateway_clock_times:
            return _err(
                f"网关 {gw_id} 本会话尚未成功时钟召测，无法确认可达性；"
                "请先调用 edge_call_clock(task_id, device_id, confirm=true)",
                next_action="edge_call_clock",
                gateway_reachable=False,
            )
        # 按 itemId 分组构建请求体（当前只有 20200002，未来可能多个）
        # 向后兼容：单个 itemId 时行为不变
        data_item_list = [
            {"itemId": item_id, "itemBody": bodies}
            for item_id, bodies in item_bodies_by_item_id.items()
        ]
        payload = {
            "deviceId": gw_id,
            "dataItemList": data_item_list,
        }
        # 记录是否为全量下发（在填充requested_keys之前已记录）
        # 计算总监测点数量
        total_point_count = sum(len(bodies) for bodies in item_bodies_by_item_id.values())
        # itemId 分组（当前统一为监测点当前参数回推项 20200002）
        primary_item_id = next(iter(item_bodies_by_item_id.keys()), METER_DEPLOY_ITEM_ID)
        summary = {
            "gateway_node_key": gateway_node_key,
            "deviceId": gw_id,
            "itemId": primary_item_id,
            "meter_count": total_point_count,
            "meter_keys": sorted(included_keys),
            "scope": "full" if is_full_deploy else "batch",
            "audit": "写入审计日志",
        }
        try:
            client = _client_for(session)
            # 添加页面兼容的请求头（对齐页面抓包结果）
            original_sign_headers = client._sign_headers
            def _sign_headers_with_forward():
                headers = original_sign_headers()
                # 添加 ForwardType、ForwardPort（与页面一致）
                headers.setdefault("ForwardType", "SmartUnit")
                headers.setdefault("ForwardPort", "7500")
                # 添加 ForwardUrl、webSite（直连模式下使用 http://undefined，与页面一致）
                if not client.proxy_mode:
                    headers.setdefault("ForwardUrl", "http://undefined")
                    headers.setdefault("webSite", "http://undefined")
                # 添加 PhoneNum、Code、SepToken（与页面一致）
                headers.setdefault("PhoneNum", "undefined")
                headers.setdefault("Code", "undefined")
                headers.setdefault("SepToken", "null")
                return headers
            client._sign_headers = _sign_headers_with_forward
            try:
                resp = _call_action(task_id, session, PATH_SET_DEVICE_PARAM, payload, link=True)
            finally:
                client._sign_headers = original_sign_headers
        except EdgeApiError as exc:
            return _err(f"下发调用失败: {exc}", request_summary=summary)
        result = _action_result("set_device_param", summary, resp)
        if deploy_warnings:
            result["warnings"] = list(deploy_warnings)
        # 根据后端响应判断接口层面成功/失败
        # 后端统一以 rtnCode == 0 表示成功（ok 由 _normalize 派生）；
        # HTTP 200 或 rtnCode=200 均不计成功
        if resp.get("ok"):
            result["ok"] = True
            result["error"] = False
            result["state"] = "ACCEPTED"
            result["stage_state"] = "SUCCEEDED"
            result["message"] = f"下发成功，总计{total_point_count}个设备"
            # 为实际纳入下发的监测点节点记录 param_deploy 阶段状态
            for meter_key in included_keys:
                _stage_for(session, meter_key).record_stage(
                    "param_deploy", StageState.SUCCEEDED,
                    f"下发成功（网关 {gateway_node_key} 批量下发）",
                    detail={"gateway": gateway_node_key, "rtnCode": resp.get("rtnCode")},
                    gateway_key=gateway_node_key,
                )
        else:
            result["ok"] = False
            result["error"] = True
            result["state"] = "UNCLEAR"
            result["stage_state"] = "UNVERIFIED"
            result["message"] = f"下发失败: {resp.get('rtnMsg', '未知错误')}"
        result["state_explanation"] = "接口已接受请求，设备执行结果未验证，请勿自动重发"
        # 记录本次下发摘要供变更检测
        session.last_deploy_summary = {
            "meter_keys": summary["meter_keys"],
            "meter_count": summary["meter_count"],
        }
        if skipped:
            result["skipped"] = [
                {"node_key": k, "reason": r} for k, r in skipped
            ]
        return result

    @mcp.tool()
    def edge_check_monitor_online(
        task_id: str,
        node_key: str = "",
        device_id: str = "",
        st_time: str = "",
        end_time: str = "",
        road_no: str = "",
        check_method: str = "",
        device_type: str = "",
    ) -> dict:
        """按设备类型判定监测点是否在线（诊断查询，不阻塞任何操作）。

        照明/配电房走感知事件（时间窗内该 deviceId 有任意上报=在线），
        XLBA 等默认走运维召测（31800006 成功=在线）。profile 未声明
        判定方法时默认运维召测；绝不因无法判定而阻断建档/时钟/下发/召测。

        同时支持模板会话（按 node_key 解析类型）与免模板独立登录会话
        （用 device_id，自动读后端档案 deviceTypeId 选路，分路号取 agentNum）；
        直连与代理均可。可用 check_method/device_type/road_no 显式兜底。

        Args:
            task_id: 会话 ID。
            node_key: 监测点节点键（模板会话用于解析类型）。
            device_id: 目标 deviceId（免模板会话必填；模板会话可缺省）。
            st_time: 感知事件查询起始时间（空=今天 00:00:00）。
            end_time: 感知事件查询结束时间（空=今天 23:59:59）。
            road_no: 分路号（免模板且类型走召测时兜底；缺则取档案 agentNum）。
            check_method: 显式指定判定方法（smart_event/monitor_debug），优先于自动派生。
            device_type: 显式设备类型名（免模板时用于查 profile，优先于档案）。

        Returns:
            {ok, online, method, ...}；online 为 True/False/None。
        """
        session = edge_sessions.get(task_id, owner_id=_current_owner_id())
        if session is None:
            return _err(f"会话不存在或已过期: {task_id}")

        # 免模板独立登录会话（edge_get_token）：按后端档案类型自动选路
        if session.template is None:
            dev = str(device_id or "").strip()
            if not dev:
                return _err("独立登录会话需 device_id 判定在线")
            chosen = check_method if check_method in ("smart_event", "monitor_debug") else ""
            road = str(road_no or "").strip()
            if not chosen:
                try:
                    record = _read_device_record(session, dev)
                except EdgeApiError as exc:
                    return _err(f"读取设备档案失败，无法判定类型：{exc}")
                prof, _ = default_registry.resolve(
                    str(device_type or record.get("deviceType") or ""),
                    str(record.get("deviceTypeId") or ""),
                )
                chosen = (getattr(prof, "online_check_method", "monitor_debug")
                          if prof else "monitor_debug")
                road = road or str(record.get("agentNum") or "").strip()
            if chosen == "smart_event":
                return _online_smart_event(session, dev, st_time, end_time)
            # monitor_debug 免模板路径：需分路号
            if not road:
                return {
                    "ok": True, "online": None, "method": chosen, "device_id": dev,
                    "needs_user_input": True,
                    "detail": "该类型默认运维召测，但无分路号；请补传 road_no 或确认 device_type",
                }
            poll = edge_call_monitor_debug(
                task_id=task_id, device_id=dev, road_no=road, confirm=True,
            )
            online = bool(poll.get("monitor_valid") or poll.get("ok"))
            return {
                "ok": True, "online": online, "method": chosen, "device_id": dev,
                "road_no": road, "poll_state": poll.get("stage_state"),
                "detail": "运维召测成功=在线（免模板判定，不阻塞）",
            }

        # 解析类型→判定方法（未声明/未知默认 monitor_debug）
        method = "monitor_debug"
        resolved_device_id = str(device_id or "").strip()
        if node_key:
            node, profile, _, err = _resolve_node(session, node_key)
            if err or node is None:
                return _err(f"无法解析节点 {node_key}: {err or '不存在'}")
            resolved_device_id = (
                resolved_device_id
                or str(session.key_to_device_id.get(node_key, "")
                       or getattr(node, "device_id", "") or "")
            )
            if profile is not None:
                method = getattr(profile, "online_check_method", "monitor_debug")
        if not resolved_device_id:
            return _err("缺少 deviceId：请提供 node_key（已建档）或 device_id")

        if method == "smart_event":
            return _online_smart_event(session, resolved_device_id, st_time, end_time)
        # 默认/未知：运维召测（需 node_key 以解析分路号）
        if not node_key:
            return {
                "ok": True, "online": None, "method": method,
                "device_id": resolved_device_id,
                "needs_user_input": True,
                "detail": (
                    "该类型在线判定默认走运维召测，但未提供 node_key，"
                    "无法解析分路号；不阻塞，仅供参考"
                ),
            }
        poll = edge_call_monitor_debug(
            task_id=task_id, node_key=node_key, confirm=True,
        )
        online = bool(poll.get("monitor_valid") or poll.get("ok"))
        return {
            "ok": True, "online": online, "method": method,
            "device_id": resolved_device_id, "node_key": node_key,
            "poll_state": poll.get("stage_state"),
            "detail": "运维召测成功=在线（判定不阻塞，仅供参考）",
        }

    @mcp.tool()
    @_tracked_action("legacy_diagnostic", "device_id")
    def edge_call_device_data(
        task_id: str, device_id: str, confirm: bool = False, plan_id: str = "",
    ) -> dict:
        """召测设备数据（callDeviceData）。

        保留兼容入口，但不允许绕过31800006契约门禁，始终返回BLOCKED。

        Args:
            task_id: 会话 ID。
            device_id: 目标设备 deviceId。
            confirm: 用户是否确认召测。
            plan_id: 当前计划ID。
        """
        session = edge_sessions.get(task_id, owner_id=_current_owner_id())
        if session is None:
            return _err(f"会话不存在或已过期: {task_id}")
        if not confirm:
            return _err("召测需用户确认（confirm=true）")
        return _err(
            "旧callDeviceData不计入31800006验收，禁止作为未核实通信契约的替代入口",
            stage_state="BLOCKED", contract_unverified=True,
        )

    @mcp.tool()
    @_tracked_action("gateway_clock", "device_id", require_template=False, dedup=False)
    def edge_call_clock(
        task_id: str,
        device_id: str,
        plan_id: str = "",
        confirm: bool = False,
        allow_poll: bool = False,
    ) -> dict:
        """网关时钟召测（callClock，联通类，只读诊断）。

        对应 UI「参数设置-时钟-召测」。请求 body 仅为 ``{"devId": "<ID>"}``，
        不使用 deviceId 代替 devId，也不猜测 itemId。HTTP200 + rtnCode=0
        且 ``rtnData.callTime.clockTime`` 可解析才视为成功。只召测不校时。
        通用能力：准入仅 confirm 确认，不依赖建档阶段状态；目标不在
        当前会话模板时告警照发（与独立会话行为一致）。

        Args:
            task_id: 会话 ID。
            device_id: 目标网关 devId（后端设备 ID）。
            plan_id: 计划 ID（仅记录，不再校验）。
            confirm: 用户是否已确认执行。
            allow_poll: 是否允许异步轮询补取（首版保留，暂未启用）。
        """
        session = edge_sessions.get(task_id, owner_id=_current_owner_id())
        if session is None:
            return _err(f"会话不存在或已过期: {task_id}")
        # 确认守卫
        if not confirm:
            return _err("时钟召测需用户确认（confirm=true）")
        clock_warnings: list[str] = []
        # 区分会话类型：独立登录会话 vs 建档模板会话
        if session.template is None:
            # 独立登录会话（edge_get_token 创建）：简化约束
            if not device_id:
                return _err("device_id 不能为空")
            gw_node_key = ""  # 独立会话无节点键概念
        else:
            # 建档模板会话：目标可解析为会话节点时校验网关类型；
            # 解析不到不阻断，告警后按直连模式照发
            gw_node_key = ""
            for nk, did in session.key_to_device_id.items():
                if did == device_id:
                    gw_node_key = nk
                    break
            if gw_node_key:
                _, profile, _, error = _resolve_node(session, gw_node_key)
                if error:
                    return error
                if not profile.is_gateway:
                    return _err(
                        f"节点 {gw_node_key} 非网关，时钟召测目标必须为网关"
                    )
            else:
                clock_warnings.append(
                    f"目标 {device_id} 非本会话节点，按直连模式照发，"
                    "请确认 devId 正确"
                )
        # 构造请求（design §8：body 仅 devId）
        payload = {"devId": device_id}
        summary = {"devId": device_id, "gateway_node_key": gw_node_key}
        try:
            client = _client_for(session)
            # Portal UI 实测：时钟召测不发送 ForwardUrl 头，由门户根据会话状态自动转发
            original_skip = getattr(client, "_skip_proxy_headers", False)
            client._skip_proxy_headers = True
            try:
                resp = _call_action(task_id, session, PATH_CALL_CLOCK, payload, link=True)
            finally:
                client._skip_proxy_headers = original_skip
        except EdgeApiError as exc:
            return _err(
                f"时钟召测调用失败：{exc}", request_summary=summary,
            )
        # 解析 clockTime
        clock_time = ""
        rtn_data = resp.get("data")
        if isinstance(rtn_data, dict):
            call_time = rtn_data.get("callTime")
            if isinstance(call_time, dict):
                value = call_time.get("clockTime")
                clock_time = "" if value is None else str(value).strip()
        result = _action_result("call_clock", summary, resp)
        if clock_warnings:
            result["warnings"] = list(clock_warnings)
        result["state"] = resp.get("state")
        result["clock_time"] = clock_time
        result["clock_time_valid"] = False
        # clockTime 有效性校验
        if resp.get("ok") and not clock_time:
            result["ok"] = False
            result["error"] = True
            result["clock_time_valid"] = False
            result["detail"] = "响应缺少 clockTime"
        elif clock_time and resp.get("ok") and resp.get("http_status") == 200:
            try:
                datetime.fromisoformat(clock_time)
                result["clock_time_valid"] = True
                # design §8：存储网关时钟时间参考
                session.gateway_clock_times[device_id] = clock_time
            except ValueError:
                result["ok"] = False
                result["error"] = True
                result["clock_time_valid"] = False
                result["detail"] = f"clockTime 格式非法: {clock_time}"
        # allow_poll 预留（首版不轮询）
        result["allow_poll"] = allow_poll
        valid = bool(result.get("clock_time_valid")) and bool(resp.get("ok"))
        result.update(
            ok=valid, error=not valid,
            stage_state="SUCCEEDED" if valid else "UNVERIFIED",
            gateway_reachable=valid,
        )
        return result

    @mcp.tool()
    @_tracked_action("monitor_debug", "node_key", require_template=False, dedup=False)
    def edge_call_monitor_debug(
        task_id: str,
        node_key: str = "",
        plan_id: str = "",
        tag: str = "",
        confirm: bool = False,
        device_id: str = "",
        road_no: str = "",
    ) -> dict:
        """监测点运维调试召测（实测 itemId=31800006，dataItem 包裹结构）。

        对已建档（deviceId 可解析）的监测点进行运维调试召测，不区分
        监测点类型。准入仅 confirm 确认；父级一致性/分路号来源以
        warnings 呈现不阻断。分路号优先实时读档案 agentNum 现值。
        rtnCode=0表示召测成功。

        Args:
            task_id: 会话 ID。
            node_key: 监测点节点键（建档模板会话必填）。
            plan_id: 计划 ID（仅记录，不再校验）。
            tag: 标签过滤，默认空表示全部标签。
            confirm: 用户是否已确认执行。
            device_id: 监测点设备 ID（独立登录会话必填）。
            road_no: 分路号（独立登录会话必填）。
        """
        session = edge_sessions.get(
            task_id, owner_id=_current_owner_id(),
        )
        if session is None:
            return _err(f"会话不存在或已过期: {task_id}")
        # 确认守卫
        if not confirm:
            return _err("监测点召测需用户确认（confirm=true）")
        # 区分会话类型：独立登录会话 vs 建档模板会话
        if session.template is None:
            # 独立登录会话（edge_get_token 创建）：简化约束
            if not device_id:
                return _err("独立会话需提供 device_id 参数")
            if not road_no:
                return _err("独立会话需提供 road_no 参数")
            try:
                road_no_int = int(road_no)
            except ValueError:
                return _err(f"分路号非整数: {road_no}")
            # 直接跳转到构造请求部分
            payload = {
                "deviceId": device_id,
                "dataItem": {
                    "itemId": MONITOR_DEBUG_ITEM_ID,
                    "annexInfo": {
                        "roadNo": road_no_int,
                        "tag": str(tag or "").strip(),
                    },
                },
            }
            summary = {"deviceId": device_id, "roadNo": road_no_int}
            # 执行调用
            try:
                client = _client_for(session)
                resp = _call_action(task_id, session, PATH_CALL_DEVICE_PARAM, payload, link=True)
            except EdgeApiError as exc:
                return _err(
                    f"监测点召测调用失败: {exc}",
                    request_summary=summary,
                )
            # 结果返回
            result = _action_result("call_monitor_debug", summary, resp)
            result["state"] = resp.get("state")
            if resp.get("ok"):
                result["monitor_valid"] = True
                result["stage_state"] = "SUCCEEDED"
            else:
                result["monitor_valid"] = False
                result["stage_state"] = "UNVERIFIED"
            return result
        # 建档模板会话：准入仅 confirm，保留节点存在性与建档状态校验
        if not node_key:
            return _err("node_key 不能为空")
        # 解析节点
        node, profile, detail, err = _resolve_node(session, node_key)
        if err:
            return err
        if profile.is_gateway:
            return _err(
                f"节点 {node_key} 是网关，监测点召测仅适用于监测点"
            )
        # 获取实际 deviceId
        device_id = (
            session.key_to_device_id.get(node_key, "")
            or node.device_id
        )
        if not device_id:
            return _err(
                f"节点 {node_key} 尚未建档，无 deviceId"
            )
        poll_warnings: list[str] = []
        # 实时读档案记录：分路号优先取后端现值 agentNum，读失败回退模板值
        record: dict = {}
        try:
            record = _read_device_record(session, device_id)
        except Exception as exc:  # noqa: BLE001 - 档案读取失败回退模板分路号
            poll_warnings.append(
                f"设备档案读取失败（{exc}），分路号回退模板值"
            )
        parent_id = session.key_to_device_id.get(node.parent_key, "")
        actual_parent = str(record.get("parentId", ""))
        if parent_id and actual_parent and actual_parent != parent_id:
            poll_warnings.append(
                f"监测点实际父级({actual_parent})与模板({parent_id})"
                "不一致，请复核拓扑"
            )
        # 解析 roadNo（整数）：agentNum 现值优先，缺失回退 node.road_no 并告警
        road_no_str = str(record.get("agentNum") or "").strip()
        if not road_no_str and record:
            road_no_str = str(
                node.road_no if node.road_no is not None else ""
            ).strip()
            if road_no_str:
                poll_warnings.append(
                    f"档案 agentNum 为空，分路号回退模板值({road_no_str})"
                )
        elif not road_no_str:
            road_no_str = str(
                node.road_no if node.road_no is not None else ""
            ).strip()
        if not road_no_str:
            return _err(
                f"节点 {node_key} 分路号未填写，无法构造召测请求"
            )
        try:
            road_no = int(road_no_str)
        except ValueError:
            return _err(
                f"分路号非整数: {road_no_str}"
            )
        # 构造请求（实测契约：deviceId + dataItem:{itemId, annexInfo}）
        payload = {
            "deviceId": device_id,
            "dataItem": {
                "itemId": MONITOR_DEBUG_ITEM_ID,
                "annexInfo": {
                    "roadNo": road_no,
                    "tag": str(tag or "").strip(),
                },
            },
        }
        summary = {
            "node_key": node_key,
            "deviceId": device_id,
            "itemId": MONITOR_DEBUG_ITEM_ID,
            "roadNo": road_no,
            "tag": payload["dataItem"]["annexInfo"]["tag"],
        }
        try:
            client = _client_for(session)
            # 添加页面兼容的请求头（对齐页面抓包结果）
            original_sign_headers = client._sign_headers
            def _sign_headers_with_forward():
                headers = original_sign_headers()
                # 添加 ForwardType、ForwardPort（与页面一致）
                headers.setdefault("ForwardType", "SmartUnit")
                headers.setdefault("ForwardPort", "7500")
                # 添加 ForwardUrl、webSite（直连模式下使用 http://undefined，与页面一致）
                if not client.proxy_mode:
                    headers.setdefault("ForwardUrl", "http://undefined")
                    headers.setdefault("webSite", "http://undefined")
                # 添加 PhoneNum、Code、SepToken（与页面一致）
                headers.setdefault("PhoneNum", "undefined")
                headers.setdefault("Code", "undefined")
                headers.setdefault("SepToken", "null")
                return headers
            client._sign_headers = _sign_headers_with_forward
            try:
                resp = _call_action(task_id, session, PATH_CALL_DEVICE_PARAM, payload, link=True)
            finally:
                client._sign_headers = original_sign_headers
        except EdgeApiError as exc:
            return _err(
                f"监测点召测调用失败: {exc}",
                request_summary=summary,
            )
        # 结果校验
        result = _action_result(
            "call_monitor_debug", summary, resp,
        )
        if poll_warnings:
            result["warnings"] = list(poll_warnings)
        result["state"] = resp.get("state")
        if not resp.get("ok"):
            result["monitor_valid"] = False
            return result
        # 深度校验：itemId / finshFlag / roadNo / dataTime / data
        rtn_data = resp.get("data")
        if not isinstance(rtn_data, dict):
            result["ok"] = False
            result["error"] = True
            result["monitor_valid"] = False
            result["detail"] = "响应缺少 rtnData"
            return result
        # 提取 dataItem 对象
        data_item = rtn_data.get("dataItem")
        if not isinstance(data_item, dict):
            result["ok"] = False
            result["error"] = True
            result["monitor_valid"] = False
            result["detail"] = "响应缺少 dataItem"
            return result
        # 从 dataItem 获取 itemId 和 finshFlag
        resp_item_id = str(data_item.get("itemId", "")).strip()
        finsh_flag = data_item.get("finshFlag")
        # 提取 itemBody 数组
        item_body = data_item.get("itemBody")
        if not isinstance(item_body, list) or len(item_body) == 0:
            result["ok"] = False
            result["error"] = True
            result["monitor_valid"] = False
            result["detail"] = "响应缺少 itemBody 数据"
            return result
        # 从 itemBody[0] 获取 roadNo、dataTime、实际数据
        first_item = item_body[0]
        resp_road_no = first_item.get("roadNo")
        data_time = str(first_item.get("dataTime", "")).strip()
        target_data = first_item.get("item")
        # itemId 校验
        if resp_item_id != MONITOR_DEBUG_ITEM_ID:
            result["ok"] = False
            result["error"] = True
            result["monitor_valid"] = False
            result["detail"] = (
                f"itemId 不匹配: 期望 "
                f"{MONITOR_DEBUG_ITEM_ID}，实际 {resp_item_id}"
            )
            return result
        # finshFlag 校验
        if finsh_flag != 0:
            result["ok"] = False
            result["error"] = True
            result["monitor_valid"] = False
            result["detail"] = (
                f"finshFlag 非 0: {finsh_flag}"
            )
            return result
        # roadNo 匹配
        if str(resp_road_no) != str(road_no):
            result["ok"] = False
            result["error"] = True
            result["monitor_valid"] = False
            result["detail"] = (
                f"roadNo 不匹配: 期望 {road_no}，"
                f"实际 {resp_road_no}"
            )
            return result
        # dataTime 有效性
        if not data_time:
            result["ok"] = False
            result["error"] = True
            result["monitor_valid"] = False
            result["detail"] = "响应缺少 dataTime"
            return result
        try:
            datetime.fromisoformat(data_time)
        except ValueError:
            result["ok"] = False
            result["error"] = True
            result["monitor_valid"] = False
            result["detail"] = (
                f"dataTime 格式非法: {data_time}"
            )
            return result
        # 目标数据存在性（0/False 不是空）
        if target_data is None or target_data == "" or target_data == [] or target_data == {}:
            result["ok"] = False
            result["error"] = True
            result["monitor_valid"] = False
            result["detail"] = "响应缺少目标数据"
            return result
        # 时间域校验已移除：召测成功只取决于自身响应结构（itemId/
        # finshFlag/roadNo/dataTime 格式/目标数据），与是否召测过
        # 网关时钟无关。网关时钟不再是召测的验收前置。
        # 全部通过
        result["monitor_valid"] = True
        result["data_time"] = data_time
        result["finsh_flag"] = finsh_flag
        result["target_data"] = target_data
        verified = resp.get("http_status") == 200
        result.update(
            ok=verified, error=not verified, monitor_valid=verified,
            stage_state="SUCCEEDED" if verified else "UNVERIFIED",
        )
        return result

    @mcp.tool()
    def execute_archive_task(
        task_id: str = "",
        gateway_node_key: str = "",
        meter_node_keys: str = "",
        stages: str = "all",
        auto_confirm: bool = False,
        batch_size: int = 0,
        budget: float = 0.0,
        cursor: str = "",
    ) -> dict:
        """一键执行建档任务（完整流程或独立执行）。

        两种模式（按会话是否绑定模板分派）：
        1. 完整流程（模板会话 task_id）：plan→建档→挂载→参数保存→时钟→下发→召测。
        2. 独立执行（给 gateway_node_key）：对已存在网关执行指定阶段，可携带
           edge_get_token 直连会话的 task_id 定位后端。

        大批量可用 batch_size / budget 分批推进：到达节点数或时间预算边界即
        返回，附续跑游标 cursor 与 remaining；携同一 cursor 再调可从中断处
        继续；缺省（batch_size=0、budget=0）一次跑完，行为向后兼容。缺省/失效
        游标下按阶段状态跳过已 SUCCEEDED 目标、只推进未完成部分。

        Args:
            task_id: 完整流程：模板上传后的 task_id。
            gateway_node_key: 独立执行：已存在网关的 node_key（支持 name/identifier/id）。
            meter_node_keys: 独立执行：指定监测点（逗号分隔，空=全部）。
            stages: all/clock/deploy/monitor 逗号组合，默认 all；子集跳过建档仅重试联通。
            auto_confirm: 是否自动确认下发，默认 false。
            batch_size: 单次调用最多推进的执行型工作单元数（0=不限，一次跑完）。
            budget: 单次调用最多占用秒数（0=不限）；到点即返回并给续跑游标。
            cursor: 上一次返回的续跑游标；缺省从头开始（阶段状态兜底跳过已完成）。

        Returns:
            执行结果摘要，含 summary（成功/失败/跳过）、cursor、remaining、
            partial、stages（阶段状态汇总）与 report_id。
        """
        # 按解析到的会话是否绑定模板分派：模板会话走全流程，
        # 否则给定 gateway_node_key 走独立模式（可携带直连会话 task_id）
        session = (
            edge_sessions.get(task_id, owner_id=_current_owner_id())
            if task_id else None
        )
        if session is not None and session.template is not None:
            return _execute_full_workflow(
                task_id, stages, auto_confirm,
                batch_size=batch_size, budget_seconds=budget, cursor=cursor,
            )
        elif gateway_node_key:
            return _execute_standalone_workflow(
                task_id, gateway_node_key, meter_node_keys, stages, auto_confirm,
            )
        elif task_id:
            return _err(
                "独立模式需提供 gateway_node_key（该会话未绑定建档模板）"
            )
        else:
            return _err("task_id 或 gateway_node_key 必须提供一个")

    def _execute_full_workflow(
        task_id: str, stages: str, auto_confirm: bool,
        batch_size: int = 0, budget_seconds: float = 0.0, cursor: str = "",
    ) -> dict:
        """一键编排：plan→建档→挂载→参数保存→时钟→下发→召测，支持分批续跑。

        以 session.last_plan 为权威计划构建有序工作单元；batch_size/budget
        限定单次推进量并返回续跑游标；是否跳过以阶段状态为准，游标仅作提示。
        """
        import time
        st = _parse_stages(stages)
        session = edge_sessions.get(task_id, owner_id=_current_owner_id())
        if session is None:
            return _err(f"会话不存在或已过期: {task_id}")

        # 单次规划，全流程复用同一 plan_id（规避 plan_id 轮换）
        plan_result = plan_device_archive(task_id=task_id)
        if not plan_result.get("ok"):
            return plan_result
        plan_id = plan_result["plan_id"]
        if not session.last_plan.get("executable", False):
            return _err("计划存在结构性冲突或模板错误，禁止执行")

        results: list[dict] = []
        details: list[dict] = []
        plan = session.last_plan
        node_map = session.template.node_map() if session.template else {}
        nodes = session.template.nodes if session.template else []

        def _record(r: dict, nk: str, action: str) -> None:
            results.append(r)
            details.append({
                "node_key": nk, "action": action,
                "state": r.get("stage_state", "UNVERIFIED"),
                "ok": r.get("ok", False),
            })

        def _archive_unit(item: dict) -> bool:
            """单节点建档：create/update → mount → parameter_save（已成则跳过）。"""
            nk = item.get("node_key", "")
            action = item.get("action", "")
            executed = False
            if not _stage_succeeded(session, nk, "archive_read"):
                _record(
                    edge_upsert_device(
                        task_id=task_id, node_key=nk,
                        plan_id=plan_id, confirm=True,
                    ),
                    nk, action,
                )
                executed = True
            node = node_map.get(nk)
            parent_key = getattr(node, "parent_key", "") if node else ""
            if (action == "create" and parent_key
                    and not _stage_succeeded(session, nk, "mount")):
                parent_device_id = (
                    session.key_to_device_id.get(parent_key, "")
                    or item.get("parent_device_id", "")
                )
                if parent_device_id:
                    _record(
                        edge_mount_device(
                            task_id=task_id, node_key=nk,
                            parent_device_id=parent_device_id,
                            plan_id=plan_id, confirm=True,
                        ),
                        nk, "mount",
                    )
                    executed = True
            if not _stage_succeeded(session, nk, "parameter_save"):
                _record(
                    edge_save_device_parameters(
                        task_id=task_id, node_key=nk,
                        plan_id=plan_id, confirm=True,
                    ),
                    nk, "parameter_save",
                )
                executed = True
            return executed

        def _clock_unit(node) -> bool:
            """网关时钟（只读）；已 SUCCEEDED 跳过，未建档无 device_id 则略过。"""
            nk = node.node_key
            if _stage_succeeded(session, nk, "gateway_clock"):
                details.append({
                    "node_key": nk, "action": "clock", "state": "SKIPPED",
                    "skipped_reason": "本任务已完成",
                })
                return False
            device_id = session.key_to_device_id.get(nk, "")
            if not device_id:
                return False
            _record(
                edge_call_clock(
                    task_id=task_id, device_id=device_id,
                    plan_id=plan_id, confirm=True,
                ),
                nk, "clock",
            )
            return True

        def _deploy_unit(batch: dict) -> bool:
            """批量下发（需确认）；按网关粒度，已 SUCCEEDED 跳过。"""
            gk = batch.get("gateway_key", "")
            if _stage_succeeded(session, gk, "param_deploy"):
                details.append({
                    "node_key": gk, "action": "deploy", "state": "SKIPPED",
                    "skipped_reason": "本任务已完成",
                })
                return False
            _record(
                edge_set_device_param(
                    task_id=task_id, gateway_node_key=gk,
                    meter_node_keys=",".join(batch.get("meter_keys", [])),
                    plan_id=plan_id, confirm=True,
                ),
                gk, "deploy",
            )
            return True

        def _monitor_unit(node) -> bool:
            """监测点运维召测（只读）；已 SUCCEEDED 跳过。"""
            nk = node.node_key
            if _stage_succeeded(session, nk, "monitor_debug"):
                details.append({
                    "node_key": nk, "action": "monitor", "state": "SKIPPED",
                    "skipped_reason": "本任务已完成",
                })
                return False
            _record(
                edge_call_monitor_debug(
                    task_id=task_id, node_key=nk,
                    plan_id=plan_id, confirm=True,
                ),
                nk, "monitor",
            )
            return True

        # 有序工作单元：archive(拓扑序节点) → clock(网关) → deploy(批次) → monitor(监测点)
        units: list = []
        if st["archive"]:
            for item in plan.get("items", []):
                if item.get("action", "") in ("create", "update"):
                    units.append(("archive", lambda it=item: _archive_unit(it)))
        if st["clock"]:
            for node in nodes:
                _, profile, _, _ = _resolve_node(session, node.node_key)
                if profile is not None and profile.is_gateway:
                    units.append(("clock", lambda nd=node: _clock_unit(nd)))
        if st["deploy"]:
            for batch in plan.get("deploy_batches", []):
                if batch.get("gateway_key", ""):
                    units.append(("deploy", lambda b=batch: _deploy_unit(b)))
        if st["monitor"]:
            for node in nodes:
                _, profile, _, _ = _resolve_node(session, node.node_key)
                if profile is not None and not profile.is_gateway:
                    units.append(("monitor", lambda nd=node: _monitor_unit(nd)))

        total_units = len(units)
        # 游标仅作进度提示：续跑以阶段状态为权威，始终从头扫描；
        # 已完成单元由 _stage_succeeded 或计划改判 skip 而快速跳过（不计入 batch_size），
        # 因此单元列表随进度变化也不会漏做或重复已完成节点（design D2）。
        processed = 0
        started = time.monotonic()
        idx = 0
        next_cursor = total_units
        stopped = False
        pending = False
        while idx < total_units:
            kind, runner = units[idx]
            if kind == "deploy" and not auto_confirm:
                pending = True
                next_cursor = idx
                stopped = True
                break
            executed = bool(runner())
            idx += 1
            if executed:
                processed += 1
                over = (
                    (batch_size and processed >= batch_size)
                    or (budget_seconds
                        and (time.monotonic() - started) >= budget_seconds)
                )
                if over and idx < total_units:
                    next_cursor = idx
                    stopped = True
                    break
        if not stopped:
            next_cursor = total_units
        remaining = total_units - next_cursor
        cursor_out = "" if next_cursor >= total_units else str(next_cursor)

        if pending:
            return {
                "ok": False, "pending_confirm": True, "stage": "param_deploy",
                "message": "下发需确认，请携此游标设 auto_confirm=true 继续",
                "plan_id": plan_id, "stages_requested": stages,
                "mode": "partial", "cursor": cursor_out,
                "remaining": remaining, "details": details,
            }
        return _aggregate_workflow_results(
            task_id, plan_id, results, details, session,
            stages_requested=stages, cursor=cursor_out, remaining=remaining,
            partial=bool(cursor_out),
        )

    def _execute_standalone_workflow(
        task_id: str,
        gateway_node_key: str,
        meter_node_keys: str,
        stages: str,
        auto_confirm: bool,
    ) -> dict:
        """独立执行：不依赖模板，直接查询设备树执行操作。"""
        st = _parse_stages(stages)
        # 1. 定位会话：显式 task_id 优先，否则仅当唯一会话时兼容沿用
        if task_id:
            session = edge_sessions.get(task_id, owner_id=_current_owner_id())
            if session is None:
                return _err(f"会话不存在或已过期: {task_id}")
        else:
            active = list(edge_sessions._sessions.items())
            if len(active) != 1:
                return _err("独立模式需指定 task_id（当前存在多个会话或无会话）")
            task_id, session = active[0]
        # 2. 查询设备树获取网关和监测点 device_id
        device_tree_result = edge_get_device_tree(task_id=task_id)
        if not device_tree_result.get("ok"):
            return _err(
                f"设备树查询失败: {device_tree_result.get('message')}",
            )
        device_tree = device_tree_result.get("data", [])
        if not isinstance(device_tree, list):
            return _err("设备树格式异常")
        if not device_tree:
            return _err("设备树为空")
        # 解析设备树，找到目标网关
        gateway_info = _find_device_in_tree(device_tree, gateway_node_key)
        if not gateway_info:
            return _err(f"设备树中未找到网关 {gateway_node_key}")
        gateway_device_id = str(
            gateway_info.get("id") or gateway_info.get("deviceId") or ""
        )
        if not gateway_device_id:
            return _err(f"网关 {gateway_node_key} 无 deviceId")
        # 获取网关下所有监测点（或指定的监测点）
        if meter_node_keys:
            meter_device_ids = [
                k.strip() for k in meter_node_keys.split(",") if k.strip()
            ]
        else:
            # 获取网关下所有子设备（监测点），兼容嵌套与扁平树
            meter_device_ids = _collect_meter_device_ids(
                device_tree, gateway_node_key, gateway_device_id,
            )
        if not meter_device_ids:
            return _err(f"网关 {gateway_node_key} 下无监测点")
        results = []
        details = []
        # 3. 执行时钟同步（直接调用，不依赖模板）
        if st["clock"]:
            clock_result = _standalone_call_clock(
                session, gateway_device_id,
            )
            results.append(clock_result)
            details.append({
                "device_id": gateway_device_id,
                "identifier": gateway_node_key,
                "action": "clock",
                "ok": clock_result.get("ok", False),
                "message": clock_result.get("message", ""),
            })
        # 4. 执行运维召测（直接调用，不依赖模板）— 在 deploy 之前执行
        if st["monitor"]:
            for meter_id in meter_device_ids:
                monitor_result = _standalone_call_monitor(
                    session, meter_id,
                )
                results.append(monitor_result)
                details.append({
                    "device_id": meter_id,
                    "action": "monitor",
                    "ok": monitor_result.get("ok", False),
                    "message": monitor_result.get("message", ""),
                })
        # 5. 执行批量下发（经 edge_set_device_param 免模板路径）
        if st["deploy"]:
            # 检查前置阶段是否成功
            clock_succeeded = any(
                d.get("action") == "clock" and d.get("ok") for d in details
            )
            monitor_succeeded = any(
                d.get("action") == "monitor" and d.get("ok") for d in details
            )
            # 如果是 all 模式，检查前置阶段
            if st["archive"] and details:
                has_clock = any(d.get("action") == "clock" for d in details)
                has_monitor = any(d.get("action") == "monitor" for d in details)
                if has_clock and not clock_succeeded:
                    return {
                        "ok": False,
                        "message": "网关时钟召测失败，无法下发",
                        "details": details,
                    }
                if has_monitor and not monitor_succeeded:
                    return {
                        "ok": False,
                        "message": "监测点运维召测失败，无法下发",
                        "details": details,
                    }
            # 检查是否需要用户确认
            if not auto_confirm:
                return {
                    "ok": False,
                    "pending_confirm": True,
                    "message": "前置阶段成功，是否继续下发？请设置 auto_confirm=true 确认",
                    "gateway_node_key": gateway_node_key,
                    "gateway_device_id": gateway_device_id,
                    "meter_count": len(meter_device_ids),
                    "clock_ok": clock_succeeded,
                    "monitor_ok": monitor_succeeded,
                    "details": details,
                }
            # 经已注册工具下发：_tracked_action 会建立 pending_action，
            # 使免模板下发同样具备派发意图与持久报告
            deploy_result = edge_set_device_param(
                task_id=task_id,
                gateway_node_key=gateway_node_key,
                confirm=True,
                meter_node_keys=",".join(meter_device_ids),
            )
            results.append(deploy_result)
            details.append({
                "device_id": gateway_device_id,
                "identifier": gateway_node_key,
                "action": "deploy",
                "ok": deploy_result.get("ok", False),
                "device_count": len(meter_device_ids),
                "message": deploy_result.get("message", ""),
            })
        # 汇总返回
        succeeded = sum(1 for r in results if r.get("ok"))
        failed = len(results) - succeeded
        return {
            "ok": failed == 0,
            "mode": "standalone",
            "gateway_node_key": gateway_node_key,
            "gateway_device_id": gateway_device_id,
            "meter_count": len(meter_device_ids),
            "summary": {
                "total": len(results),
                "succeeded": succeeded,
                "failed": failed,
            },
            "details": details,
            "stages_executed": stages,
            "report_id": session.report_id,
        }

    def _get_all_meters_for_gateway(
        session: EdgeSession, gateway_node_key: str,
    ) -> list[str]:
        """获取网关下的所有监测点 node_key。"""
        meters = []
        if session.template:
            for node in session.template.nodes:
                if node.parent_key == gateway_node_key:
                    meters.append(node.node_key)
        return meters

    def _aggregate_workflow_results(
        task_id: str,
        plan_id: str,
        results: list[dict],
        details: list[dict],
        session: EdgeSession,
        stages_requested: str = "",
        cursor: str = "",
        remaining: int = 0,
        partial: bool = False,
    ) -> dict:
        """汇总工作流执行结果（区分成功/跳过/失败，含分批游标）。"""
        total = len(details)
        succeeded = sum(1 for d in details if d.get("ok"))
        skipped = sum(1 for d in details if d.get("state") == "SKIPPED")
        failed = total - succeeded - skipped

        # 汇总阶段状态
        stages_summary = {}
        if session.template:
            for node in session.template.nodes:
                orchestrator = _stage_for(session, node.node_key)
                stages_summary[node.node_key] = {
                    name: record.state.value
                    for name, record in orchestrator.records.items()
                }

        return {
            "ok": failed == 0,
            "task_id": task_id,
            "plan_id": plan_id,
            "stages_requested": stages_requested,
            "partial": partial,
            "cursor": cursor,
            "remaining": remaining,
            "summary": {
                "total": total,
                "succeeded": succeeded,
                "skipped": skipped,
                "failed": failed,
            },
            "details": details,
            "stages": stages_summary,
            "report_id": session.report_id,
        }

    def _find_device_in_tree(
        devices: list[dict], target: str,
    ) -> dict | None:
        """按 identifier/name/id 或档案字段 deviceName/deviceId 查找设备。"""
        for device in devices:
            if (
                device.get("identifier") == target
                or device.get("name") == target
                or device.get("deviceName") == target
                or str(device.get("id") or "") == target
                or str(device.get("deviceId") or "") == target
            ):
                return device
            children = device.get("children") or []
            found = _find_device_in_tree(children, target)
            if found:
                return found
        return None

    def _get_all_children(
        devices: list[dict], parent_identifier: str,
    ) -> list[dict]:
        """获取设备树下某节点的所有子孙设备。"""
        parent = _find_device_in_tree(devices, parent_identifier)
        if not parent:
            return []
        result = []
        stack = list(parent.get("children") or [])
        while stack:
            node = stack.pop()
            result.append(node)
            stack.extend(node.get("children") or [])
        return result

    def _collect_meter_device_ids(
        tree: list[dict], gateway_node_key: str, gateway_device_id: str,
    ) -> list[str]:
        """归集网关下监测点的 deviceId，兼容嵌套与扁平设备树。

        嵌套树走 children 递归；若节点无 children 嵌套（扁平列表）
        则回退按 parentId 等于网关 deviceId 归集。结果去重并保序。

        Args:
            tree: 设备树节点列表。
            gateway_node_key: 网关标识（用于排除网关自身）。
            gateway_device_id: 网关 deviceId。

        Returns:
            监测点 deviceId 列表（去重、保序）。
        """
        children = _get_all_children(tree, gateway_node_key)
        if not children:
            children = [
                node for node in tree
                if str(node.get("parentId") or "") == gateway_device_id
            ]
        collected: list[str] = []
        seen: set[str] = set()
        for child in children:
            dev_id = str(child.get("id") or child.get("deviceId") or "")
            if not dev_id or dev_id == gateway_device_id:
                continue
            if (
                child.get("identifier") == gateway_node_key
                or child.get("name") == gateway_node_key
                or child.get("deviceName") == gateway_node_key
            ):
                continue
            if dev_id not in seen:
                seen.add(dev_id)
                collected.append(dev_id)
        return collected

    def _standalone_call_clock(
        session, gateway_device_id: str,
    ) -> dict:
        """独立模式时钟召测：直接调用 API，成功后记录会话可达标记。"""
        try:
            client = _client_for(session)
            resp = client.call_link(
                PATH_CALL_CLOCK,
                {"devId": gateway_device_id},
            )
        except EdgeApiError as exc:
            return _err(f"时钟召测异常: {exc}")
        if not resp.get("ok"):
            return _err(f"时钟召测失败: {resp.get('rtnMsg')}")
        # 解析 clockTime 并写入会话可达标记（与 edge_call_clock 同一事实源）
        clock_time = ""
        rtn_data = resp.get("data")
        if isinstance(rtn_data, dict):
            call_time = rtn_data.get("callTime")
            if isinstance(call_time, dict):
                value = call_time.get("clockTime")
                clock_time = "" if value is None else str(value).strip()
        if clock_time:
            try:
                datetime.fromisoformat(clock_time)
                session.gateway_clock_times[gateway_device_id] = clock_time
            except ValueError:
                pass
        return {"ok": True, "message": "时钟召测成功", "clock_time": clock_time}

    def _standalone_call_monitor(
        session, meter_device_id: str,
    ) -> dict:
        """独立模式运维召测：直接调用 API，不依赖模板。"""
        try:
            client = _client_for(session)
            resp = client.call_link(
                PATH_CALL_MONITOR_DEBUG,
                {
                    "deviceId": meter_device_id,
                    "dataItem": {"itemId": "31800006"},
                },
            )
            if resp.get("ok"):
                return {"ok": True, "message": "运维召测成功"}
            return _err(f"运维召测失败: {resp.get('rtnMsg')}")
        except EdgeApiError as exc:
            return _err(f"运维召测异常: {exc}")

    @mcp.tool()
    @_tracked_action("compensation", "")
    def edge_apply_compensation_plan(
        task_id: str, confirm: bool = False, plan_id: str = "",
    ) -> dict:
        """按补偿清单确认式删除本次新建设备（叶子到父节点）。

        仅删除补偿清单内本次新建的 deviceId，删除后回读设备树验证，
        绝不删除清单外的既有设备。

        Args:
            task_id: 会话 ID。
            confirm: 用户是否明确确认清理。
            plan_id: 当前计划ID，清单变化后必须重新确认。
        """
        session = edge_sessions.get(task_id, owner_id=_current_owner_id())
        if session is None:
            return _err(f"会话不存在或已过期: {task_id}")
        if not confirm or not plan_id or plan_id != session.active_plan_id:
            return _err("补偿清理需要当前plan_id与独立确认，未调用后端")
        if not session.recorder.entries:
            return {"ok": True, "stage_state": "SUCCEEDED", "action": "apply_compensation",
                    "message": "补偿清单为空，本次无新建设备需清理", "deleted": []}
        try:
            client = _client_for(session)
        except EdgeApiError as exc:
            return _err(f"补偿清理登录失败: {exc}")
        scope_ids = {entry.device_id for entry in session.recorder.entries}
        tree = client.call(PATH_GET_DEVICE_TREE, {})
        if not tree.get("ok") or not isinstance(tree.get("data"), list):
            return _err("无法核验补偿清单的实际子树，禁止清理")
        for row in _flatten_devices(tree["data"]):
            device_id = str(row.get("deviceId") or row.get("id") or "")
            if device_id not in scope_ids and str(row.get("parentId", "")) in scope_ids:
                return _err("补偿目标包含清单外子设备，禁止级联清理")
            if device_id in scope_ids:
                descendants = _flatten_devices(row.get("children", []))
                if any(
                    str(child.get("deviceId") or child.get("id") or "") not in scope_ids
                    for child in descendants
                ):
                    return _err("补偿目标包含清单外后代，禁止级联清理")

        def audited_write(path: str, payload: dict) -> dict:
            """在每个清理请求前持久化意图。"""
            return _call_action(task_id, session, path, payload)

        result = apply_compensation(
            client, session.recorder.plan, confirm=confirm, write_call=audited_write,
        )
        result["action"] = "apply_compensation"
        result["stage_state"] = "SUCCEEDED" if result["ok"] else "UNVERIFIED"
        if session.pending_action["request_sent"]:
            for key in session.key_to_device_id:
                for stage in ("archive_read", "parameter_save"):
                    _stage_for(session, key).record_stage(
                        stage, StageState.UNVERIFIED, "补偿清理后需重新计划与回读",
                    )
        return result

    @mcp.tool()
    def get_device_archive_task_report(
        task_id: str,
        report_id: str = "",
    ) -> dict:
        """查询自动建档任务报告（脱敏计划、动作结果、补偿清单）。

        支持进程中断后查询、任务过期后由所属身份查报告。报告不含凭据。

        Args:
            task_id: 会话 ID（用于归属校验）。
            report_id: 报告 ID；留空时按 task_id 查找最新报告。
        """
        owner_id = _current_owner_id()
        if not owner_id:
            return _err("无法确定报告归属身份")
        store = TaskReportStore()
        try:
            report = store.load(report_id) if report_id else store.find_by_task(task_id, owner_id)
        except (TaskReportError, OSError) as exc:
            return _err(str(exc))
        if report is None or report.owner_id != owner_id or report.task_id != task_id:
            return _err("报告不存在、已过期或不属于当前身份与任务")
        return {"ok": True, "report": sanitize_report(report.to_dict())}

    # 将已注册的工具函数暴露到模块命名空间，便于测试与直接引用
    globals().update(
        {
            "convert_comm_address_tool": convert_comm_address_tool,
            "read_device_archive_template": read_device_archive_template,
            "migrate_device_archive_template": migrate_device_archive_template,
            "plan_device_archive": plan_device_archive,
            "edge_upsert_device": edge_upsert_device,
            "edge_mount_device": edge_mount_device,
            "edge_save_device_parameters": edge_save_device_parameters,
            "edge_get_device_tree": edge_get_device_tree,
            "edge_get_device_list": edge_get_device_list,
            "edge_get_device_parameters": edge_get_device_parameters,
            "edge_set_device_param": edge_set_device_param,
            "edge_call_device_data": edge_call_device_data,
            "edge_call_clock": edge_call_clock,
            "edge_call_monitor_debug": edge_call_monitor_debug,
            "edge_check_monitor_online": edge_check_monitor_online,
            "edge_apply_compensation_plan": edge_apply_compensation_plan,
            "get_device_archive_task_report": get_device_archive_task_report,
            "edge_get_token": edge_get_token,
            "edge_delete_device": edge_delete_device,
        }
    )


#: 已注册的自动建档原子工具名（供 register 与文档一致性校验）
EDGE_TOOL_NAMES = (
    "convert_comm_address_tool",
    "generate_device_archive_template",
    "get_device_archive_template_download",
    "migrate_device_archive_template",
    "read_device_archive_template",
    "upload_device_archive_template",
    "plan_device_archive",
    "edge_upsert_device",
    "edge_mount_device",
    "edge_save_device_parameters",
    "edge_get_device_tree",
    "edge_get_device_list",
    "edge_get_device_parameters",
    "edge_set_device_param",
    "edge_call_device_data",
    "edge_call_clock",
    "edge_call_monitor_debug",
    "edge_check_monitor_online",
    "execute_archive_task",
    "edge_apply_compensation_plan",
    "get_device_archive_task_report",
    "edge_get_token",
    "edge_delete_device",
)


def _flatten_devices(tree_data) -> list[dict]:
    """递归展平设备树为设备字典列表。

    Args:
        tree_data: getDeviceTree 的 rtnData（树节点列表）。

    Returns:
        展平后的设备字典列表。
    """
    out: list[dict] = []

    def walk(nodes) -> None:
        for node in nodes or []:
            if isinstance(node, dict):
                out.append(node)
                walk(node.get("children") or [])

    walk(tree_data)
    return out


def _ext_infos_to_list(ext_infos: dict, include_empty: bool) -> list[dict]:
    """将 extInfos 字典转为 modifyDevice 的 [{propertyCode, propertyValue}]。

    Args:
        ext_infos: propertyCode -> propertyValue 字典。
        include_empty: True 输出全部键（含空值，用于新建保证 UI 渲染）；
            False 仅输出非空值（用于更新，避免覆盖手工配置）。

    Returns:
        extInfos 列表。
    """
    out: list[dict] = []
    for code, value in (ext_infos or {}).items():
        text = str(value if value is not None else "")
        if not include_empty and text == "":
            continue
        out.append({"propertyCode": code, "propertyValue": text})
    return out


def _resolve_new_device_id(
    client: EdgeDeviceClient, node: TopologyNode
) -> tuple[str, list[str]]:
    """新建后回查设备树，按条码解析后端 deviceId（唯一性校验）。

    design §7：ID 只从已验证响应字段或唯一业务身份回查取得。
    多个匹配即歧义，拒绝静默选择。

    Args:
        client: 已登录边缘客户端。
        node: 刚建档的拓扑节点。

    Returns:
        二元组 ``(device_id, issues)``：
          - device_id: 解析到的 deviceId；未找到或歧义返回空串。
          - issues: 问题列表（空表示正常）。
    """
    barcode = str(node.identifier or "").strip()
    if not barcode:
        return "", ["条码为空，无法回查 deviceId"]
    try:
        tree = client.call(PATH_GET_DEVICE_TREE, {})
    except EdgeApiError as exc:
        return "", [f"回查设备树失败: {exc}"]
    data = tree.get("data")
    if not tree.get("ok") or not isinstance(data, list):
        return "", ["设备树响应失败或缺少有效 data 列表"]
    # 按条码收集全部匹配
    matches: list[str] = []
    for dev in _flatten_devices(data):
        ident = str(
            dev.get("identifier") or dev.get("deviceAddress") or ""
        ).strip()
        if ident == barcode:
            dev_id = str(dev.get("deviceId") or dev.get("id") or "")
            if dev_id:
                matches.append(dev_id)
    if len(matches) == 0:
        return "", [f"按条码 {barcode} 未在设备树中找到匹配"]
    if len(matches) > 1:
        return "", [
            f"按条码 {barcode} 找到 {len(matches)} 个匹配"
            f"（{', '.join(matches)}），回查歧义，拒绝静默选择"
        ]
    return matches[0], []


def _fix_agent_measured_num(
    client: EdgeDeviceClient, device_id: str, payload: dict
) -> bool | None:
    """建档后二次 modifyDevice 修正分路号/测量点号。

    新建时 agentNum/measuredPointNum 被后端默认成 1；带 deviceId 重发
    完整顶层字段可正确写入（实测）。payload 无这两个字段时跳过（如网关）。

    Args:
        client: 已登录边缘客户端。
        device_id: 新建设备的 deviceId。
        payload: 首次建档的完整 payload（含 agentNum/measuredPointNum）。

    Returns:
        True 修正成功；False 修正失败；None 无需修正（无相关字段）。
    """
    if "agentNum" not in payload and "measuredPointNum" not in payload:
        return None
    update = dict(payload)
    update["deviceId"] = device_id
    try:
        resp = client.call(PATH_MODIFY_DEVICE, update)
    except EdgeApiError:
        return False
    return bool(resp.get("ok"))


def _reapply_agent_num_after_mount(
    session: EdgeSession, node: TopologyNode, device_id: str, *, task_id: str = "",
) -> bool | None:
    """挂载后重新写入分路号/测量点号（updateDeviceParent 会重置为 1）。

    仅对电表（非网关）节点生效：重新解析 profile 得到完整顶层字段 +
    extInfos，带 deviceId 重发以恢复 agentNum/measuredPointNum。

    Args:
        session: 会话状态。
        node: 已挂载的拓扑节点。
        device_id: 该节点的后端 deviceId。

    Returns:
        True 恢复成功；False 失败；None 无需恢复（网关/无字段/解析错误）。
    """
    profile, lookup_err = default_registry.resolve(node.device_type, "")
    if profile is None or lookup_err or profile.is_gateway:
        return None
    detail = session.template.meter_details.get(node.node_key, {})
    resolved = profile.resolve(node, session.template.task_config, detail)
    if resolved.errors:
        return None
    payload = dict(resolved.base_payload)
    ext_list = _ext_infos_to_list(resolved.ext_infos, include_empty=True)
    if ext_list:
        payload["extInfos"] = ext_list
    try:
        client = _client_for(session)
    except EdgeApiError:
        return False
    numbers = {
        key: value for key, value in payload.items()
        if key in ("agentNum", "measuredPointNum") and value is not None and value != ""
    }
    if not numbers:
        return None
    if task_id:
        resp = _call_action(
            task_id, session, PATH_MODIFY_DEVICE, dict(numbers, deviceId=device_id),
        )
        return bool(resp.get("ok"))
    return _fix_agent_measured_num(client, device_id, numbers)


def _readback_verify_device(
    session: EdgeSession, node: TopologyNode, device_id: str
) -> tuple[bool, list[str]]:
    """回读设备档案并逐字段比较。

    design §7：新建→挂载→恢复编号后，逐字段回读比较，
    修正失败或差异使该阶段失败，阻止后续下发。

    Args:
        session: 会话状态。
        node: 拓扑节点。
        device_id: 后端 deviceId。

    Returns:
        二元组 ``(ok, mismatches)``：
          - ok: 全部匹配返回 True。
          - mismatches: 不一致字段列表（空表示全部匹配）。
    """
    profile, lookup_err = default_registry.resolve(node.device_type, "")
    if profile is None or lookup_err:
        return False, [f"profile 解析失败: {lookup_err}"]
    detail = (
        session.template.meter_details.get(node.node_key, {})
        if not profile.is_gateway
        else session.template.gateway_details.get(node.node_key, {})
    )
    resolved = profile.resolve(node, session.template.task_config, detail)
    if resolved.errors:
        return False, [f"profile 解析错误: {'；'.join(resolved.errors)}"]
    try:
        backend_data = _read_device_record(session, device_id)
    except EdgeApiError as exc:
        return False, [f"回读失败: {exc}"]
    mismatches = _compare_archive_fields(
        resolved.base_payload, resolved.ext_infos, backend_data,
    )
    item = _plan_item(session, node.node_key)
    expected_parent = item.get("parent_device_id", "")
    if item.get("action") == "create" and node.parent_key:
        expected_parent = session.key_to_device_id.get(node.parent_key, "")
        # 区分"模板根节点"与"父ID尚未解析"
        if not expected_parent:
            # 节点有父键但父ID未解析，不能视为根节点
            mismatches.append("parentId: 父设备ID尚未解析，禁止验证")
            return False, mismatches
    if item:
        backend_pid = str(backend_data.get("parentId", ""))
        # 根节点网关在边缘后端 pid 为 -1，与 plan 中的空字符串等价
        if not (backend_pid == "-1" and not str(expected_parent)):
            if backend_pid != str(expected_parent):
                mismatches.append("parentId: 实际父级与已确认计划不一致")
    return not mismatches, mismatches


def _save_meter_parameters(
    session: EdgeSession,
    node,
    device_id: str,
    resolved,
    detail: dict,
    task_id: str,
) -> list[str]:
    """保存监测点基本参数到设备本地运行时并回读验证。

    调用 modifyDevice/v1（参数设置版），写入波特率、费率数、
    扩展属性等运行时字段。保存后回读设备档案验证关键字段。

    Args:
        session: 会话状态。
        node: 拓扑节点。
        device_id: 监测点设备 ID。
        resolved: profile 解析结果。
        detail: 电表明细行字典。

    Returns:
        不一致字段列表；空列表表示保存成功且回读通过。
    """
    # baudRate 不写入档案顶层（仅参与 feeNum 位域计算），此处不做码值转换

    parent_id = session.key_to_device_id.get(node.parent_key, "")
    if not parent_id:
        return ["无法确定父设备ID，禁止参数保存"]

    # 顶层参数字段（排除档案专属字段，保留空值以匹配 UI 保存行为）
    # baudRate 不写入档案顶层（仅参与 feeNum 位域计算），从 base_payload 排除
    _ARCHIVE_ONLY_KEYS = {"deviceName", "deviceTypeId", "commAddrRepetition"}
    _BAUD_RATE_EXCLUDED_KEYS = {"baudRate"}  # 不写入档案顶层
    payload: dict = {"deviceId": device_id, "parentId": parent_id}
    for key, value in resolved.base_payload.items():
        if key in _ARCHIVE_ONLY_KEYS or key in _BAUD_RATE_EXCLUDED_KEYS:
            continue
        if value is None:
            continue
        payload[key] = value

    # extInfos（含 feeNum 位域，合并现有扩展属性以避免覆盖手工配置）
    ext_dict: dict[str, str] = {}
    try:
        current = _read_device_record(session, device_id)
        for row in current.get("extInfos", []) or []:
            if isinstance(row, dict) and "propertyCode" in row:
                ext_dict[row["propertyCode"]] = str(
                    row.get("propertyValue", "")
                )
    except EdgeApiError:
        pass
    ext_dict.update(resolved.ext_infos)
    fee_num = (
        resolved.deploy_item_body.get("feeNum")
        if resolved.deploy_item_body else None
    )
    if fee_num is not None:
        ext_dict["feeNum"] = str(fee_num)
    ext_list = _ext_infos_to_list(ext_dict, include_empty=True)
    if ext_list:
        payload["extInfos"] = ext_list

    resp = _call_action(
        task_id, session, PATH_MODIFY_DEVICE, payload,
    )
    if not resp.get("ok"):
        raise EdgeApiError(
            f"监测点参数保存失败: rtnCode={resp.get('rtnCode')}, "
            f"rtnMsg={resp.get('rtnMsg')}"
        )

    # 回读验证（仅验证 feeNum，baudRate 不写入档案顶层故不验证）
    mismatches: list[str] = []
    try:
        actual = _read_device_record(session, device_id)
        if fee_num is not None:
            actual_ext = {
                row["propertyCode"]: str(row.get("propertyValue", ""))
                for row in actual.get("extInfos", [])
                if isinstance(row, dict) and "propertyCode" in row
            }
            actual_fee = actual_ext.get("feeNum", "")
            if actual_fee != str(fee_num):
                mismatches.append(
                    f"extInfos.feeNum: 期望={str(fee_num)!r}, "
                    f"实际={actual_fee!r}"
                )
    except EdgeApiError as exc:
        mismatches.append(f"回读验证失败: {exc}")
    return mismatches


def _save_gateway_parameters_auto(
    session: EdgeSession,
    node,
    device_id: str,
    resolved,
    task_id: str,
) -> dict:
    """网关 CREATE 后立即保存通讯地址参数（20100024）。

    从 profile 解析结果中提取 deviceAddress 和 identifier，
    写入参数项 20100024 并回读验证。

    Args:
        session: 会话状态。
        node: 拓扑节点。
        device_id: 网关设备 ID。
        resolved: profile 解析结果。
        task_id: 任务 ID。

    Returns:
        保存结果字典，含 ok、mismatches 等。
    """
    try:
        current = _read_device_record(session, device_id)
        body = _read_gateway_address_body(session, device_id)
    except EdgeApiError as exc:
        return {"ok": False, "mismatches": [f"读取现有参数失败: {exc}"]}
    body = dict(body)
    body.update(
        commAddr=resolved.base_payload["deviceAddress"],
        identifier=resolved.base_payload["identifier"],
    )
    params = {
        "deviceId": device_id,
        "parentId": current.get("parentId"),
        "params": [{
            "deviceId": device_id,
            "itemId": GATEWAY_ADDRESS_ITEM_ID,
            "itemBody": body,
        }],
    }
    if params["parentId"] is None:
        return {"ok": False, "mismatches": ["无法回读网关实际父级"]}
    try:
        resp = _client_for(session).call(
            PATH_MODIFY_DEVICE_PARAM, params,
        )
    except EdgeApiError as exc:
        return {"ok": False, "mismatches": [f"保存调用失败: {exc}"]}
    if not resp.get("ok"):
        return {
            "ok": False,
            "mismatches": [
                f"rtnCode={resp.get('rtnCode')}, "
                f"rtnMsg={resp.get('rtnMsg')}"
            ],
        }
    mismatches = _verify_gateway_address(session, device_id, body)
    return {"ok": not mismatches, "mismatches": mismatches}


def _save_meter_parameters_auto(
    session: EdgeSession,
    node,
    device_id: str,
    resolved,
    detail: dict,
    task_id: str,
) -> dict:
    """监测点 CREATE+MOUNT 后立即保存基本参数。

    委托给 _save_meter_parameters 执行实际的保存与回读验证。

    Args:
        session: 会话状态。
        node: 拓扑节点。
        device_id: 监测点设备 ID。
        resolved: profile 解析结果。
        detail: 电表明细行字典。
        task_id: 任务 ID。

    Returns:
        保存结果字典，含 ok、mismatches 等。
    """
    try:
        mismatches = _save_meter_parameters(
            session, node, device_id, resolved, detail, task_id,
        )
    except EdgeApiError as exc:
        return {"ok": False, "mismatches": [f"保存调用失败: {exc}"]}
    return {"ok": not mismatches, "mismatches": mismatches}


def _read_device_record(session: EdgeSession, device_id: str) -> dict:
    """从档案查询响应中严格选择目标设备，支持单对象及列表。"""
    resp = _client_for(session).call(PATH_GET_DEVICE_LIST, {"deviceId": device_id})
    if not resp.get("ok"):
        raise EdgeApiError(f"回读失败: rtnCode={resp.get('rtnCode')}")
    data = resp.get("data")
    if isinstance(data, dict):
        rows = data.get("rows", [data])
    else:
        rows = data
    if not isinstance(rows, list):
        raise EdgeApiError("回读响应不是档案列表")
    matches = [
        row for row in rows if isinstance(row, dict)
        and str(row.get("deviceId", "")) == device_id
    ]
    if len(matches) != 1:
        raise EdgeApiError("回读目标设备缺失或不唯一")
    return matches[0]


def _compare_archive_fields(base: dict, ext: dict, actual: dict) -> list[str]:
    """逐一比较已写字段；缺失、零值丢失和扩展字段差异均不能通过。"""
    # 后端自行计算的扩展字段，不纳入回读验证
    _skip_ext_keys = {"dsTypeId", "deviceId"}

    def text(value: object) -> str:
        return "" if value is None else str(value).strip()

    errors = []
    for key, value in base.items():
        # 重复地址策略是请求选项，不是可回读的设备属性。
        if key in ("deviceId", "commAddrRepetition", "extInfos") or text(value) == "":
            continue
        if key not in actual or text(actual[key]) != text(value):
            errors.append(f"{key}: 期望={text(value)!r}, 实际={text(actual.get(key))!r}")
    actual_ext = {
        item.get("propertyCode"): item.get("propertyValue")
        for item in actual.get("extInfos", []) or [] if isinstance(item, dict)
    }
    for key, value in ext.items():
        if text(value) == "" or key in _skip_ext_keys:
            continue
        if key not in actual_ext or text(actual_ext[key]) != text(value):
            errors.append(f"extInfos.{key}: 期望={text(value)!r}, 实际不一致或缺失")
    return errors


def _read_gateway_address_body(session: EdgeSession, device_id: str) -> dict:
    """读取唯一地址参数对象，拒绝结构异常，空列表表示尚无参数项。"""
    resp = _client_for(session).call(
        PATH_GET_DEVICE_PARAM,
        {"deviceId": device_id, "itemIdS": [GATEWAY_ADDRESS_ITEM_ID]},
    )
    if not resp.get("ok") or not isinstance(resp.get("data"), list):
        raise EdgeApiError("无法读取原地址参数，禁止覆盖未确认字段")
    items = [
        item for item in resp["data"] if isinstance(item, dict)
        and item.get("itemId") == GATEWAY_ADDRESS_ITEM_ID
    ]
    if not items:
        return {}
    if len(items) != 1 or not isinstance(items[0].get("itemBody"), dict):
        raise EdgeApiError("原地址参数项不唯一或itemBody不是对象")
    return items[0]["itemBody"]


def _read_deploy_param_body(session: EdgeSession, device_id: str) -> dict:
    """读取监测点 20200002 当前参数 itemBody（下发通用读）。

    参数项缺失、不唯一或 itemBody 为空/结构异常时抛 EdgeApiError，
    由调用方整批失败处理；禁止回退模板值或虚构默认报文。

    Args:
        session: 会话状态。
        device_id: 监测点后端 deviceId。

    Returns:
        设备当前参数的 itemBody 字典（非空）。

    Raises:
        EdgeApiError: 读取失败或参数项不合法时。
    """
    resp = _client_for(session).call(
        PATH_GET_DEVICE_PARAM,
        {"deviceId": device_id, "itemIdS": [METER_DEPLOY_ITEM_ID]},
    )
    if not resp.get("ok") or not isinstance(resp.get("data"), list):
        raise EdgeApiError(
            f"无法读取当前参数项 {METER_DEPLOY_ITEM_ID}"
        )
    items = [
        item for item in resp["data"] if isinstance(item, dict)
        and item.get("itemId") == METER_DEPLOY_ITEM_ID
    ]
    if not items:
        raise EdgeApiError(
            f"当前参数项 {METER_DEPLOY_ITEM_ID} 缺失，请先完成参数保存"
        )
    if (len(items) != 1
            or not isinstance(items[0].get("itemBody"), dict)
            or not items[0]["itemBody"]):
        raise EdgeApiError(
            f"当前参数项 {METER_DEPLOY_ITEM_ID} 不唯一或 itemBody 为空/异常"
        )
    return dict(items[0]["itemBody"])


def _build_deploy_body_from_archive(session: EdgeSession, device_id: str) -> dict:
    """从设备档案现值组装 20200002 下发 itemBody（免模板首写用）。

    档案已是码值形态（protocolNumber/proxyCommPort/decimalNum…），字段
    来源与 profile 一致；authParam 经 normalize_auth_param_for_deploy 归一。
    必需项 commAddr 缺失或非法时抛 EdgeApiError，由调用方跳过该台，绝不虚构。

    Args:
        session: 已登录边缘会话。
        device_id: 目标监测点 deviceId。

    Returns:
        20200002 itemBody 字典。

    Raises:
        EdgeApiError: 档案缺失、commAddr 非法等无法组装时。
    """
    record = _read_device_record(session, device_id)
    ext = {
        str(e.get("propertyCode")): str(e.get("propertyValue") or "")
        for e in (record.get("extInfos") or []) if isinstance(e, dict)
    }

    def _int_or_none(key: str, src: dict) -> int | None:
        raw = str(src.get(key, "") or "").strip()
        return int(raw) if raw.lstrip("-").isdigit() else None

    comm_addr = str(record.get("deviceAddress") or "").strip()
    if not comm_addr:
        raise EdgeApiError("档案缺通讯地址 deviceAddress，无法组装下发项")
    try:
        comm_addr = validate_device_address(comm_addr)
    except AddressConversionError as exc:
        raise EdgeApiError(f"档案通讯地址非法: {exc}") from exc

    body: dict = {"commAddr": comm_addr, "baudRate": ""}
    for key, src, field in (
        ("roadNo", record, "agentNum"),
        ("measurNo", record, "measuredPointNum"),
        ("protocolCode", record, "protocolNumber"),
        ("comPort", record, "proxyCommPort"),
        ("decimalNum", ext, "decimalNum"),
        ("userBigNo", ext, "userBigNo"),
        ("userSmallNo", ext, "userSmallNo"),
        ("feeNum", ext, "feeNum"),
    ):
        val = _int_or_none(field, src)
        if val is not None:
            body[key] = val
    integer_num = _int_or_none("integerNum", ext)
    body["integerNum"] = integer_num if integer_num is not None else 6
    # feeNum 恒含：页面下发实测恒带 feeNum（缺省 1），缺失会致 RTU DENY；
    # 档案有显值用显值，否则对齐页面默认 1。
    if "feeNum" not in body:
        body["feeNum"] = 1
    body["authParam"] = normalize_auth_param_for_deploy(ext.get("authParam", ""))
    coll = str(record.get("collectorAddress") or "").strip()
    body["collCommAddr"] = coll if coll else "000000000000"
    body["aCommAddr"] = ext.get("aCommAddr", "")
    return body


def _verify_gateway_address(session: EdgeSession, device_id: str, expected: dict) -> list[str]:
    """回读175网关20100024参数项，核对通讯地址（identifier 非后端持久化字段，跳过验证）。"""
    resp = _client_for(session).call(
        PATH_GET_DEVICE_PARAM,
        {"deviceId": device_id, "itemIdS": [GATEWAY_ADDRESS_ITEM_ID]},
    )
    if not resp.get("ok") or not isinstance(resp.get("data"), list):
        return ["网关地址参数回读失败"]
    items = [
        item for item in resp["data"] if isinstance(item, dict)
        and item.get("itemId") == GATEWAY_ADDRESS_ITEM_ID
    ]
    if len(items) != 1 or not isinstance(items[0].get("itemBody"), dict):
        return ["网关地址参数项缺失或不唯一"]
    actual = items[0]["itemBody"]
    # 即便前端只显示commAddr，实际写入字段仍须完整回读。
    # identifier 后端不持久化，跳过验证。
    return [
        f"20100024.{key} 与本次保存值不一致或缺失"
        for key, value in expected.items()
        if key != "identifier"
        and (key not in actual or str(actual[key]) != str(value))
    ]


def _collect_all_monitor_point_keys(
    session: EdgeSession, gateway_node_key: str,
) -> list[str]:
    """收集网关子树下所有监测点节点键（用于全量下发）。

    递归遍历网关整棵子树，包含多级子网关下的监测点，排除网关本身。
    下发/召测为通用能力，覆盖所有非网关监测点类型。
    与 _build_monitor_point_item_body 的收集逻辑保持一致。

    Args:
        session: 会话状态。
        gateway_node_key: 网关节点键。

    Returns:
        监测点节点键列表，空列表表示无监测点。
    """
    node_map = session.template.node_map()
    child_map: dict[str, list[str]] = {}
    for n in session.template.nodes:
        if n.parent_key:
            child_map.setdefault(n.parent_key, []).append(n.node_key)

    all_point_keys: list[str] = []
    stack = [gateway_node_key]
    while stack:
        cur = stack.pop()
        for ck in child_map.get(cur, []):
            child = node_map.get(ck)
            if child is None:
                continue
            prof, _ = default_registry.resolve(child.device_type, "")
            if prof and getattr(prof, "is_gateway", False):
                stack.append(ck)  # 子网关：继续向下收集
            else:
                all_point_keys.append(ck)

    return all_point_keys


def _parse_smart_event_online(resp: dict, device_id: str) -> bool:
    """解析 getSmartEventData 响应：时间窗内该 deviceId 有任意上报即在线。

    兼容 data 为 rtnData（dict 含 responseData）或直接 list 两种形态。
    不看 dataVal 的 0/1（那是开关状态），只看是否有上报记录。

    Args:
        resp: client.call 归一化后的响应。
        device_id: 目标 deviceId。

    Returns:
        在线为 True，无记录为 False。
    """
    data = resp.get("data") if isinstance(resp, dict) else None
    entries: list = []
    if isinstance(data, dict):
        entries = data.get("responseData", []) or []
    elif isinstance(data, list):
        entries = data
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("deviceId", "")) != str(device_id):
            continue
        arr = entry.get("dataArray")
        if isinstance(arr, list) and len(arr) > 0:
            return True
    return False


def _build_monitor_point_item_body(
    session: EdgeSession,
    gateway_node_key: str,
    node_keys: list[str] | None = None,
) -> tuple[dict[str, list[dict]], list[str], list[tuple[str, str]]]:
    """收集下发用监测点 itemBody（数据源：模板填报值算出的 deploy_item_body）。

    通用能力：不区分监测点类型，下发内容为 profile 依据用户在模板实际填报值
    算出的 `deploy_item_body`（itemId 20200002），服务端不再实时读后端当前参数
    记录。某目标无 deviceId 或无有效 deploy_item_body → 仅跳过该目标并记录
    原因，不连坐整批。

    Args:
        session: 会话状态。
        gateway_node_key: 网关节点键。
        node_keys: 显式非空监测点节点键列表；空或 None 表示全量下发。

    Returns:
        三元组 ``(item_bodies_by_item_id, included_keys, skipped)``：
          - item_bodies_by_item_id: {itemId: [itemBody, ...]}。
          - included_keys: 纳入本次下发的 node_key 列表。
          - skipped: [(node_key, reason), ...] 被跳过的目标。
    """
    skipped: list[tuple[str, str]] = []
    # 空值表示全量：先按网关子树收集所有监测点
    if not node_keys:
        node_keys = _collect_all_monitor_point_keys(session, gateway_node_key)
    if not node_keys or len(node_keys) != len(set(node_keys)):
        return {}, [], [("*", "下发集合必须显式、非空且不重复")]
    # 归属校验：请求节点必须属于此网关子树（拓扑正确性，非阶段门禁）
    node_map = session.template.node_map()
    subtree_keys = set(
        _collect_all_monitor_point_keys(session, gateway_node_key)
    )
    orphan_keys = {k for k in node_keys if k not in subtree_keys}
    if orphan_keys:
        return {}, [], [
            (k, f"不属于网关 {gateway_node_key} 的子树")
            for k in sorted(orphan_keys)
        ]
    # 从 plan 各节点取 profile 算好的 deploy_item_body
    body_by_key = {
        it.get("node_key"): it.get("deploy_item_body")
        for it in session.last_plan.get("items", [])
    }
    item_bodies_by_item_id: dict[str, list[dict]] = {}
    included: list[str] = []
    for key in node_keys:
        node = node_map.get(key)
        if node is None:
            skipped.append((key, "下发节点不存在"))
            continue
        device_id = str(
            session.key_to_device_id.get(key, "") or node.device_id or ""
        )
        if not device_id:
            skipped.append((key, "尚未建档，无 deviceId"))
            continue
        body = body_by_key.get(key)
        # 一致性校验：待推 itemBody 必须是非空 dict（即用户填报映射）
        if not isinstance(body, dict) or not body:
            skipped.append((key, "无有效下发参数（deploy_item_body 缺失/为空）"))
            continue
        item_bodies_by_item_id.setdefault(
            METER_DEPLOY_ITEM_ID, []
        ).append(body)
        included.append(key)
    return item_bodies_by_item_id, included, skipped
