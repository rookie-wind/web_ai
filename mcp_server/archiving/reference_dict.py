"""参考字典标准化、分页、作用域关联与同名异码检测（阶段一取数）。

在 :mod:`reference_provider` 的原始读取链之上，把五类字典标准化为带来源、
作用域、名称、码值和获取时间的 :class:`DictRecord`，并落实 design §1：

- **完整分页**：云端各适配器显式处理总数、分页与结束条件，检测重复页与截断。
- **作用域关联**：型号按 ``brandId`` 归属品牌；接口内部 ID 仅用于关联，
  不替代业务码（品牌 ``code``、型号 ``modelCode``）。
- **同名异码检测**：同一作用域内同名却对应多个码值即判冲突；跨品牌同名
  属不同作用域，合法。
- **全有或全无**：任一来源失败即 :class:`DictCollectionError`，返回具体来源，
  不以部分字典或历史缓存降级。

四串口项与抄表间隔是协议固定枚举（见 field_contract），**不属**参考字典，
边缘 ``getDictItemList`` 对其返回空已实测确认。
"""

from __future__ import annotations

__all__ = [
    "DictRecord",
    "DictFetchReport",
    "DictConflict",
    "DictCollectionError",
    "ReferenceDictSet",
    "collect_reference_dictionaries",
    "detect_conflicts",
    "SCOPE_DEVICE_TYPE",
    "SCOPE_USER_BIG_NO",
    "SCOPE_BRAND",
    "SCOPE_MODEL",
    "SCOPE_COMM_MODE",
    "SOURCE_EDGE",
    "SOURCE_CLOUD",
    "ALL_SCOPES",
]

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .reference_provider import ReferenceDictProvider

# 字典作用域标识
SCOPE_DEVICE_TYPE = "device_type"
SCOPE_USER_BIG_NO = "user_big_no"
SCOPE_BRAND = "brand"
SCOPE_MODEL = "model"
SCOPE_COMM_MODE = "comm_mode"
# 来源标识
SOURCE_EDGE = "edge"
SOURCE_CLOUD = "cloud"
# 五类字典（全有或全无的完整集合）
ALL_SCOPES: tuple[str, ...] = (
    SCOPE_DEVICE_TYPE,
    SCOPE_USER_BIG_NO,
    SCOPE_BRAND,
    SCOPE_MODEL,
    SCOPE_COMM_MODE,
)
# 默认分页参数
DEFAULT_PAGE_SIZE = 500
DEFAULT_MAX_PAGES = 1000


