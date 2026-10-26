"""XLPA 自动建档引擎：拓扑排序、幂等匹配与 dry-run 计划生成。

引擎为纯逻辑，不做 I/O：输入解析后的 ``ArchiveTemplate`` 与从边缘后端
读取的现有设备索引，输出 ``DryRunPlan``。写入与联通由 Skill 编排原子
工具执行，引擎只负责「计划什么、为什么」。

幂等匹配以设备名称为键：
  - 网关：按名称回查，基本字段有差异则 UPDATE，否则 SKIP；参数项另行保存。
  - 监测点：按 ``设备名称``（全局唯一）回查，命中则需要用户确认后
    按模板修改参数（UPDATE）；未命中 → CREATE。
  - 未命中 → CREATE。``deviceId`` 由后端回填，仅用于展示与下发复用。
  - 同一网关下 ``分路号``/``测量点号`` 唯一，跨网关允许重复；编号冲突阻断。
  - 命中但挂载网关与后端父级不一致 → 保持现状仅告警，绝不挪动。
"""

from __future__ import annotations

__all__ = [
    "ExistingDevice",
    "build_existing_index",
    "topological_order",
    "build_plan",
    "ExecutionLockManager",
    "revalidate_plan",
]

from dataclasses import dataclass, field
import threading
import time
import uuid

from .excel_reader import ArchiveTemplate
from .models import (
    DryRunItem,
    DryRunPlan,
    PlanAction,
    TopologyNode,
)
from .profiles.registry import ProfileRegistry, default_registry


@dataclass
class ExistingDevice:
    """边缘后端现有设备档案摘要。"""

    device_id: str = ""
    name: str = ""
    device_type_id: str = ""
    parent_id: str = ""
    address: str = ""
    identifier: str = ""
    proxy_comm_type: str = ""
    road_no: str = ""
    raw: dict = field(default_factory=dict)


def _norm_road_no(value) -> str:
    """将分路号归一化为整数字符串，非数字返回去空白原值。

    Args:
        value: 后端或模板中的分路号原值。

    Returns:
        归一化后的分路号字符串；空值返回空串。
    """
    text = str(value if value is not None else "").strip()
    if not text:
        return ""
    try:
        return str(int(float(text)))
    except (TypeError, ValueError):
        return text


def build_existing_index(devices: list[dict]) -> dict[str, ExistingDevice]:
    """将后端设备档案列表构建为 deviceId -> ExistingDevice 索引。

    Args:
        devices: getDeviceTree / getDeviceList 展平后的设备字典列表。

    Returns:
        deviceId 到 ExistingDevice 的映射。
    """
    index: dict[str, ExistingDevice] = {}
    for row in devices:
        if not isinstance(row, dict):
            continue
        device_id = str(row.get("deviceId") or row.get("id") or "").strip()
        if not device_id:
            continue
        index[device_id] = ExistingDevice(
            device_id=device_id,
            name=str(row.get("deviceName") or row.get("name") or ""),
            device_type_id=str(row.get("deviceTypeId") or ""),
            parent_id=str(row.get("pid") or row.get("parentId") or ""),
            address=str(row.get("deviceAddress") or ""),
            identifier=str(row.get("identifier") or "").strip(),
            proxy_comm_type=str(row.get("proxyCommType") or ""),
            road_no=_norm_road_no(row.get("roadNo") or row.get("agentNum")),
            raw=row,
        )
    return index


def topological_order(nodes: list[TopologyNode]) -> tuple[list[TopologyNode], list[str]]:
    """按父节点键拓扑排序，父节点先于子节点。

    Args:
        nodes: 拓扑节点列表。

    Returns:
        二元组 ``(排序后节点, 错误列表)``；存在环或父节点缺失时记录错误。
    """
    errors: list[str] = []
    by_key = {node.node_key: node for node in nodes if node.node_key}
    ordered: list[TopologyNode] = []
    visited: set[str] = set()
    visiting: set[str] = set()

    def visit(node: TopologyNode) -> None:
        if node.node_key in visited:
            return
        if node.node_key in visiting:
            errors.append(f"拓扑存在环，涉及节点键 {node.node_key}")
            return
        visiting.add(node.node_key)
        if node.parent_key:
            parent = by_key.get(node.parent_key)
            if parent is None:
                errors.append(
                    f"节点 {node.node_key} 的父节点键 {node.parent_key} 未在拓扑总览中定义"
                )
            else:
                visit(parent)
        visiting.discard(node.node_key)
        visited.add(node.node_key)
        ordered.append(node)

    for node in nodes:
        visit(node)
    return ordered, errors


