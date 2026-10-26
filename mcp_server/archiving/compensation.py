"""XLPA 自动建档补偿清单记录与确认式清理。

主流程失败不自动回滚。执行写入时记录本次新建设备，用户明确确认后，
按叶子到父节点顺序调用 deleteDevice 清理，并回读设备树验证；绝不删除
补偿清单之外的既有设备。
"""

from __future__ import annotations

__all__ = [
    "CompensationRecorder",
    "apply_compensation",
    "DELETE_DEVICE_PATH",
    "GET_DEVICE_TREE_PATH",
]

from collections.abc import Callable

from archiving.models import CompensationEntry, CompensationPlan

# 边缘后端删除设备与读取设备树端点（来源 Path B 实测）
DELETE_DEVICE_PATH = "/devArchManager/doc/set/deleteDevice/v1"
GET_DEVICE_TREE_PATH = "/devArchManager/doc/get/getDeviceTree/v1"


class CompensationRecorder:
    """执行期补偿清单记录器：仅登记本次新建的设备。"""

    def __init__(self) -> None:
        """初始化空记录器。"""
        self.plan = CompensationPlan()

    def record_created(
        self,
        node_key: str,
        device_id: str,
        device_name: str,
        parent_device_id: str = "",
    ) -> CompensationEntry:
        """记录一个本次新建的设备。

        Args:
            node_key: 拓扑节点键。
            device_id: 后端返回的新建 deviceId。
            device_name: 设备名称。
            parent_device_id: 父设备 deviceId（用于叶子优先排序）。

        Returns:
            新增的补偿条目。
        """
        entry = CompensationEntry(
            node_key=node_key,
            device_id=str(device_id),
            device_name=device_name,
            parent_device_id=str(parent_device_id or ""),
            delete_payload={"deviceId": str(device_id)},
        )
        self.plan.add(entry)
        return entry

    @property
    def entries(self) -> list[CompensationEntry]:
        """当前记录的补偿条目列表。"""
        return self.plan.entries

    def to_dict(self) -> dict:
        """序列化补偿清单（含叶子优先删除顺序）。"""
        return self.plan.to_dict()


def _flatten_tree(nodes: list, out: dict) -> None:
    """递归展平设备树为 deviceId -> 节点字典。

    Args:
        nodes: 树节点列表。
        out: 输出映射。
    """
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        device_id = str(node.get("id") or node.get("deviceId") or "")
        if device_id:
            out[device_id] = node
        _flatten_tree(node.get("children") or [], out)


def apply_compensation(
    client,
    plan: CompensationPlan,
    *,
    confirm: bool = False,
    write_call: Callable[[str, dict], dict] | None = None,
) -> dict:
    """按补偿清单确认式删除本次新建设备。

    Args:
        client: 已登录的 EdgeDeviceClient（提供 ``call``）。
        plan: 补偿清单，仅含本次新建设备。
        confirm: 用户是否明确确认清理；未确认时不执行任何删除。
        write_call: 可选的写入审计回调，查询仍使用client。

    Returns:
        结构化结果字典：``ok``、``confirmed``、``deleted``、``failed``、
        ``remaining``、``out_of_scope_protected`` 与逐项 ``results``。
        ``remaining`` 为回读后仍存在的本次新建 deviceId（应为空）。
    """
    if not confirm:
        return {
            "ok": False,
            "confirmed": False,
            "deleted": [],
            "failed": [],
            "remaining": [e.device_id for e in plan.entries],
            "reason": "补偿清理需用户明确确认（confirm=true）后才执行",
            "results": [],
        }

    results: list[dict] = []
    deleted: list[str] = []
    failed: list[str] = []
    # 叶子到父节点顺序删除
    for entry in plan.delete_order():
        call = write_call or client.call
        resp = call(DELETE_DEVICE_PATH, dict(entry.delete_payload))
        ok = bool(resp.get("ok"))
        results.append(
            {
                "node_key": entry.node_key,
                "device_id": entry.device_id,
                "device_name": entry.device_name,
                "ok": ok,
                "rtnCode": resp.get("rtnCode"),
                "rtnMsg": resp.get("rtnMsg", ""),
            }
        )
        if ok:
            deleted.append(entry.device_id)
        else:
            failed.append(entry.device_id)
            break

    # 回读设备树验证本次新建设备已消失，且不清理清单外设备
    remaining: list[str] = []
    tree_resp = client.call(GET_DEVICE_TREE_PATH, {})
    readback_verified = bool(tree_resp.get("ok")) and isinstance(tree_resp.get("data"), list)
    if readback_verified:
        flat: dict[str, dict] = {}
        _flatten_tree(tree_resp.get("data") or [], flat)
        scope_ids = {e.device_id for e in plan.entries}
        remaining = [did for did in scope_ids if did in flat]
        # 清单外设备始终保留，不参与删除
        out_of_scope = [did for did in flat if did not in scope_ids]
    else:
        out_of_scope = []

    return {
        "ok": readback_verified and not failed and not remaining,
        "readback_verified": readback_verified,
        "confirmed": True,
        "deleted": deleted,
        "failed": failed,
        "remaining": remaining,
        "out_of_scope_protected_count": len(out_of_scope),
        "results": results,
    }