def _now_iso() -> str:
    """返回当前 UTC 时间的 ISO 秒级字符串。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean_code(value: object) -> str:
    """将码值规范化为字符串，保留合法的 ``0`` / ``"0"``。

    Args:
        value: 原始码值（可能是 int、str 或 None）。

    Returns:
        去空白的字符串；None 归一为空串。
    """
    if value is None:
        return ""
    return str(value).strip()


@dataclass
class DictRecord:
    """标准化后的单条字典记录。

    Attributes:
        scope: 作用域（device_type/user_big_no/brand/model/comm_mode）。
        source: 来源（edge/cloud）。
        name: 工程人员所见名称（下拉显示名）。
        code: 业务码值（写入后端用），保留 ``"0"``。
        internal_id: 接口内部 ID，仅供查询关联，不替代业务码。
        scope_key: 作用域细分键（型号为 brandId，其余为空表示全局）。
        scope_label: 作用域可读标签（型号为 brandName）。
        fetched_at: 本条记录的获取时间。
    """

    scope: str = ""
    source: str = ""
    name: str = ""
    code: str = ""
    internal_id: str = ""
    scope_key: str = ""
    scope_label: str = ""
    fetched_at: str = ""

    def to_dict(self) -> dict:
        """序列化为普通字典（供快照存储）。

        Returns:
            含全部字段的字典。
        """
        return {
            "scope": self.scope,
            "source": self.source,
            "name": self.name,
            "code": self.code,
            "internal_id": self.internal_id,
            "scope_key": self.scope_key,
            "scope_label": self.scope_label,
            "fetched_at": self.fetched_at,
        }


@dataclass
class DictFetchReport:
    """单个字典的取数分页报告。

    Attributes:
        scope: 作用域。
        source: 来源。
        pages: 实际请求页数。
        collected: 去重后收集到的记录数。
        total_expected: 后端声明的总数（无则为 None）。
        duplicate_pages: 检测到的重复页数（整页记录均已见过）。
        truncated: 是否截断（收集数 < 声明总数，或触顶仍未自然结束）。
        hit_page_cap: 是否因达到最大页数上限而停止。
    """

    scope: str = ""
    source: str = ""
    pages: int = 0
    collected: int = 0
    total_expected: int | None = None
    duplicate_pages: int = 0
    truncated: bool = False
    hit_page_cap: bool = False


@dataclass
class DictConflict:
    """同作用域同名异码冲突。

    Attributes:
        scope: 作用域。
        scope_key: 作用域细分键（型号为 brandId，其余为空）。
        name: 冲突的名称。
        codes: 该名称在同一作用域下出现的多个码值。
    """

    scope: str = ""
    scope_key: str = ""
    name: str = ""
    codes: list[str] = field(default_factory=list)


class DictCollectionError(Exception):
    """参考字典取数未全部成功（全有或全无），携带具体失败来源。"""

    def __init__(self, failures: list[tuple[str, str]]):
        """初始化异常。

        Args:
            failures: ``(scope, message)`` 失败来源列表。
        """
        self.failures = list(failures)
        detail = "; ".join(f"{scope}: {msg}" for scope, msg in self.failures)
        super().__init__(
            f"参考字典取数未全部成功（全有或全无），失败来源 → {detail}"
        )


# ── 行/项 → DictRecord 标准化 ──


def _map_user_big_no(row: dict, fetched_at: str) -> DictRecord | None:
    """标准化用户大分类行（deviceTypeName/deviceTypeCode）。"""
    name = str(row.get("deviceTypeName", "") or "").strip()
    code = _clean_code(row.get("deviceTypeCode"))
    if not name or code == "":
        return None
    return DictRecord(
        scope=SCOPE_USER_BIG_NO,
        source=SOURCE_CLOUD,
        name=name,
        code=code,
        internal_id=_clean_code(row.get("id")),
        fetched_at=fetched_at,
    )


def _map_brand(row: dict, fetched_at: str) -> DictRecord | None:
    """标准化品牌行（nameCN 优先，code 为业务码）。"""
    name = str(row.get("nameCN", "") or row.get("name", "") or "").strip()
    code = _clean_code(row.get("code"))
    if not name or code == "":
        return None
    return DictRecord(
        scope=SCOPE_BRAND,
        source=SOURCE_CLOUD,
        name=name,
        code=code,
        internal_id=_clean_code(row.get("id")),
        fetched_at=fetched_at,
    )


def _map_model(row: dict, fetched_at: str) -> DictRecord | None:
    """标准化型号行（modelCode 为业务码，brandId 作作用域关联）。"""
    name = str(row.get("name", "") or "").strip()
    code = _clean_code(row.get("modelCode"))
    if not name or code == "":
        return None
    return DictRecord(
        scope=SCOPE_MODEL,
        source=SOURCE_CLOUD,
        name=name,
        code=code,
        internal_id=_clean_code(row.get("id")),
        scope_key=_clean_code(row.get("brandId")),
        scope_label=str(row.get("brandName", "") or "").strip(),
        fetched_at=fetched_at,
    )


def _normalize_edge_list(
    items: list,
    scope: str,
    name_key: str,
    code_key: str,
    fetched_at: str,
) -> list[DictRecord]:
    """标准化边缘字典项列表（无分页）。

    Args:
        items: 边缘 ``rtnData`` 列表。
        scope: 作用域。
        name_key: 名称字段键。
        code_key: 码值字段键。
        fetched_at: 获取时间。

    Returns:
        标准化记录列表；名称或码值为空的项被跳过（``"0"`` 保留）。
    """
    records: list[DictRecord] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get(name_key, "") or "").strip()
        code = _clean_code(item.get(code_key))
        if not name or code == "":
            continue
        records.append(
            DictRecord(
                scope=scope,
                source=SOURCE_EDGE,
                name=name,
                code=code,
                fetched_at=fetched_at,
            )
        )
    return records


# ── 云端分页驱动 ──


async def _fetch_cloud_paged(
    provider: "ReferenceDictProvider",
    api_method: Callable[..., Awaitable[dict]],
    scope: str,
    mapper: Callable[[dict, str], DictRecord | None],
    fetched_at: str,
    page_size: int,
    max_pages: int,
) -> tuple[list[DictRecord], DictFetchReport]:
    """按显式分页拉取云端字典并检测重复页与截断。

    结束条件：空页、短页（不足 page_size）、达到声明总数、整页重复（stall）
    或触顶 max_pages。重复行（同一内部 ID 或同一 关联|名称|码 三元组）跳过。

    Args:
        provider: 参考字典提供者。
        api_method: 云端 api_client 方法（首参 token，接受 pageIndex/pageSize）。
        scope: 作用域。
        mapper: 行标准化函数。
        fetched_at: 获取时间。
        page_size: 每页条数。
        max_pages: 页数上限（防失控）。

    Returns:
        ``(记录列表, 分页报告)``。
    """
    records: list[DictRecord] = []
    seen: set[str] = set()
    report = DictFetchReport(scope=scope, source=SOURCE_CLOUD)
    total_expected: int | None = None
    page_index = 1
    while page_index <= max_pages:
        result = await provider.cloud_call(
            api_method, pageIndex=page_index, pageSize=page_size
        )
        data = result.get("data") if isinstance(result, dict) else None
        data = data if isinstance(data, dict) else {}
        rows = data.get("rows") or []
        if total_expected is None:
            declared = data.get("total")
            if isinstance(declared, int):
                total_expected = declared
        report.pages += 1
        new_in_page = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            rec = mapper(row, fetched_at)
            if rec is None:
                continue
            dedup_key = rec.internal_id or (
                f"{rec.scope_key}|{rec.name}|{rec.code}"
            )
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            records.append(rec)
            new_in_page += 1
        if rows and new_in_page == 0:
            # 整页均为已见记录：判定重复页并停止，避免无限翻页
            report.duplicate_pages += 1
            break
        if not rows or len(rows) < page_size:
            break
        if total_expected is not None and len(records) >= total_expected:
            break
        page_index += 1
    else:
        report.hit_page_cap = True
    report.collected = len(records)
    report.total_expected = total_expected
    if total_expected is not None and len(records) < total_expected:
        report.truncated = True
    elif report.hit_page_cap:
        report.truncated = True
    return records, report


# ── 同名异码检测 ──


def detect_conflicts(records: list[DictRecord]) -> list[DictConflict]:
    """检测同作用域内同名对应多个码值的冲突。

    作用域由 ``(scope, scope_key)`` 界定：型号按 brandId 分域，故跨品牌同名
    合法；其余字典 scope_key 为空，属全局作用域。

    Args:
        records: 全部标准化记录。

    Returns:
        冲突列表（每项含冲突名称与多个码值）。
    """
    groups: dict[tuple[str, str, str], set[str]] = {}
    for rec in records:
        key = (rec.scope, rec.scope_key, rec.name)
        groups.setdefault(key, set()).add(rec.code)
    conflicts: list[DictConflict] = []
    for (scope, scope_key, name), codes in groups.items():
        if len(codes) > 1:
            conflicts.append(
                DictConflict(
                    scope=scope,
                    scope_key=scope_key,
                    name=name,
                    codes=sorted(codes),
                )
            )
    return conflicts


# ── 结果容器 ──


@dataclass
class ReferenceDictSet:
    """一次生成任务取到的完整参考字典集合。

    Attributes:
        fetched_at: 本次取数时间。
        records: 作用域到记录列表的映射。
        reports: 各字典分页报告。
        conflicts: 同名异码冲突列表。
    """

    fetched_at: str = ""
    records: dict[str, list[DictRecord]] = field(default_factory=dict)
    reports: list[DictFetchReport] = field(default_factory=list)
    conflicts: list[DictConflict] = field(default_factory=list)

    def scope_records(self, scope: str) -> list[DictRecord]:
        """返回指定作用域的记录列表。"""
        return self.records.get(scope, [])

    def code_map(self, scope: str, scope_key: str | None = None) -> dict[str, str]:
        """构造名称到码值的映射（可按作用域细分键过滤）。

        Args:
            scope: 作用域。
            scope_key: 型号等按品牌过滤时传入 brandId；None 表示不过滤。

        Returns:
            ``{名称: 码值}`` 字典。
        """
        out: dict[str, str] = {}
        for rec in self.scope_records(scope):
            if scope_key is not None and rec.scope_key != scope_key:
                continue
            out[rec.name] = rec.code
        return out

    def has_conflicts(self) -> bool:
        """是否存在同名异码冲突。"""
        return bool(self.conflicts)

    def truncated_scopes(self) -> list[str]:
        """返回被判定截断的作用域列表。"""
        return [r.scope for r in self.reports if r.truncated]

    def is_complete(self) -> bool:
        """五类字典是否齐备、无冲突且无截断。"""
        if any(scope not in self.records for scope in ALL_SCOPES):
            return False
        if self.has_conflicts() or self.truncated_scopes():
            return False
        return True

    def to_snapshot_dict(self) -> dict:
        """序列化为快照字典（作用域到记录字典列表）。

        Returns:
            可 JSON 化的字典，供 :class:`TemplateSnapshot` 存储。
        """
        return {
            scope: [rec.to_dict() for rec in recs]
            for scope, recs in self.records.items()
        }


# ── 全有或全无编排 ──


async def collect_reference_dictionaries(
    provider: "ReferenceDictProvider",
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_pages: int = DEFAULT_MAX_PAGES,
    fetched_at: str | None = None,
) -> ReferenceDictSet:
    """取全五类参考字典并标准化，任一来源失败即整体失败。

    Args:
        provider: 参考字典提供者（已完成配置与鉴权注入）。
        page_size: 云端分页每页条数。
        max_pages: 云端分页页数上限。
        fetched_at: 显式获取时间（测试注入用），默认当前 UTC。

    Returns:
        完整的 :class:`ReferenceDictSet`。

    Raises:
        DictCollectionError: 任一字典取数失败（携带具体来源）。
    """
    ts = fetched_at or _now_iso()
    failures: list[tuple[str, str]] = []
    records_by_scope: dict[str, list[DictRecord]] = {}
    reports: list[DictFetchReport] = []

    # 边缘（同步、无分页）
    edge_specs = [
        (SCOPE_DEVICE_TYPE, provider.fetch_device_types, "name", "code"),
        (
            SCOPE_COMM_MODE,
            provider.fetch_comm_modes,
            "dictItemName",
            "dictItemCode",
        ),
    ]
    for scope, fetch, name_key, code_key in edge_specs:
        try:
            result = fetch()
            data = result.get("data") if isinstance(result, dict) else None
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                items = data.get("rows") or []
            else:
                items = []
            recs = _normalize_edge_list(items, scope, name_key, code_key, ts)
            records_by_scope[scope] = recs
            reports.append(
                DictFetchReport(
                    scope=scope,
                    source=SOURCE_EDGE,
                    pages=1,
                    collected=len(recs),
                    total_expected=len(items),
                )
            )
        except Exception as exc:  # noqa: BLE001 - 汇总为具体来源后统一抛出
            failures.append((scope, str(exc)))

    # 云端（显式分页）
    api = provider.api_client
    cloud_specs = [
        (SCOPE_USER_BIG_NO, api.get_device_type_list, _map_user_big_no),
        (SCOPE_BRAND, api.get_brand_list, _map_brand),
        (SCOPE_MODEL, api.get_model_list, _map_model),
    ]
    for scope, api_method, mapper in cloud_specs:
        try:
            recs, report = await _fetch_cloud_paged(
                provider, api_method, scope, mapper, ts, page_size, max_pages
            )
            records_by_scope[scope] = recs
            reports.append(report)
        except Exception as exc:  # noqa: BLE001 - 汇总为具体来源后统一抛出
            failures.append((scope, str(exc)))

    if failures:
        raise DictCollectionError(failures)

    all_records = [
        rec for recs in records_by_scope.values() for rec in recs
    ]
    return ReferenceDictSet(
        fetched_at=ts,
        records=records_by_scope,
        reports=reports,
        conflicts=detect_conflicts(all_records),
    )