def _collect_subtree_meters(
    gateway_key: str,
    child_map: dict[str, list[str]],
    deployable_meter_keys: set[str],
) -> set[str]:
    """收集某网关整棵子树下所有可下发电表（不含网关，多级递归）。

    遍历时仅保留属于 ``deployable_meter_keys`` 的节点（CREATE/SKIP 电表），
    从子树中收集所有此类电表键；网关节点只作为中间跳板、不入结果。

    Args:
        gateway_key: 网关节点键。
        child_map: parent_key -> [child_key,...] 子级映射。
        deployable_meter_keys: 本次可下发（CREATE/SKIP）的电表键集合。

    Returns:
        子树下可下发电表的 node_key 集合。
    """
    result: set[str] = set()
    stack = [gateway_key]
    visited: set[str] = set()
    while stack:
        cur = stack.pop()
        if cur in visited:
            continue
        visited.add(cur)
        for child in child_map.get(cur, []):
            if child in deployable_meter_keys:
                result.add(child)
            else:
                # 网关（或暂未区分）作为中间跳板继续向下
                stack.append(child)
    return result


def _build_name_indexes(
    existing_index: dict[str, ExistingDevice],
) -> tuple[
    dict[str, list[ExistingDevice]],
    dict[tuple[str, str], list[ExistingDevice]],
    dict[tuple[str, str], list[ExistingDevice]],
]:
    """从 deviceId 索引构造名称回查 + 网关内编号二级索引（候选集合模式）。

    design §7：身份索引保留候选列表，多个后端候选即冲突。名称驱动下：
      - by_name: 设备名称 -> 候选设备列表（网关与监测点均按名称去重，全局唯一）。
      - by_gw_road: (parent_id, 分路号) -> 候选设备（同网关内分路号唯一）。
      - by_gw_measur: (parent_id, 测量点号) -> 候选设备（同网关内测量点号唯一）。
    跨网关分路号/测量点号重复允许。

    Args:
        existing_index: build_existing_index 返回的 deviceId 索引。

    Returns:
        二元组 ``(by_name, by_gw_road, by_gw_measur)``。
    """
    by_name: dict[str, list[ExistingDevice]] = {}
    by_gw_road: dict[tuple[str, str], list[ExistingDevice]] = {}
    by_gw_measur: dict[tuple[str, str], list[ExistingDevice]] = {}
    for dev in existing_index.values():
        name = (dev.name or "").strip()
        if name:
            by_name.setdefault(name, []).append(dev)
        parent_id = (dev.parent_id or "").strip()
        if not parent_id:
            continue
        road_no = _norm_road_no(dev.road_no)
        if road_no:
            by_gw_road.setdefault((parent_id, road_no), []).append(dev)
        measur_no = str(dev.raw.get("measuredPointNum") or "").strip()
        if measur_no:
            by_gw_measur.setdefault((parent_id, measur_no), []).append(dev)
    return by_name, by_gw_road, by_gw_measur


