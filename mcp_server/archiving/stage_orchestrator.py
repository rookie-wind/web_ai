"""阶段依赖编排与汇总。

完整编排顺序为建档／挂载／全字段回读 → 参数保存回读 → 网关时钟 →
``20200002`` 批量下发 → 逐监测点 ``31800006`` 召测。每阶段分别
记录，依赖阶段未成功则后续阻止。单独诊断需独立确认目标范围，
不计入完整流程验收。

阶段状态：
  - NOT_RUN: 未执行。
  - BLOCKED: 被前置阶段阻止。
  - SUCCEEDED: 成功。
  - FAILED: 失败。
  - UNVERIFIED: 结果未验证（超时、仅受理等）。
"""

from __future__ import annotations

__all__ = [
    "StageState",
    "StageRecord",
    "StageOrchestrator",
]

from enum import Enum


class StageState(str, Enum):
    """阶段状态枚举。"""

    NOT_RUN = "NOT_RUN"
    BLOCKED = "BLOCKED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNVERIFIED = "UNVERIFIED"


class StageRecord:
    """单阶段执行记录。

    Attributes:
        stage_name: 阶段名称。
        state: 阶段状态。
        reason: 状态原因（若有）。
        detail: 详细结果（若有）。
        gateway_key: 关联网关（若有）。
    """

    def __init__(
        self,
        stage_name: str,
        state: StageState = StageState.NOT_RUN,
        reason: str = "",
        detail: dict | None = None,
        gateway_key: str = "",
    ):
        """初始化阶段记录。

        Args:
            stage_name: 阶段名称。
            state: 初始状态。
            reason: 状态原因。
            detail: 详细结果。
            gateway_key: 关联网关。
        """
        self.stage_name = stage_name
        self.state = state
        self.reason = reason
        self.detail = detail or {}
        self.gateway_key = gateway_key

    def to_dict(self) -> dict:
        """序列化为字典。"""
        return {
            "stage_name": self.stage_name,
            "state": self.state.value,
            "reason": self.reason,
            "detail": dict(self.detail),
            "gateway_key": self.gateway_key,
        }


# 阶段依赖声明：key → 前置阶段列表
_STAGE_DEPENDENCIES: dict[str, list[str]] = {
    "archive_read": [],
    "parameter_save": ["archive_read"],
    "gateway_clock": ["archive_read", "parameter_save"],
    "param_deploy": ["gateway_clock", "archive_read", "parameter_save"],
    "monitor_debug": ["param_deploy", "archive_read", "parameter_save"],
}


class StageOrchestrator:
    """阶段依赖编排器。

    管理阶段状态与依赖检查，确保前置阶段成功后才执行后续阶段。
    单独诊断不计入全链路汇总。
    """

    def __init__(self, required_stages: tuple[str, ...] | None = None) -> None:
        """初始化编排器，并明确该目标的适用阶段。"""
        self.required_stages = (
            tuple(_STAGE_DEPENDENCIES) if required_stages is None else required_stages
        )
        self.records: dict[str, StageRecord] = {}
        self._standalone_diagnostic: bool = False

    def record_stage(
        self,
        stage_name: str,
        state: StageState,
        reason: str = "",
        detail: dict | None = None,
        gateway_key: str = "",
    ) -> StageRecord:
        """记录阶段结果。

        Args:
            stage_name: 阶段名称。
            state: 阶段状态。
            reason: 原因描述。
            detail: 详细结果。
            gateway_key: 关联网关。

        Returns:
            阶段记录。
        """
        record = StageRecord(
            stage_name=stage_name,
            state=state,
            reason=reason,
            detail=detail,
            gateway_key=gateway_key,
        )
        self.records[stage_name] = record
        return record

    def can_execute(self, stage_name: str) -> tuple[bool, str]:
        """检查阶段是否可以执行。

        前置阶段必须为 SUCCEEDED，否则当前阶段被阻止。

        Args:
            stage_name: 阶段名称。

        Returns:
            ``(可执行, 原因)`` 二元组。
        """
        deps = _STAGE_DEPENDENCIES.get(stage_name, [])
        for dep in deps:
            dep_record = self.records.get(dep)
            if dep_record is None:
                return False, (
                    f"前置阶段 {dep} 未执行"
                )
            if dep_record.state == StageState.BLOCKED:
                return False, (
                    f"前置阶段 {dep} 被阻止: "
                    f"{dep_record.reason}"
                )
            if dep_record.state == StageState.UNVERIFIED:
                return False, (
                    f"前置阶段 {dep} 未验证: "
                    f"{dep_record.reason}"
                )
            if dep_record.state == StageState.FAILED:
                return False, (
                    f"前置阶段 {dep} 失败: "
                    f"{dep_record.reason}"
                )
            if dep_record.state != StageState.SUCCEEDED:
                return False, (
                    f"前置阶段 {dep} 状态为 "
                    f"{dep_record.state.value}"
                )
        return True, ""

    def mark_standalone_diagnostic(self) -> None:
        """标记为单独诊断模式。

        单独诊断不计入全链路汇总，不补做未授权前序写入。
        """
        self._standalone_diagnostic = True

    @property
    def is_standalone_diagnostic(self) -> bool:
        """是否为单独诊断模式。"""
        return self._standalone_diagnostic

    def summary(self) -> dict:
        """生成阶段汇总。

        Returns:
            汇总字典，含各阶段状态、整体结论和是否全链路。
        """
        stages = {
            name: self.records.get(
                name, StageRecord(name, reason="尚无执行回执"),
            ).to_dict()
            for name in dict.fromkeys((*self.required_stages, *self.records))
        }
        # 缺少任一适用阶段都不能凭局部成功判定完整成功。
        all_succeeded = bool(self.required_stages) and all(
            stages[name]["state"] == StageState.SUCCEEDED.value
            for name in self.required_stages
        )
        has_blocked = any(
            rec.state == StageState.BLOCKED
            for rec in self.records.values()
        )
        has_unverified = any(
            rec.state == StageState.UNVERIFIED
            for rec in self.records.values()
        )
        has_failed = any(
            rec.state == StageState.FAILED
            for rec in self.records.values()
        )

        if self._standalone_diagnostic:
            overall = "STANDALONE_DIAGNOSTIC"
        elif has_blocked:
            overall = "BLOCKED"
        elif has_unverified:
            overall = "UNVERIFIED"
        elif has_failed:
            overall = "FAILED"
        elif all_succeeded and stages:
            overall = "SUCCEEDED"
        else:
            overall = "NOT_RUN"

        return {
            "stages": stages,
            "overall": overall,
            "is_full_chain": overall == "SUCCEEDED",
            "stage_count": len(stages),
        }

    def old_call_excluded(self) -> dict:
        """声明旧 callDeviceData 不计入新链路证据。

        Returns:
            排除声明字典。
        """
        return {
            "excluded": True,
            "reason": (
                "旧 edge_call_device_data 使用 callDeviceData，"
                "不等于 31800006 运维契约，不计入新链路通信证据"
            ),
            "new_evidence_item": "31800006",
        }
