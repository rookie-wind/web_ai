"""设备时间域验证与只读结果补取控制。

design §8：使用本次网关时钟与请求耗时建立时间参考，
不直接与未同步的服务端时钟比较。诊断缺少可证明本次数据
的时间或关联证据时为 UNVERIFIED。

首版不猜异步补取端点；只有已核实的只读结果接口及关联键
可在任务联通时限内轮询。禁止轮询时重新发送下发命令。
"""

from __future__ import annotations

__all__ = [
    "TimeValidationResult",
    "validate_data_time",
    "check_item_id_contract",
    "sanitize_diagnostic_log",
]

from datetime import datetime, timezone


# 默认允许的最大时间漂移（秒）：5 分钟
DEFAULT_MAX_DRIFT_SECONDS = 300


class TimeValidationResult:
    """时间域验证结果。

    Attributes:
        valid: 数据时间是否在有效范围内。
        unverified: 时间参考不足，无法判定。
        reason: 不可读原因描述。
        data_time: 解析后的数据时间（若有）。
        reference_time: 参考时间（网关时钟）。
        drift_seconds: 实际漂移秒数。
    """

    def __init__(
        self,
        *,
        valid: bool = False,
        unverified: bool = False,
        reason: str = "",
        data_time: datetime | None = None,
        reference_time: datetime | None = None,
        drift_seconds: float = 0.0,
    ):
        """初始化验证结果。

        Args:
            valid: 数据时间有效。
            unverified: 时间参考不足。
            reason: 原因描述。
            data_time: 数据时间。
            reference_time: 参考时间。
            drift_seconds: 漂移秒数。
        """
        self.valid = valid
        self.unverified = unverified
        self.reason = reason
        self.data_time = data_time
        self.reference_time = reference_time
        self.drift_seconds = drift_seconds

    def to_dict(self) -> dict:
        """序列化为字典。"""
        return {
            "valid": self.valid,
            "unverified": self.unverified,
            "reason": self.reason,
            "data_time": (
                self.data_time.isoformat()
                if self.data_time else ""
            ),
            "reference_time": (
                self.reference_time.isoformat()
                if self.reference_time else ""
            ),
            "drift_seconds": self.drift_seconds,
        }


def validate_data_time(
    data_time_str: str,
    gateway_clock_str: str = "",
    request_elapsed: float = 0.0,
    max_drift_seconds: float = DEFAULT_MAX_DRIFT_SECONDS,
) -> TimeValidationResult:
    """验证数据时间是否在本次网关时钟参考范围内。

    使用本次网关时钟与请求耗时建立时间参考，不直接与
    未同步的服务端时钟比较。

    Args:
        data_time_str: 数据时间字符串（ISO 格式）。
        gateway_clock_str: 本次网关时钟时间（ISO 格式）。
        request_elapsed: 请求耗时（秒）。
        max_drift_seconds: 允许的最大时间漂移（秒）。

    Returns:
        时间验证结果。
    """
    # 解析数据时间
    try:
        data_time = datetime.fromisoformat(data_time_str)
        if data_time.tzinfo is None:
            data_time = data_time.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return TimeValidationResult(
            valid=False,
            reason=f"数据时间格式非法: {data_time_str}",
        )

    # 无网关时钟参考 → UNVERIFIED
    if not gateway_clock_str:
        return TimeValidationResult(
            valid=False,
            unverified=True,
            reason="缺少网关时钟时间参考，无法验证数据时效",
            data_time=data_time,
        )

    # 解析网关时钟
    try:
        ref_time = datetime.fromisoformat(gateway_clock_str)
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return TimeValidationResult(
            valid=False,
            unverified=True,
            reason=f"网关时钟格式非法: {gateway_clock_str}",
            data_time=data_time,
        )

    # 计算漂移（考虑请求耗时）
    drift = abs((data_time - ref_time).total_seconds())
    effective_window = max_drift_seconds + request_elapsed

    if drift > effective_window:
        return TimeValidationResult(
            valid=False,
            reason=(
                f"数据时间漂移 {drift:.0f}s "
                f"超出允许范围 {effective_window:.0f}s"
            ),
            data_time=data_time,
            reference_time=ref_time,
            drift_seconds=drift,
        )

    return TimeValidationResult(
        valid=True,
        data_time=data_time,
        reference_time=ref_time,
        drift_seconds=drift,
    )


def check_item_id_contract(
    resp_item_id: str,
    expected_item_id: str = "31800006",
) -> bool:
    """校验返回数据项是否符合契约声明。

    用于确认召测响应 itemId 等于运维契约项（当前实测为 31800006）。

    Args:
        resp_item_id: 响应中的 itemId。
        expected_item_id: 期望的 itemId。

    Returns:
        是否匹配。
    """
    return str(resp_item_id).strip() == str(expected_item_id).strip()


def sanitize_diagnostic_log(
    log_message: str,
) -> str:
    """脱敏诊断日志，保留 ERROR 关键词但不以此决定通信结果。

    design §8：保留混合端口日志供诊断，不用是否出现
    ERROR 词决定通信结果。

    Args:
        log_message: 原始日志消息。

    Returns:
        脱敏后的日志消息。
    """
    from archiving.log_sanitizer import sanitize_log_message
    return sanitize_log_message(log_message)