def build_plan(
    template: ArchiveTemplate,
    existing_index: dict[str, ExistingDevice] | None = None,
    registry: ProfileRegistry | None = None,
) -> DryRunPlan:
    """基于模板与现有设备索引生成 dry-run 计划。

    Args:
        template: 解析后的任务模板。
        existing_index: deviceId -> ExistingDevice；首跑可为空。
        registry: profile 注册表，默认用全局注册表。

    Returns:
        DryRunPlan，含逐项动作、冲突、下发/召测计划标志与提示。
    """
    registry = registry or default_registry
    existing_index = existing_index or {}
    plan = DryRunPlan()
    plan.plan_id = uuid.uuid4().hex[:12]

    def _is_gateway_node(node: TopologyNode) -> bool:
        """按 profile 判定节点是否为网关。"""
        profile, _ = registry.resolve(node.device_type, "")
        return bool(profile and getattr(profile, "is_gateway", False))

    # 模板解析错误直接汇入计划错误
    for err in template.errors:
        plan.warnings.append(f"模板错误: {err}")

    # 防御性检查：确保节点键唯一性（解析器应已保证，此处作为安全网）
    node_keys = [node.node_key for node in template.nodes if node.node_key]
    if len(node_keys) != len(set(node_keys)):
        duplicates = [
            key for key in node_keys if node_keys.count(key) > 1
        ]
        plan.warnings.append(
            f"拓扑节点键重复: {', '.join(set(duplicates))}，"
            f"请检查挂载关系表"
        )

    ordered, topo_errors = topological_order(template.nodes)
    for err in topo_errors:
        plan.warnings.append(err)

    gateway_details = template.gateway_details
    meter_details = template.meter_details
    task_config = template.task_config

    # 名称回查索引 + 网关内编号索引（design §7：同网关内编号重复即冲突）
    by_name, by_gw_road, by_gw_measur = _build_name_indexes(existing_index)
    backfilled: dict[str, str] = plan.node_key_to_device_id

    # 任务内去重键重复检测：网关与监测点均按设备名称（全局唯一）
    seen_task_keys: set[str] = set()
    for node in ordered:
        if not node.device_name:
            continue
        task_key = node.device_name
        if task_key in seen_task_keys:
            plan.warnings.append(f"任务内去重键重复: {task_key}，请检查挂载/监测点")
        seen_task_keys.add(task_key)

    # 记录每个节点的 profile 结果，供下发/召测计划判断
    link_blocked_gateways: set[str] = set()
    meter_count = 0
    gateway_count = 0

    for node in ordered:
        profile, lookup_err = registry.resolve(node.device_type, "")
        if lookup_err and (profile is None or not getattr(profile, "supported", True)):
            item = DryRunItem(
                node_key=node.node_key,
                action=PlanAction.CONFLICT,
                device_type=node.device_type,
                device_id=node.device_id,
                road_no=node.road_no,
                reason=lookup_err,
            )
            plan.items.append(item)
            plan.conflicts.append(item)
            continue

        detail = {}
        if profile.is_gateway:
            detail = gateway_details.get(node.node_key, {})
            gateway_count += 1
        else:
            # 非网关即监测点：明细照常加载（下发/召测为通用能力）
            detail = meter_details.get(node.node_key, {})
            meter_count += 1

        resolved = profile.resolve(node, task_config, detail)
        for warn in resolved.warnings:
            plan.warnings.append(warn)
        # dry-run 展示 payload：base_payload + extInfos（审阅将写入的完整档案）
        display_payload = dict(resolved.base_payload)
        if resolved.ext_infos:
            display_payload["extInfos"] = [
                {"propertyCode": k, "propertyValue": v}
                for k, v in resolved.ext_infos.items()
            ]

        if resolved.errors:
            item = DryRunItem(
                node_key=node.node_key,
                action=PlanAction.CONFLICT,
                device_type=node.device_type,
                device_id=node.device_id,
                road_no=node.road_no,
                reason="；".join(resolved.errors),
                payload=display_payload,
                # profile 字段级错误（个别目标已填值非法/映射不上）：
                # 进 conflicts 供展示，但不连坐整批（structural=False）。
                structural=False,
            )
            plan.items.append(item)
            plan.conflicts.append(item)
            if profile.is_gateway and resolved.link_blocked:
                link_blocked_gateways.add(node.node_key)
            continue

        if profile.is_gateway and resolved.link_blocked:
            link_blocked_gateways.add(node.node_key)

        # ── 幂等判定：按名称回查（网关与监测点均按全局唯一设备名称）──
        parent_device_id = ""
        if node.parent_key:
            parent_node = next(
                (n for n in ordered if n.node_key == node.parent_key), None
            )
            if parent_node is not None:
                parent_device_id = (
                    backfilled.get(parent_node.node_key) or parent_node.device_id
                )

        matched_key = f"名称 {node.device_name}"
        if not node.device_name:
            item = DryRunItem(
                node_key=node.node_key,
                action=PlanAction.CONFLICT,
                device_type=node.device_type,
                road_no=node.road_no,
                reason="缺少设备名称，拒绝静默新建",
                payload=display_payload,
            )
            plan.items.append(item)
            plan.conflicts.append(item)
            continue

        candidates = by_name.get(node.device_name, [])

        # design §7：多个后端候选即冲突
        if len(candidates) > 1:
            candidate_ids = [c.device_id for c in candidates]
            item = DryRunItem(
                node_key=node.node_key,
                action=PlanAction.CONFLICT,
                device_type=node.device_type,
                road_no=node.road_no,
                reason=(
                    f"按 {matched_key} 回查发现 {len(candidates)} 个候选设备"
                    f"（{', '.join(candidate_ids)}），身份冲突，拒绝静默选择"
                ),
                payload=display_payload,
            )
            plan.items.append(item)
            plan.conflicts.append(item)
            continue

        existing = candidates[0] if candidates else None
        if existing and existing.device_type_id != profile.device_type_id:
            item = DryRunItem(
                node_key=node.node_key, action=PlanAction.CONFLICT,
                device_type=node.device_type, device_id=existing.device_id,
                reason="同名设备类型与模板不符，禁止覆盖", payload=display_payload,
            )
            plan.items.append(item)
            plan.conflicts.append(item)
            continue

        # design §7：网关内编号冲突检查（同网关内 road_no/measured_point_no 重复）
        if not profile.is_gateway and parent_device_id:
            norm_road = _norm_road_no(node.road_no)
            if norm_road:
                road_candidates = by_gw_road.get(
                    (parent_device_id, norm_road), []
                )
                # 过滤掉自身匹配（按名称）
                road_conflicts = [
                    c for c in road_candidates
                    if (c.name or "").strip() != node.device_name
                ]
                if road_conflicts:
                    conflict_ids = [c.device_id for c in road_conflicts]
                    item = DryRunItem(
                        node_key=node.node_key,
                        action=PlanAction.CONFLICT,
                        device_type=node.device_type,
                        road_no=node.road_no,
                        reason=(
                            f"分路号 {norm_road} 在同网关 {parent_device_id} "
                            f"下与现有设备（{', '.join(conflict_ids)}）冲突"
                        ),
                        payload=display_payload,
                    )
                    plan.items.append(item)
                    plan.conflicts.append(item)
                    continue
            # 测量点号冲突检查
            measur_no = str(resolved.base_payload.get("measuredPointNum", "")).strip()
            if measur_no:
                measur_candidates = by_gw_measur.get(
                    (parent_device_id, measur_no), []
                )
                measur_conflicts = [
                    c for c in measur_candidates
                    if (c.name or "").strip() != node.device_name
                ]
                if measur_conflicts:
                    conflict_ids = [c.device_id for c in measur_conflicts]
                    item = DryRunItem(
                        node_key=node.node_key,
                        action=PlanAction.CONFLICT,
                        device_type=node.device_type,
                        road_no=node.road_no,
                        reason=(
                            f"测量点号 {measur_no} 在同网关 {parent_device_id} "
                            f"下与现有设备（{', '.join(conflict_ids)}）冲突"
                        ),
                        payload=display_payload,
                    )
                    plan.items.append(item)
                    plan.conflicts.append(item)
                    continue

        if existing is not None:
            backfilled[node.node_key] = existing.device_id
            if (
                parent_device_id
                and existing.parent_id
                and parent_device_id != existing.parent_id
            ):
                plan.warnings.append(
                    f"节点 {node.node_key} 的挂载网关与后端父级不一致，"
                    "保持实际父级不挪动；参数与通信验收须先确认归属"
                )
            if profile.is_gateway:
                expected = {
                    key: str(value) for key, value in resolved.base_payload.items()
                    if key not in ("deviceId", "commAddrRepetition")
                    and value is not None and value != ""
                }
                current = dict(existing.raw)
                current.update(
                    deviceName=existing.name, deviceTypeId=existing.device_type_id,
                    deviceAddress=existing.address, identifier=existing.identifier,
                    proxyCommType=existing.proxy_comm_type,
                )
                differences = [
                    key for key, value in expected.items() if str(current.get(key)) != value
                ]
                action = PlanAction.UPDATE if differences else PlanAction.SKIP
                reason = (
                    f"按 {matched_key} 命中网关；基本字段需确认修正: {', '.join(differences)}"
                    if differences else f"按 {matched_key} 命中网关，基本档案一致，另行校验参数项"
                )
            else:
                # design §2：监测点已存在 → 确认后按模板修改参数（UPDATE）
                action = PlanAction.UPDATE
                reason = (
                    f"按 {matched_key} 回查命中现有监测点，"
                    "需用户确认后按模板修改参数"
                )
            plan.items.append(
                DryRunItem(
                    node_key=node.node_key,
                    action=action,
                    device_type=node.device_type,
                    device_id=existing.device_id,
                    parent_device_id=existing.parent_id or parent_device_id,
                    road_no=node.road_no,
                    reason=reason,
                    payload=display_payload,
                )
            )
        else:
            plan.items.append(
                DryRunItem(
                    node_key=node.node_key,
                    action=PlanAction.CREATE,
                    device_type=node.device_type,
                    device_id="",
                    parent_device_id=parent_device_id,
                    road_no=node.road_no,
                    reason=f"按 {matched_key} 回查未命中，新建",
                    payload=display_payload,
                )
            )

    # ── 下发 / 召测计划（与建档解耦：SKIP 的监测点仍纳入下发）──
    # meter_count 同时统计 CREATE 与 SKIP 节点，其 deviceId 已回填到
    # plan.node_key_to_device_id，故建档被跳过的监测点仍可下发抄表参数。
    # 默认规划下发与召测（不再受 task_config.allow_* 门禁；执行阶段单独确认）。
    deploy_allowed = meter_count > 0
    if deploy_allowed and link_blocked_gateways:
        plan.warnings.append(
            "存在缺少 proxyCommType 的网关，其子树下发/召测可能因无法联通而失败，"
            "仅告警不阻断: " + ", ".join(sorted(link_blocked_gateways))
        )
    # 联通前置缺失不再阻断规划：有监测点即规划下发/召测（D3，仅 warnings 提示）。
    plan.deploy_planned = deploy_allowed
    plan.poll_planned = True
    if deploy_allowed:
        plan.warnings.append("下发/召测默认规划，执行前需用户确认")

    # ── design §6：绑定摘要、字段来源、批次清单与前置条件 ──
    # 可执行性：仅结构性冲突阻断。字段级 profile 错误（structural=False）
    # 只使该目标写入失败，不连坐整批（详见 D7）。
    structural_conflicts = [
        c for c in plan.conflicts if c.structural
    ] + [
        it for it in plan.items
        if it.action == PlanAction.CONFLICT and it.structural
    ]
    plan.executable = (
        not structural_conflicts
        and not template.errors
        and not topo_errors
    )

    # 绑定摘要：每个节点的父级信息
    node_by_key = {n.node_key: n for n in ordered}
    for item in plan.items:
        nk = item.node_key
        node = node_by_key.get(nk)
        if node is None:
            continue
        parent_device_id = item.parent_device_id or ""
        parent_barcode = ""
        if node.parent_key:
            parent_barcode = node.parent_key
        plan.binding_summary[nk] = {
            "parent_key": node.parent_key or "",
            "parent_device_id": parent_device_id,
            "parent_barcode": parent_barcode,
        }

    # 字段来源：从 payload 提取来源标记
    for item in plan.items:
        sources: dict[str, str] = {}
        payload = item.payload or {}
        for key, val in payload.items():
            if key == "extInfos":
                continue
            if val != "" and val is not None:
                sources[key] = "engineer_input"
            else:
                sources[key] = "empty"
        if payload.get("extInfos"):
            for ext in payload["extInfos"]:
                code = ext.get("propertyCode", "")
                if code:
                    sources[f"ext.{code}"] = "engineer_input"
        plan.field_sources[item.node_key] = sources

    # 新建批次清单（按拓扑顺序，网关先于子节点）
    current_batch: list[str] = []
    for item in plan.items:
        if item.action == PlanAction.CREATE:
            current_batch.append(item.node_key)
    if current_batch:
        plan.create_batches.append(current_batch)

    # 下发批次清单（按网关分组；每网关收集其整棵子树下所有监测点，含多级）
    if plan.deploy_planned:
        # 本次可下发监测点：全部 CREATE/SKIP/UPDATE 的非网关节点。
        # 下发与建档解耦：命中已存在设备的监测点（SKIP/UPDATE）仍纳入范围。
        deployable_meter_keys: set[str] = set()
        for it in plan.items:
            if it.action not in (
                PlanAction.CREATE, PlanAction.SKIP, PlanAction.UPDATE,
            ):
                continue
            n = node_by_key.get(it.node_key)
            if n is None or _is_gateway_node(n):
                continue
            deployable_meter_keys.add(it.node_key)
        child_map: dict[str, list[str]] = {}
        for n in template.nodes:
            if n.parent_key:
                child_map.setdefault(n.parent_key, []).append(n.node_key)
        for n in template.nodes:
            if not _is_gateway_node(n):
                continue
            subtree = _collect_subtree_meters(
                n.node_key, child_map, deployable_meter_keys
            )
            if not subtree:
                continue
            gw_device_id = backfilled.get(n.node_key, n.node_key)
            plan.deploy_batches.append({
                "gateway_key": n.node_key,
                "gateway_device_id": gw_device_id,
                "meter_keys": sorted(subtree),
            })

    # 阶段前置条件
    if plan.create_batches:
        plan.preconditions.append(
            "建档阶段：全部 CREATE 节点按拓扑顺序完成"
        )
    if plan.deploy_planned:
        plan.preconditions.append(
            "下发阶段：建档完成且全部监测点 deviceId 已回填"
        )
    if plan.poll_planned:
        plan.preconditions.append(
            "召测阶段：下发完成且参数已写入"
        )
    if not plan.executable:
        plan.preconditions.append(
            "计划存在冲突或模板错误，禁止执行"
        )

    return plan


