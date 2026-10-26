"""task 2.3 验收：五类字典标准化、完整分页、作用域关联与同名异码检测。

覆盖 design §1 与验收标准：重复页、截断、跨品牌同名（合法）、同品牌同名异码
（冲突）、0 码值保留、部分服务失败（全有或全无 + 具体来源），以及边缘列表
（设备类型 / 代理通信方式）的标准化。全程 mock，无网络。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_MCP_DIR = Path(__file__).parent.parent
if str(_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_MCP_DIR))

from archiving.reference_config import ReferenceConfig  # noqa: E402
from archiving.reference_dict import (  # noqa: E402
    SCOPE_BRAND,
    SCOPE_COMM_MODE,
    SCOPE_DEVICE_TYPE,
    SCOPE_MODEL,
    SCOPE_USER_BIG_NO,
    DictCollectionError,
    collect_reference_dictionaries,
    detect_conflicts,
)
from archiving.reference_provider import (  # noqa: E402
    ReferenceDictError,
    ReferenceDictProvider,
)

_TS = "2026-01-01T00:00:00+00:00"

_DEVICE_TYPES = [
    {"code": "100009", "name": "8163网关"},
    {"code": "100019", "name": "XLBA"},
]
_COMM_MODES = [
    {"dictItemCode": "13", "dictItemName": "MQTT"},
    {"dictItemCode": "0", "dictItemName": "未配置"},
]
_USER_BIG = [{"id": 1, "deviceTypeName": "电表", "deviceTypeCode": "11"}]
_BRANDS = [
    {"id": 10, "nameCN": "安科瑞", "code": "1"},
    {"id": 11, "nameCN": "美的", "code": "6"},
]
_MODELS = [
    {"id": 100, "name": "DTZ341", "brandId": 10, "brandName": "安科瑞",
     "modelCode": "33"},
    {"id": 101, "name": "DTZ341", "brandId": 11, "brandName": "美的",
     "modelCode": "44"},
]


class _PagedCloud:
    """云端替身：按 pageIndex 提供分页行，可对指定方法抛错。"""

    def __init__(self, pages, totals=None, raise_for=None):
        """初始化。

        Args:
            pages: 方法名到「每页行列表」的映射。
            totals: 方法名到声明总数的映射（缺省表示无 total 字段）。
            raise_for: 需抛 ReferenceDictError 的方法名集合。
        """
        self._pages = pages
        self._totals = totals or {}
        self._raise_for = raise_for or set()
        self.calls: list[tuple] = []

    async def _serve(self, method, token, pageIndex=1, pageSize=500):
        self.calls.append((method, token, pageIndex, pageSize))
        if method in self._raise_for:
            raise ReferenceDictError(f"{method} 服务失败")
        seq = self._pages.get(method, [])
        rows = seq[pageIndex - 1] if pageIndex - 1 < len(seq) else []
        data = {"rows": rows}
        if method in self._totals:
            data["total"] = self._totals[method]
        return {"error": False, "code": 20000, "data": data, "empty": not rows}

    async def get_device_type_list(self, token, **k):
        """设备类型（用户大分类）分页替身。"""
        return await self._serve("get_device_type_list", token, **k)

    async def get_brand_list(self, token, **k):
        """品牌分页替身。"""
        return await self._serve("get_brand_list", token, **k)

    async def get_model_list(self, token, **k):
        """型号分页替身。"""
        return await self._serve("get_model_list", token, **k)


class _DictEdge:
    """边缘替身：按路径返回设备类型或通信方式字典。"""

    instances: list["_DictEdge"] = []

    def __init__(self, base_url, login_name, password, *a, **k):
        """初始化并登记实例。"""
        self.base_url = base_url
        self.logged_in = False
        self.closed = False
        self.calls: list[tuple] = []
        _DictEdge.instances.append(self)

    def login(self):
        """模拟登录成功。"""
        self.logged_in = True
        return {"ok": True, "rtnCode": 0, "data": {"token": "t"}}

    def call(self, path, payload=None):
        """按路径返回对应字典列表。"""
        self.calls.append((path, payload or {}))
        if path.endswith("getDeviceTypeSelect/v1"):
            data = _DEVICE_TYPES
        elif "getDictItemList" in path:
            data = _COMM_MODES
        else:
            data = []
        return {"ok": True, "rtnCode": 0, "rtnMsg": "", "data": data}

    def close(self):
        """标记关闭。"""
        self.closed = True


_FULL_CFG = ReferenceConfig(
    reference_edge_url="http://ref-edge:7500",
    reference_edge_login_name="refuser",
    reference_edge_password="refpass",
    cloud_base_url="https://cloud.example.com",
)


async def _never() -> bool:
    """永不成功的刷新替身。"""
    return False


def _provider(cloud) -> ReferenceDictProvider:
    """构造注入式 provider。"""
    return ReferenceDictProvider(
        _FULL_CFG,
        api_client=cloud,
        system_token_accessor=lambda: "SYS",
        system_token_refresher=_never,
        edge_client_factory=_DictEdge,
    )


def _default_pages():
    """默认单页数据（各方法一页即结束）。"""
    return {
        "get_device_type_list": [_USER_BIG],
        "get_brand_list": [_BRANDS],
        "get_model_list": [_MODELS],
    }


@pytest.fixture(autouse=True)
def _clear_edge():
    """每例前清空边缘实例登记。"""
    _DictEdge.instances.clear()


# ── 完整取数与标准化 ──


class TestCollectComplete:
    """五类字典齐备时的标准化结果。"""

    @pytest.mark.asyncio
    async def test_all_five_scopes_complete(self):
        """五类字典齐备、无冲突、无截断 → is_complete。"""
        provider = _provider(_PagedCloud(_default_pages()))
        result = await collect_reference_dictionaries(
            provider, fetched_at=_TS
        )
        assert result.is_complete()
        assert len(result.scope_records(SCOPE_DEVICE_TYPE)) == 2
        assert len(result.scope_records(SCOPE_COMM_MODE)) == 2
        assert len(result.scope_records(SCOPE_USER_BIG_NO)) == 1
        assert len(result.scope_records(SCOPE_BRAND)) == 2
        assert len(result.scope_records(SCOPE_MODEL)) == 2
        provider.close()

    @pytest.mark.asyncio
    async def test_edge_records_normalized(self):
        """边缘记录 source=edge，名称/码值取正确字段。"""
        provider = _provider(_PagedCloud(_default_pages()))
        result = await collect_reference_dictionaries(
            provider, fetched_at=_TS
        )
        dt = {r.name: r.code for r in result.scope_records(SCOPE_DEVICE_TYPE)}
        assert dt == {"8163网关": "100009", "XLBA": "100019"}
        cm = {r.name: r.code for r in result.scope_records(SCOPE_COMM_MODE)}
        assert cm["MQTT"] == "13"
        assert all(r.source == "edge" for r in
                   result.scope_records(SCOPE_COMM_MODE))
        provider.close()

    @pytest.mark.asyncio
    async def test_model_uses_business_code_not_internal_id(self):
        """型号业务码取 modelCode，而非内部 id。"""
        provider = _provider(_PagedCloud(_default_pages()))
        result = await collect_reference_dictionaries(
            provider, fetched_at=_TS
        )
        rec = result.scope_records(SCOPE_MODEL)[0]
        assert rec.code == "33"
        assert rec.internal_id == "100"
        assert rec.scope_key == "10" and rec.scope_label == "安科瑞"
        provider.close()

    @pytest.mark.asyncio
    async def test_brand_code_map(self):
        """品牌名称→码值映射正确。"""
        provider = _provider(_PagedCloud(_default_pages()))
        result = await collect_reference_dictionaries(
            provider, fetched_at=_TS
        )
        assert result.code_map(SCOPE_BRAND) == {"安科瑞": "1", "美的": "6"}
        provider.close()


# ── 0 码值保留 ──


class TestZeroCode:
    """合法 0 码值不得判为空。"""

    @pytest.mark.asyncio
    async def test_zero_code_preserved(self):
        """边缘通信方式含 dictItemCode='0' 应保留。"""
        provider = _provider(_PagedCloud(_default_pages()))
        result = await collect_reference_dictionaries(
            provider, fetched_at=_TS
        )
        cm = result.code_map(SCOPE_COMM_MODE)
        assert cm["未配置"] == "0"
        provider.close()

    @pytest.mark.asyncio
    async def test_integer_zero_code_preserved(self):
        """整型 0 码值规范化为字符串 '0' 并保留。"""
        pages = _default_pages()
        pages["get_device_type_list"] = [
            [{"id": 9, "deviceTypeName": "零类", "deviceTypeCode": 0}]
        ]
        provider = _provider(_PagedCloud(pages))
        result = await collect_reference_dictionaries(
            provider, fetched_at=_TS
        )
        assert result.code_map(SCOPE_USER_BIG_NO) == {"零类": "0"}
        provider.close()


# ── 分页：重复页与截断 ──


class TestPagination:
    """显式分页的结束条件、重复页与截断检测。"""

    @pytest.mark.asyncio
    async def test_duplicate_page_detected(self):
        """第二页整页重复 → duplicate_pages=1 并停止。"""
        b = [{"id": 20, "nameCN": "格力", "code": "9"}]
        pages = _default_pages()
        pages["get_brand_list"] = [b + b[:0] + [
            {"id": 21, "nameCN": "海尔", "code": "8"}], b + [
            {"id": 21, "nameCN": "海尔", "code": "8"}]]
        # page1 两条(==page_size) → 继续；page2 全为已见 → 重复页停止
        provider = _provider(_PagedCloud(pages))
        result = await collect_reference_dictionaries(
            provider, page_size=2, fetched_at=_TS
        )
        report = next(r for r in result.reports if r.scope == SCOPE_BRAND)
        assert report.duplicate_pages == 1
        assert report.collected == 2
        provider.close()

    @pytest.mark.asyncio
    async def test_truncation_detected(self):
        """声明 total=5 但仅返回 2 条短页 → 截断，is_complete=False。"""
        pages = _default_pages()
        totals = {"get_brand_list": 5}
        provider = _provider(_PagedCloud(pages, totals=totals))
        result = await collect_reference_dictionaries(
            provider, fetched_at=_TS
        )
        assert SCOPE_BRAND in result.truncated_scopes()
        assert not result.is_complete()
        provider.close()

    @pytest.mark.asyncio
    async def test_multi_page_collects_all(self):
        """跨页收集全部并按 total 结束，不判截断。"""
        p1 = [{"id": i, "nameCN": f"品牌{i}", "code": str(i)}
              for i in range(1, 3)]
        p2 = [{"id": 3, "nameCN": "品牌3", "code": "3"}]
        pages = _default_pages()
        pages["get_brand_list"] = [p1, p2]
        totals = {"get_brand_list": 3}
        provider = _provider(_PagedCloud(pages, totals=totals))
        result = await collect_reference_dictionaries(
            provider, page_size=2, fetched_at=_TS
        )
        report = next(r for r in result.reports if r.scope == SCOPE_BRAND)
        assert report.collected == 3 and not report.truncated
        assert report.pages == 2
        provider.close()


# ── 作用域关联与同名异码 ──


class TestScopeAssociationAndConflicts:
    """品牌型号作用域关联与同作用域同名异码检测。"""

    @pytest.mark.asyncio
    async def test_cross_brand_same_name_legal(self):
        """跨品牌同型号名（不同 brandId）合法，无冲突。"""
        provider = _provider(_PagedCloud(_default_pages()))
        result = await collect_reference_dictionaries(
            provider, fetched_at=_TS
        )
        assert not result.has_conflicts()
        provider.close()

    @pytest.mark.asyncio
    async def test_same_brand_same_name_diff_code_conflict(self):
        """同品牌同名对应两个 modelCode → 冲突，is_complete=False。"""
        pages = _default_pages()
        pages["get_model_list"] = [[
            {"id": 100, "name": "DTZ341", "brandId": 10,
             "brandName": "安科瑞", "modelCode": "33"},
            {"id": 102, "name": "DTZ341", "brandId": 10,
             "brandName": "安科瑞", "modelCode": "99"},
        ]]
        provider = _provider(_PagedCloud(pages))
        result = await collect_reference_dictionaries(
            provider, fetched_at=_TS
        )
        assert result.has_conflicts()
        conflict = result.conflicts[0]
        assert conflict.scope == SCOPE_MODEL
        assert conflict.scope_key == "10"
        assert conflict.codes == ["33", "99"]
        assert not result.is_complete()
        provider.close()

    @pytest.mark.asyncio
    async def test_model_code_map_scoped_by_brand(self):
        """按 brandId 过滤的型号映射只含该品牌型号。"""
        provider = _provider(_PagedCloud(_default_pages()))
        result = await collect_reference_dictionaries(
            provider, fetched_at=_TS
        )
        assert result.code_map(SCOPE_MODEL, scope_key="10") == {"DTZ341": "33"}
        assert result.code_map(SCOPE_MODEL, scope_key="11") == {"DTZ341": "44"}
        provider.close()

    def test_detect_conflicts_global_scope(self):
        """全局作用域（scope_key 空）同名异码判冲突。"""
        from archiving.reference_dict import DictRecord

        recs = [
            DictRecord(scope=SCOPE_BRAND, name="X", code="1"),
            DictRecord(scope=SCOPE_BRAND, name="X", code="2"),
        ]
        conflicts = detect_conflicts(recs)
        assert len(conflicts) == 1
        assert conflicts[0].codes == ["1", "2"]


# ── 全有或全无 ──


class TestAllOrNothing:
    """任一来源失败即整体失败并返回具体来源。"""

    @pytest.mark.asyncio
    async def test_partial_cloud_failure_raises_with_source(self):
        """品牌服务失败 → DictCollectionError 指明 brand 来源。"""
        provider = _provider(
            _PagedCloud(_default_pages(), raise_for={"get_brand_list"})
        )
        with pytest.raises(DictCollectionError) as exc:
            await collect_reference_dictionaries(provider, fetched_at=_TS)
        scopes = [s for s, _ in exc.value.failures]
        assert SCOPE_BRAND in scopes
        provider.close()

    @pytest.mark.asyncio
    async def test_edge_failure_raises_with_source(self):
        """边缘登录失败 → DictCollectionError 指明设备类型来源。"""
        class _BadEdge(_DictEdge):
            def login(self):
                raise ReferenceDictError("参考边缘登录失败")

        provider = ReferenceDictProvider(
            _FULL_CFG,
            api_client=_PagedCloud(_default_pages()),
            system_token_accessor=lambda: "SYS",
            system_token_refresher=_never,
            edge_client_factory=_BadEdge,
        )
        with pytest.raises(DictCollectionError) as exc:
            await collect_reference_dictionaries(provider, fetched_at=_TS)
        scopes = [s for s, _ in exc.value.failures]
        assert SCOPE_DEVICE_TYPE in scopes and SCOPE_COMM_MODE in scopes
        provider.close()

    @pytest.mark.asyncio
    async def test_snapshot_dict_serializable(self):
        """快照字典可 JSON 化且含五类作用域。"""
        import json

        provider = _provider(_PagedCloud(_default_pages()))
        result = await collect_reference_dictionaries(
            provider, fetched_at=_TS
        )
        snap = result.to_snapshot_dict()
        json.dumps(snap, ensure_ascii=False)
        assert set(snap.keys()) == {
            SCOPE_DEVICE_TYPE, SCOPE_COMM_MODE, SCOPE_USER_BIG_NO,
            SCOPE_BRAND, SCOPE_MODEL,
        }
        provider.close()
