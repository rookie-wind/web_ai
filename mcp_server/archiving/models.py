"""XLPA 自动建档核心数据模型。

覆盖一次边缘建档任务的结构化对象：任务配置、拓扑节点、profile 字段、
dry-run 计划、执行结果和补偿清单。所有模型提供 ``to_dict`` /
``from_dict``，保证在工具返回、报告落盘和复跑之间的序列化稳定性。

敏感字段（password、token）通过 ``redacted`` 系列方法脱敏，
默认 ``to_dict`` 不输出明文密码。
"""

from __future__ import annotations

__all__ = [
    "TaskConfig",
    "TopologyNode",
    "FieldTarget",
    "ProfileField",
    "PlanAction",
    "DryRunItem",
    "DryRunPlan",
    "ExecutionItem",
    "ExecutionResult",
    "CompensationEntry",
    "CompensationPlan",
    "FieldSource",
    "EvidenceStatus",
    "InputType",
    "FieldSpec",
    "CellInput",
    "ResolvedField",
    "TemplateSnapshot",
    "TypeSheetSpec",
    "REDACTED",
]

from dataclasses import dataclass, field
from enum import Enum
import uuid

# 敏感字段脱敏占位符
REDACTED = "***REDACTED***"


class FieldTarget(str, Enum):
    """profile 字段在建档 payload 中的落点分类。"""

    BASE_FIELD = "base_field"
    EXT_INFOS = "extInfos"
    DATA_ITEM = "data_item"
    DERIVED = "derived"


class PlanAction(str, Enum):
    """dry-run 计划中单个节点的动作类型。"""

    CREATE = "create"
    UPDATE = "update"
    SKIP = "skip"
    CONFLICT = "conflict"