class ExecutionLockManager:
    """任务与网关级执行锁管理器。

    design §7：任务内和同一目标网关进程内锁减少并发竞争。
    外部客户端仍可竞争，靠执行前/写后回查发现。
    """

    def __init__(self) -> None:
        """初始化锁管理器。"""
        self._task_locks: dict[str, float] = {}
        self._gateway_locks: dict[str, str] = {}
        self._mutex = threading.Lock()

    def acquire_task(self, task_id: str, ttl: float = 7200.0) -> bool:
        """获取任务级锁。

        Args:
            task_id: 任务唯一标识。
            ttl: 锁有效期（秒），默认 2 小时。

        Returns:
            成功获取返回 True；已被锁定返回 False。
        """
        with self._mutex:
            now = time.time()
            existing = self._task_locks.get(task_id)
            if existing is not None and now < existing:
                return False
            self._task_locks[task_id] = now + ttl
            return True

    def release_task(self, task_id: str) -> None:
        """释放任务级锁。

        Args:
            task_id: 任务唯一标识。
        """
        with self._mutex:
            self._task_locks.pop(task_id, None)

    def acquire_gateway(self, gateway_key: str, task_id: str) -> bool:
        """获取网关级锁。

        Args:
            gateway_key: 网关节点键或 deviceId。
            task_id: 持有锁的任务 ID。

        Returns:
            成功获取返回 True；已被其他任务锁定返回 False。
        """
        with self._mutex:
            holder = self._gateway_locks.get(gateway_key)
            if holder is not None and holder != task_id:
                return False
            self._gateway_locks[gateway_key] = task_id
            return True

    def release_gateway(self, gateway_key: str) -> None:
        """释放网关级锁。

        Args:
            gateway_key: 网关节点键或 deviceId。
        """
        with self._mutex:
            self._gateway_locks.pop(gateway_key, None)

    def is_task_locked(self, task_id: str) -> bool:
        """检查任务是否被锁定。

        Args:
            task_id: 任务唯一标识。

        Returns:
            锁定中返回 True。
        """
        with self._mutex:
            expiry = self._task_locks.get(task_id)
            if expiry is None:
                return False
            return time.time() < expiry

    def get_gateway_holder(self, gateway_key: str) -> str:
        """获取网关锁持有者。

        Args:
            gateway_key: 网关节点键或 deviceId。

        Returns:
            持有者任务 ID；未锁定返回空串。
        """
        with self._mutex:
            return self._gateway_locks.get(gateway_key, "")


def revalidate_plan(
    plan: DryRunPlan,
    current_index: dict[str, ExistingDevice],
) -> tuple[bool, list[str]]:
    """执行前重新验证计划有效性。

    design §7：写前重新读取身份和编号占用；外部变更使计划失效则停止。

    Args:
        plan: 已生成的 dry-run 计划。
        current_index: 当前后端设备索引（执行前重新读取）。

    Returns:
        二元组 ``(valid, reasons)``：
          - valid: 计划是否仍然有效。
          - reasons: 失效原因列表。
    """
    reasons: list[str] = []

    # 重新构建名称 + 网关内编号索引
    by_name, by_gw_road, by_gw_measur = _build_name_indexes(current_index)

    for item in plan.items:
        if item.action == PlanAction.CONFLICT:
            continue

        node_key = item.node_key
        # 检查名称身份是否被占用
        if item.action == PlanAction.CREATE:
            candidates = by_name.get(node_key, [])
            if candidates:
                # 名称已被其他设备占用
                existing_ids = [c.device_id for c in candidates]
                reasons.append(
                    f"节点 {node_key} 计划 CREATE，但设备名称已被占用"
                    f"（{', '.join(existing_ids)}）"
                )
        elif item.action in (PlanAction.SKIP, PlanAction.UPDATE):
            # 检查原命中设备是否仍存在
            expected_id = item.device_id
            if expected_id and expected_id not in current_index:
                reasons.append(
                    f"节点 {node_key} 计划 SKIP，但原设备 {expected_id} "
                    "已不存在于后端"
                )
            # 检查父级是否变化
            binding = plan.binding_summary.get(node_key, {})
            expected_parent = binding.get("parent_device_id", "")
            if expected_id and expected_id in current_index:
                current_parent = current_index[expected_id].parent_id
                if (
                    expected_parent
                    and current_parent
                    and expected_parent != current_parent
                ):
                    reasons.append(
                        f"节点 {node_key} 的父级已变化"
                        f"（计划: {expected_parent}, 当前: {current_parent}）"
                    )

    # 检查编号占用（对 CREATE 节点）
    for item in plan.items:
        if item.action != PlanAction.CREATE:
            continue
        node_key = item.node_key
        binding = plan.binding_summary.get(node_key, {})
        parent_id = binding.get("parent_device_id", "")
        if not parent_id:
            continue
        # 检查分路号
        road_no = item.road_no
        if road_no:
            norm_road = _norm_road_no(road_no)
            conflicts = by_gw_road.get((parent_id, norm_road), [])
            if conflicts:
                conflict_ids = [c.device_id for c in conflicts]
                reasons.append(
                    f"节点 {node_key} 分路号 {norm_road} "
                    f"在同网关下已被占用（{', '.join(conflict_ids)}）"
                )

    valid = len(reasons) == 0
    return valid, reasons