@dataclass
class TaskConfig:
    """自动建档任务配置（来自 Excel 任务配置 sheet）。"""

    edge_base_url: str = ""
    login_name: str = ""
    password: str = ""
    phone: str = ""
    captcha: str = ""
    request_timeout: float = 25.0
    link_timeout: float = 12.0
    allow_deploy: bool = False
    allow_poll: bool = False
    default_proxy_comm_type: str = ""
    # 品牌/型号码值来自模板「映射」表，未知名称禁止透传写入。
    brand_name_to_code: dict[str, str] = field(default_factory=dict)
    model_code_by_brand: dict[str, dict[str, str]] = field(default_factory=dict)
    # 用户大分类号名称→码值映射（来自模板「映射」表，空时回退硬编码）。
    user_big_no_name_to_code: dict[str, str] = field(default_factory=dict)
    # 门户代理模式（由目标 IP 段自动判定：20.* 走代理，10.* 直连）
    proxy_mode: bool = False

    def to_dict(self, *, redact: bool = True) -> dict:
        """序列化为字典。

        Args:
            redact: 是否对 password 脱敏，默认 True。

        Returns:
            任务配置字典。
        """
        return {
            "edge_base_url": self.edge_base_url,
            "login_name": self.login_name,
            "password": REDACTED if redact and self.password else self.password,
            "phone": self.phone,
            "captcha": REDACTED if redact and self.captcha else self.captcha,
            "request_timeout": self.request_timeout,
            "link_timeout": self.link_timeout,
            "allow_deploy": self.allow_deploy,
            "allow_poll": self.allow_poll,
            "default_proxy_comm_type": self.default_proxy_comm_type,
            "brand_name_to_code": dict(self.brand_name_to_code),
            "model_code_by_brand": {
                k: dict(v) for k, v in self.model_code_by_brand.items()
            },
            "user_big_no_name_to_code": dict(self.user_big_no_name_to_code),
            "proxy_mode": self.proxy_mode,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskConfig":
        """从字典反序列化。

        Args:
            data: 任务配置字典。

        Returns:
            TaskConfig 实例。
        """
        data = data or {}
        return cls(
            edge_base_url=str(data.get("edge_base_url", "") or ""),
            login_name=str(data.get("login_name", "") or ""),
            password=str(data.get("password", "") or ""),
            phone=str(data.get("phone", "") or ""),
            captcha=str(data.get("captcha", "") or ""),
            request_timeout=float(data.get("request_timeout", 25.0) or 25.0),
            link_timeout=float(data.get("link_timeout", 12.0) or 12.0),
            allow_deploy=bool(data.get("allow_deploy", False)),
            allow_poll=bool(data.get("allow_poll", False)),
            default_proxy_comm_type=str(
                data.get("default_proxy_comm_type", "") or ""
            ),
            brand_name_to_code=dict(data.get("brand_name_to_code", {}) or {}),
            model_code_by_brand={
                str(k): dict(v or {})
                for k, v in (data.get("model_code_by_brand", {}) or {}).items()
            },
            user_big_no_name_to_code=dict(
                data.get("user_big_no_name_to_code", {}) or {}
            ),
            proxy_mode=bool(data.get("proxy_mode", False)),
        )


@dataclass
class TopologyNode:
    """拓扑总览中的单个设备节点。"""

    node_key: str = ""
    parent_key: str = ""
    device_name: str = ""
    device_type: str = ""
    device_id: str = ""
    identifier: str = ""
    comm_address: str = ""
    road_no: str = ""
    # 类型明细字段（网关明细 / XLBA 电表明细按节点键关联后合并）
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """序列化为字典。"""
        return {
            "node_key": self.node_key,
            "parent_key": self.parent_key,
            "device_name": self.device_name,
            "device_type": self.device_type,
            "device_id": self.device_id,
            "identifier": self.identifier,
            "comm_address": self.comm_address,
            "road_no": self.road_no,
            "detail": dict(self.detail),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TopologyNode":
        """从字典反序列化。

        Args:
            data: 拓扑节点字典。

        Returns:
            TopologyNode 实例。
        """
        data = data or {}
        return cls(
            node_key=str(data.get("node_key", "") or ""),
            parent_key=str(data.get("parent_key", "") or ""),
            device_name=str(data.get("device_name", "") or ""),
            device_type=str(data.get("device_type", "") or ""),
            device_id=str(data.get("device_id", "") or ""),
            identifier=str(data.get("identifier", "") or ""),
            comm_address=str(data.get("comm_address", "") or ""),
            road_no=str(data.get("road_no", "") or ""),
            detail=dict(data.get("detail", {}) or {}),
        )

    def idempotency_key(self) -> tuple[str, str]:
        """返回幂等匹配键（名称驱动：设备名称即可，分路号留空）。

        Returns:
            二元组 (设备名称, 空)；网关与监测点均按全局唯一设备名称去重。
        """
        return (self.device_name, "")


@dataclass
class ProfileField:
    """profile 字段映射声明。

    描述一个 Excel/档案字段落到建档 payload 的位置与来源。
    """

    name: str = ""
    target: FieldTarget = FieldTarget.BASE_FIELD
    source: str = ""
    required: bool = False
    default: str = ""

    def to_dict(self) -> dict:
        """序列化为字典。"""
        return {
            "name": self.name,
            "target": self.target.value,
            "source": self.source,
            "required": self.required,
            "default": self.default,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProfileField":
        """从字典反序列化。

        Args:
            data: profile 字段字典。

        Returns:
            ProfileField 实例。
        """
        data = data or {}
        return cls(
            name=str(data.get("name", "") or ""),
            target=FieldTarget(data.get("target", FieldTarget.BASE_FIELD.value)),
            source=str(data.get("source", "") or ""),
            required=bool(data.get("required", False)),
            default=str(data.get("default", "") or ""),
        )


@dataclass
class DryRunItem:
    """dry-run 计划中单个节点的计划项。"""

    node_key: str = ""
    action: PlanAction = PlanAction.SKIP
    device_type: str = ""
    device_id: str = ""
    parent_device_id: str = ""
    road_no: str = ""
    reason: str = ""
    payload: dict = field(default_factory=dict)
    # 冲突是否属结构性（重名/孤立/不支持类型/编号冲突）。
    # 结构性冲突参与 executable=False；字段级（个别目标填错）置 False 不连坐。
    structural: bool = True

    def to_dict(self) -> dict:
        """序列化为字典。"""
        return {
            "node_key": self.node_key,
            "action": self.action.value,
            "device_type": self.device_type,
            "device_id": self.device_id,
            "parent_device_id": self.parent_device_id,
            "road_no": self.road_no,
            "reason": self.reason,
            "payload": dict(self.payload),
            "structural": self.structural,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DryRunItem":
        """从字典反序列化。

        Args:
            data: 计划项字典。

        Returns:
            DryRunItem 实例。
        """
        data = data or {}
        return cls(
            node_key=str(data.get("node_key", "") or ""),
            action=PlanAction(data.get("action", PlanAction.SKIP.value)),
            device_type=str(data.get("device_type", "") or ""),
            device_id=str(data.get("device_id", "") or ""),
            parent_device_id=str(data.get("parent_device_id", "") or ""),
            road_no=str(data.get("road_no", "") or ""),
            reason=str(data.get("reason", "") or ""),
            payload=dict(data.get("payload", {}) or {}),
            structural=bool(data.get("structural", True)),
        )


@dataclass
class DryRunPlan:
    """完整 dry-run 计划。

    Attributes:
        plan_id: 计划唯一标识（UUID v4）。
        items: 各节点计划项。
        conflicts: 冲突项。
        deploy_planned: 是否规划下发。
        poll_planned: 是否规划召测。
        warnings: 告警列表。
        node_key_to_device_id: 条码 -> 后端 deviceId（SKIP 回填）。
        executable: 计划是否可执行（无冲突且模板有效）。
        binding_summary: 绑定摘要（node_key -> 父级信息）。
        field_sources: 字段来源（node_key -> {字段键: 来源分类}）。
        create_batches: 新建批次清单（按拓扑顺序分组）。
        deploy_batches: 下发批次清单（按网关分组）。
        preconditions: 阶段前置条件列表。
    """

    plan_id: str = ""
    items: list[DryRunItem] = field(default_factory=list)
    conflicts: list[DryRunItem] = field(default_factory=list)
    deploy_planned: bool = False
    poll_planned: bool = False
    warnings: list[str] = field(default_factory=list)
    # 条码（节点主键）-> 后端 deviceId：命中 SKIP 时回填，供下发复用
    node_key_to_device_id: dict[str, str] = field(default_factory=dict)
    # design §6：计划可执行性标志
    executable: bool = True
    # 绑定摘要：node_key -> {parent_key, parent_device_id, parent_barcode}
    binding_summary: dict[str, dict] = field(default_factory=dict)
    # 字段来源：node_key -> {field_key: source_label}
    field_sources: dict[str, dict[str, str]] = field(default_factory=dict)
    # 新建批次清单（按拓扑顺序）
    create_batches: list[list[str]] = field(default_factory=list)
    # 下发批次清单（按网关分组）
    deploy_batches: list[dict] = field(default_factory=list)
    # 阶段前置条件
    preconditions: list[str] = field(default_factory=list)

    @property
    def has_conflict(self) -> bool:
        """是否存在需要用户裁决的冲突项。"""
        return bool(self.conflicts) or any(
            item.action == PlanAction.CONFLICT for item in self.items
        )

    def counts(self) -> dict:
        """统计各动作数量。

        Returns:
            动作名到数量的字典。
        """
        result: dict[str, int] = {}
        for item in self.items:
            result[item.action.value] = result.get(item.action.value, 0) + 1
        return result

    def to_dict(self) -> dict:
        """序列化为字典。"""
        return {
            "plan_id": self.plan_id,
            "items": [item.to_dict() for item in self.items],
            "conflicts": [item.to_dict() for item in self.conflicts],
            "deploy_planned": self.deploy_planned,
            "poll_planned": self.poll_planned,
            "warnings": list(self.warnings),
            "node_key_to_device_id": dict(self.node_key_to_device_id),
            "has_conflict": self.has_conflict,
            "executable": self.executable,
            "binding_summary": dict(self.binding_summary),
            "field_sources": {
                k: dict(v) for k, v in self.field_sources.items()
            },
            "create_batches": [list(b) for b in self.create_batches],
            "deploy_batches": [dict(b) for b in self.deploy_batches],
            "preconditions": list(self.preconditions),
            "counts": self.counts(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DryRunPlan":
        """从字典反序列化。

        Args:
            data: 计划字典。

        Returns:
            DryRunPlan 实例。
        """
        data = data or {}
        return cls(
            plan_id=str(data.get("plan_id", "") or ""),
            items=[DryRunItem.from_dict(x) for x in data.get("items", [])],
            conflicts=[DryRunItem.from_dict(x) for x in data.get("conflicts", [])],
            deploy_planned=bool(data.get("deploy_planned", False)),
            poll_planned=bool(data.get("poll_planned", False)),
            warnings=list(data.get("warnings", []) or []),
            node_key_to_device_id=dict(
                data.get("node_key_to_device_id", {}) or {}
            ),
            executable=bool(data.get("executable", True)),
            binding_summary=dict(data.get("binding_summary", {}) or {}),
            field_sources={
                k: dict(v)
                for k, v in (data.get("field_sources", {}) or {}).items()
            },
            create_batches=[
                list(b) for b in data.get("create_batches", []) or []
            ],
            deploy_batches=[
                dict(b) for b in data.get("deploy_batches", []) or []
            ],
            preconditions=list(data.get("preconditions", []) or []),
        )


@dataclass
class ExecutionItem:
    """单个执行动作的结果。"""

    node_key: str = ""
    action: str = ""
    ok: bool = False
    device_id: str = ""
    rtn_code=None
    rtn_msg: str = ""

    def to_dict(self) -> dict:
        """序列化为字典。"""
        return {
            "node_key": self.node_key,
            "action": self.action,
            "ok": self.ok,
            "device_id": self.device_id,
            "rtnCode": self.rtn_code,
            "rtnMsg": self.rtn_msg,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ExecutionItem":
        """从字典反序列化。

        Args:
            data: 执行结果项字典。

        Returns:
            ExecutionItem 实例。
        """
        data = data or {}
        return cls(
            node_key=str(data.get("node_key", "") or ""),
            action=str(data.get("action", "") or ""),
            ok=bool(data.get("ok", False)),
            device_id=str(data.get("device_id", "") or ""),
            rtn_code=data.get("rtnCode"),
            rtn_msg=str(data.get("rtnMsg", "") or ""),
        )


@dataclass
class ExecutionResult:
    """一次建档执行的整体结果。"""

    items: list[ExecutionItem] = field(default_factory=list)
    # 节点键 -> 新建 deviceId 映射，用于复跑回填
    node_key_to_device_id: dict[str, str] = field(default_factory=dict)
    succeeded: bool = True

    def to_dict(self) -> dict:
        """序列化为字典。"""
        return {
            "items": [item.to_dict() for item in self.items],
            "node_key_to_device_id": dict(self.node_key_to_device_id),
            "succeeded": self.succeeded,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ExecutionResult":
        """从字典反序列化。

        Args:
            data: 执行结果字典。

        Returns:
            ExecutionResult 实例。
        """
        data = data or {}
        return cls(
            items=[ExecutionItem.from_dict(x) for x in data.get("items", [])],
            node_key_to_device_id=dict(
                data.get("node_key_to_device_id", {}) or {}
            ),
            succeeded=bool(data.get("succeeded", True)),
        )


@dataclass
class CompensationEntry:
    """补偿清单条目：本次新建的可回滚设备。"""

    node_key: str = ""
    device_id: str = ""
    device_name: str = ""
    parent_device_id: str = ""
    delete_payload: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """序列化为字典。"""
        return {
            "node_key": self.node_key,
            "device_id": self.device_id,
            "device_name": self.device_name,
            "parent_device_id": self.parent_device_id,
            "delete_payload": dict(self.delete_payload),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CompensationEntry":
        """从字典反序列化。

        Args:
            data: 补偿条目字典。

        Returns:
            CompensationEntry 实例。
        """
        data = data or {}
        return cls(
            node_key=str(data.get("node_key", "") or ""),
            device_id=str(data.get("device_id", "") or ""),
            device_name=str(data.get("device_name", "") or ""),
            parent_device_id=str(data.get("parent_device_id", "") or ""),
            delete_payload=dict(data.get("delete_payload", {}) or {}),
        )


@dataclass
class CompensationPlan:
    """补偿清单：仅包含本次新建设备，按叶子到父节点顺序清理。"""

    entries: list[CompensationEntry] = field(default_factory=list)

    def add(self, entry: CompensationEntry) -> None:
        """追加一条本次新建设备记录。

        Args:
            entry: 补偿条目。
        """
        self.entries.append(entry)

    def delete_order(self) -> list[CompensationEntry]:
        """返回叶子到父节点的删除顺序。

        以 parent_device_id 是否被其它条目的 device_id 引用判定层级：
        被引用为父节点的条目排在后面（后删）。

        Returns:
            排序后的补偿条目列表。
        """
        parent_ids = {e.parent_device_id for e in self.entries if e.parent_device_id}
        # 叶子：其 device_id 不作为任何条目的父节点
        leaves = [e for e in self.entries if e.device_id not in parent_ids]
        non_leaves = [e for e in self.entries if e.device_id in parent_ids]
        return leaves + non_leaves

    def to_dict(self) -> dict:
        """序列化为字典。"""
        return {
            "entries": [e.to_dict() for e in self.entries],
            "delete_order": [e.node_key for e in self.delete_order()],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CompensationPlan":
        """从字典反序列化。

        Args:
            data: 补偿清单字典。

        Returns:
            CompensationPlan 实例。
        """
        data = data or {}
        return cls(
            entries=[
                CompensationEntry.from_dict(x) for x in data.get("entries", [])
            ]
        )


class FieldSource(str, Enum):
    """字段取值来源分类（design §2）。"""

    ENGINEER_INPUT = "engineer_input"
    PROTOCOL_CONSTANT = "protocol_constant"
    DERIVED = "derived"


class EvidenceStatus(str, Enum):
    """字段码值／落点的证据状态，对应 G1 门槛。

    - ``VERIFIED``：后端实测确认。
    - ``PROTOCOL``：协议文档为据，端到端未实测。
    - ``UNVERIFIED``：落点或码值未确认，禁止进入可执行模板与下发。
    """

    VERIFIED = "verified"
    PROTOCOL = "protocol"
    UNVERIFIED = "unverified"


class InputType(str, Enum):
    """工程输入单元格的值类型，供 reader 保真解析。"""

    TEXT = "text"
    INTEGER = "integer"
    FLOAT = "float"
    ENUM = "enum"
    PASSWORD = "password"


@dataclass
class FieldSpec:
    """版本化字段契约中的单列声明。

    generator / reader / profile / payload 构造器 / 回读比较器共享本结构，
    不再各自维护名称码值表，消除各层独立补默认与映射漂移。

    Attributes:
        field_key: 稳定字段键（reader 翻译后的 propertyCode）。
        header: Excel 中文列名（工程人员所见）。
        input_type: 单元格值类型。
        source: 取值来源分类。
        dict_scope: 字典作用域名（ENUM 下拉取池来源；空表示无平台池）。
        required: 是否必填。
        code_map: 下拉友好名到后端码值映射（ENUM 用）。
        archive_base_key: 落档案 base_payload 的后端键。
        archive_ext_key: 落 extInfos 的后端键（双写时）。
        deploy_key: 落下发 itemBody 的后端键。
        readback_path: 回读比较路径。
        derived_deps: 派生所依赖的其它 field_key。
        evidence: 证据状态；UNVERIFIED 字段不得进入可执行模板。
        note: 出处／歧义说明。
    """

    field_key: str = ""
    header: str = ""
    input_type: InputType = InputType.TEXT
    source: FieldSource = FieldSource.ENGINEER_INPUT
    dict_scope: str = ""
    required: bool = False
    code_map: dict[str, str] = field(default_factory=dict)
    archive_base_key: str = ""
    archive_ext_key: str = ""
    deploy_key: str = ""
    readback_path: str = ""
    derived_deps: tuple[str, ...] = ()
    evidence: EvidenceStatus = EvidenceStatus.UNVERIFIED
    note: str = ""

    def dropdown_options(self) -> list[str]:
        """返回下拉选项（友好名），供 generator 建命名区域。"""
        return list(self.code_map.keys())

    def is_executable(self) -> bool:
        """字段落点／码值是否已核实、可进入可执行模板。"""
        return self.evidence is not EvidenceStatus.UNVERIFIED

    def to_dict(self) -> dict:
        """序列化为字典。"""
        return {
            "field_key": self.field_key,
            "header": self.header,
            "input_type": self.input_type.value,
            "source": self.source.value,
            "dict_scope": self.dict_scope,
            "required": self.required,
            "code_map": dict(self.code_map),
            "archive_base_key": self.archive_base_key,
            "archive_ext_key": self.archive_ext_key,
            "deploy_key": self.deploy_key,
            "readback_path": self.readback_path,
            "derived_deps": list(self.derived_deps),
            "evidence": self.evidence.value,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FieldSpec":
        """从字典反序列化。

        Args:
            data: 字段契约字典。

        Returns:
            FieldSpec 实例。
        """
        data = data or {}
        return cls(
            field_key=str(data.get("field_key", "") or ""),
            header=str(data.get("header", "") or ""),
            input_type=InputType(data.get("input_type", InputType.TEXT.value)),
            source=FieldSource(
                data.get("source", FieldSource.ENGINEER_INPUT.value)
            ),
            dict_scope=str(data.get("dict_scope", "") or ""),
            required=bool(data.get("required", False)),
            code_map=dict(data.get("code_map", {}) or {}),
            archive_base_key=str(data.get("archive_base_key", "") or ""),
            archive_ext_key=str(data.get("archive_ext_key", "") or ""),
            deploy_key=str(data.get("deploy_key", "") or ""),
            readback_path=str(data.get("readback_path", "") or ""),
            derived_deps=tuple(data.get("derived_deps", ()) or ()),
            evidence=EvidenceStatus(
                data.get("evidence", EvidenceStatus.UNVERIFIED.value)
            ),
            note=str(data.get("note", "") or ""),
        )


@dataclass
class CellInput:
    """reader 从单元格解析出的保真输入。

    Attributes:
        field_key: 对应 FieldSpec 键。
        raw: 单元格原始标量（保留类型，不做 ``or default`` 判空）。
        filled: 是否已填写（None／纯空白为 False；0／"0"／False 为 True）。
        normalized: 依 input_type 规范化后的值。
        sheet: 工作表名。
        row: 行号（1 基）。
        column: 列字母。
        mapping_source: 名称到码值映射来源标识。
    """

    field_key: str = ""
    raw: object = None
    filled: bool = False
    normalized: object = None
    sheet: str = ""
    row: int = 0
    column: str = ""
    mapping_source: str = ""

    def to_dict(self) -> dict:
        """序列化为字典。"""
        return {
            "field_key": self.field_key,
            "raw": self.raw,
            "filled": self.filled,
            "normalized": self.normalized,
            "sheet": self.sheet,
            "row": self.row,
            "column": self.column,
            "mapping_source": self.mapping_source,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CellInput":
        """从字典反序列化。

        Args:
            data: 单元格输入字典。

        Returns:
            CellInput 实例。
        """
        data = data or {}
        return cls(
            field_key=str(data.get("field_key", "") or ""),
            raw=data.get("raw"),
            filled=bool(data.get("filled", False)),
            normalized=data.get("normalized"),
            sheet=str(data.get("sheet", "") or ""),
            row=int(data.get("row", 0) or 0),
            column=str(data.get("column", "") or ""),
            mapping_source=str(data.get("mapping_source", "") or ""),
        )


@dataclass
class ResolvedField:
    """由 CellInput 依契约解析出的、按落点分列的字段结果。

    Attributes:
        field_key: 对应 FieldSpec 键。
        source: 取值来源分类。
        value: 已确定的规范化值（未填／不适用为 None）。
        archive_base: 落档案 base_payload 的 ``{后端键: 值}``。
        archive_ext: 落 extInfos 的 ``{后端键: 值}``。
        deploy: 落下发 itemBody 的 ``{后端键: 值}``。
        readback: 回读比较的 ``{路径: 值}``。
        applicable: 本字段在当前动作是否有落点。
        reason: 不适用时的显式理由（design §2／§6）。
    """

    field_key: str = ""
    source: FieldSource = FieldSource.ENGINEER_INPUT
    value: object = None
    archive_base: dict = field(default_factory=dict)
    archive_ext: dict = field(default_factory=dict)
    deploy: dict = field(default_factory=dict)
    readback: dict = field(default_factory=dict)
    applicable: bool = True
    reason: str = ""

    def to_dict(self) -> dict:
        """序列化为字典。"""
        return {
            "field_key": self.field_key,
            "source": self.source.value,
            "value": self.value,
            "archive_base": dict(self.archive_base),
            "archive_ext": dict(self.archive_ext),
            "deploy": dict(self.deploy),
            "readback": dict(self.readback),
            "applicable": self.applicable,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ResolvedField":
        """从字典反序列化。

        Args:
            data: 已解析字段字典。

        Returns:
            ResolvedField 实例。
        """
        data = data or {}
        return cls(
            field_key=str(data.get("field_key", "") or ""),
            source=FieldSource(
                data.get("source", FieldSource.ENGINEER_INPUT.value)
            ),
            value=data.get("value"),
            archive_base=dict(data.get("archive_base", {}) or {}),
            archive_ext=dict(data.get("archive_ext", {}) or {}),
            deploy=dict(data.get("deploy", {}) or {}),
            readback=dict(data.get("readback", {}) or {}),
            applicable=bool(data.get("applicable", True)),
            reason=str(data.get("reason", "") or ""),
        )


@dataclass
class TemplateSnapshot:
    """服务端权威的模板快照（design §2）。

    Attributes:
        version: 模板结构版本（如 ``v15-engineer``）。
        field_contract_version: 字段契约版本。
        snapshot_id: 随机快照 ID。
        source_time: 字典来源时间（ISO 字符串）。
        dictionaries: 作用域到字典记录列表（含来源／名称／码值／获取时间）。
        mappings: field_key 到 ``{友好名: 码值}``。
        content_digest: 规范化字典内容摘要（SHA-256）。
    """

    version: str = ""
    field_contract_version: str = ""
    snapshot_id: str = ""
    source_time: str = ""
    dictionaries: dict = field(default_factory=dict)
    mappings: dict = field(default_factory=dict)
    content_digest: str = ""

    def to_dict(self) -> dict:
        """序列化为字典。"""
        return {
            "version": self.version,
            "field_contract_version": self.field_contract_version,
            "snapshot_id": self.snapshot_id,
            "source_time": self.source_time,
            "dictionaries": dict(self.dictionaries),
            "mappings": dict(self.mappings),
            "content_digest": self.content_digest,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TemplateSnapshot":
        """从字典反序列化。

        Args:
            data: 快照字典。

        Returns:
            TemplateSnapshot 实例。
        """
        data = data or {}
        return cls(
            version=str(data.get("version", "") or ""),
            field_contract_version=str(
                data.get("field_contract_version", "") or ""
            ),
            snapshot_id=str(data.get("snapshot_id", "") or ""),
            source_time=str(data.get("source_time", "") or ""),
            dictionaries=dict(data.get("dictionaries", {}) or {}),
            mappings=dict(data.get("mappings", {}) or {}),
            content_digest=str(data.get("content_digest", "") or ""),
        )


@dataclass
class TypeSheetSpec:
    """每设备类型的 sheet 与接口能力声明（design §2）。

    Attributes:
        sheet_name: 工作表名（如 ``监测点·XLBA``）。
        device_type: 中文设备类型名。
        device_type_id: 后端 deviceTypeId。
        is_gateway: 是否网关。
        interface_capabilities: 接口能力声明（itemId／协议号等）。
        fields: 工程列契约（顺序即列顺序）。
        derived_fields: 非列的派生字段契约（如 dsTypeId／deviceAddress）。
    """

    sheet_name: str = ""
    device_type: str = ""
    device_type_id: str = ""
    is_gateway: bool = False
    interface_capabilities: dict = field(default_factory=dict)
    fields: list[FieldSpec] = field(default_factory=list)
    derived_fields: list[FieldSpec] = field(default_factory=list)

    def field(self, field_key: str) -> FieldSpec | None:
        """按 field_key 查工程列或派生列契约。

        Args:
            field_key: 稳定字段键。

        Returns:
            命中的 FieldSpec；未命中返回 None。
        """
        for spec in list(self.fields) + list(self.derived_fields):
            if spec.field_key == field_key:
                return spec
        return None

    def headers(self) -> list[str]:
        """返回工程列中文表头（generator／reader 共用）。"""
        return [spec.header for spec in self.fields if spec.header]

    def unverified_fields(self) -> list[str]:
        """返回证据未核实的字段键（G1 门槛，不得进入可执行模板）。"""
        return [
            spec.field_key
            for spec in list(self.fields) + list(self.derived_fields)
            if spec.evidence is EvidenceStatus.UNVERIFIED
        ]

    def is_fully_verified(self) -> bool:
        """全部列（含派生）是否均已核实（G1 通过条件之一）。"""
        return not self.unverified_fields()

    def to_dict(self) -> dict:
        """序列化为字典。"""
        return {
            "sheet_name": self.sheet_name,
            "device_type": self.device_type,
            "device_type_id": self.device_type_id,
            "is_gateway": self.is_gateway,
            "interface_capabilities": dict(self.interface_capabilities),
            "fields": [spec.to_dict() for spec in self.fields],
            "derived_fields": [spec.to_dict() for spec in self.derived_fields],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TypeSheetSpec":
        """从字典反序列化。

        Args:
            data: sheet 声明字典。

        Returns:
            TypeSheetSpec 实例。
        """
        data = data or {}
        return cls(
            sheet_name=str(data.get("sheet_name", "") or ""),
            device_type=str(data.get("device_type", "") or ""),
            device_type_id=str(data.get("device_type_id", "") or ""),
            is_gateway=bool(data.get("is_gateway", False)),
            interface_capabilities=dict(
                data.get("interface_capabilities", {}) or {}
            ),
            fields=[
                FieldSpec.from_dict(x) for x in data.get("fields", []) or []
            ],
            derived_fields=[
                FieldSpec.from_dict(x)
                for x in data.get("derived_fields", []) or []
            ],
        )
