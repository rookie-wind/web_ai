"""task 2.4 验收：非敏感快照私有存储、30 天有效期与规范化内容核对。

覆盖验收标准：字典变化仍按原快照解析、篡改拒绝、过期拒绝、跨身份拒绝、
同秒生成不覆盖；并验证归属摘要不可逆、往返一致、内容摘要与清理。
全程使用 tmp_path 与可控时钟，无网络、无真实凭据。
"""

from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_MCP_DIR = Path(__file__).parent.parent
if str(_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_MCP_DIR))

from archiving.models import TemplateSnapshot  # noqa: E402
from archiving.snapshot_store import (  # noqa: E402
    SnapshotExpiredError,
    SnapshotNotFoundError,
    SnapshotOwnerMismatchError,
    SnapshotStore,
    SnapshotTamperError,
    compute_content_digest,
    derive_owner_id,
)
from archiving.snapshot_store import SnapshotError  # noqa: E402

_BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)
_OWNER = derive_owner_id("mcp-token-owner")
_OTHER = derive_owner_id("mcp-token-intruder")
_BYTES = b"PK\x03\x04blank-template-bytes"


class _Clock:
    """可控时钟替身。"""

    def __init__(self, dt: datetime = _BASE):
        """初始化。"""
        self.dt = dt

    def __call__(self) -> datetime:
        """返回当前时间。"""
        return self.dt

    def advance(self, **kwargs) -> None:
        """推进时间。"""
        self.dt = self.dt + timedelta(**kwargs)


def _snapshot(dictionaries=None, mappings=None) -> TemplateSnapshot:
    """构造一个默认快照（不带 content_digest，交由存储计算）。"""
    return TemplateSnapshot(
        version="v14-engineer",
        field_contract_version="fc-v1",
        source_time="2026-01-01T00:00:00+00:00",
        dictionaries=dictionaries
        if dictionaries is not None
        else {"brand": [{"name": "安科瑞", "code": "1"}]},
        mappings=mappings if mappings is not None else {"brand": {"安科瑞": "1"}},
    )


def _store(tmp_path, clock=None) -> SnapshotStore:
    """构造使用 tmp_path 与可控时钟的存储。"""
    return SnapshotStore(tmp_path, ttl_days=30, now_fn=clock or _Clock())


# ── 往返与摘要 ──


class TestSaveLoad:
    """保存与加载的基本契约。"""

    def test_roundtrip_preserves_snapshot(self, tmp_path):
        """加载后字典/版本/契约与文件摘要一致。"""
        store = _store(tmp_path)
        rec = store.save(_snapshot(), owner_id=_OWNER, template_bytes=_BYTES)
        loaded = store.load(rec.snapshot_id, owner_id=_OWNER)
        assert loaded.snapshot.dictionaries == {"brand": [
            {"name": "安科瑞", "code": "1"}]}
        assert loaded.version == "v14-engineer"
        assert loaded.field_contract_version == "fc-v1"
        assert loaded.template_sha256 == hashlib.sha256(_BYTES).hexdigest()

    def test_content_digest_autocomputed(self, tmp_path):
        """快照无 content_digest 时由存储按规范化内容计算。"""
        store = _store(tmp_path)
        snap = _snapshot()
        rec = store.save(snap, owner_id=_OWNER, template_bytes=_BYTES)
        assert rec.content_digest == compute_content_digest(
            snap.dictionaries, snap.mappings
        )

    def test_read_template_bytes_exact(self, tmp_path):
        """读回的模板字节与写入完全一致。"""
        store = _store(tmp_path)
        rec = store.save(_snapshot(), owner_id=_OWNER, template_bytes=_BYTES)
        assert store.read_template_bytes(
            rec.snapshot_id, owner_id=_OWNER
        ) == _BYTES

    def test_save_requires_owner(self, tmp_path):
        """归属为空拒绝保存。"""
        store = _store(tmp_path)
        with pytest.raises(SnapshotError):
            store.save(_snapshot(), owner_id="", template_bytes=_BYTES)

    def test_digest_order_independent(self):
        """规范化摘要与键插入顺序无关。"""
        d1 = compute_content_digest({"a": 1, "b": 2}, {"x": {"k": "v"}})
        d2 = compute_content_digest({"b": 2, "a": 1}, {"x": {"k": "v"}})
        assert d1 == d2


# ── 内容核对：篡改拒绝 ──


class TestContentVerification:
    """工作簿呈现内容与权威快照的核对。"""

    def test_verify_content_ok(self, tmp_path):
        """呈现内容与权威一致时通过并返回权威记录。"""
        store = _store(tmp_path)
        snap = _snapshot()
        rec = store.save(snap, owner_id=_OWNER, template_bytes=_BYTES)
        got = store.verify_content(
            rec.snapshot_id,
            owner_id=_OWNER,
            presented_dictionaries=snap.dictionaries,
            presented_mappings=snap.mappings,
        )
        assert got.snapshot_id == rec.snapshot_id

    def test_verify_content_tamper_mapping(self, tmp_path):
        """呈现映射被改码 → 篡改拒绝。"""
        store = _store(tmp_path)
        rec = store.save(_snapshot(), owner_id=_OWNER, template_bytes=_BYTES)
        with pytest.raises(SnapshotTamperError):
            store.verify_content(
                rec.snapshot_id,
                owner_id=_OWNER,
                presented_dictionaries={"brand": [
                    {"name": "安科瑞", "code": "1"}]},
                presented_mappings={"brand": {"安科瑞": "999"}},
            )

    def test_verify_content_tamper_digest(self, tmp_path):
        """呈现摘要与权威不符 → 篡改拒绝。"""
        store = _store(tmp_path)
        rec = store.save(_snapshot(), owner_id=_OWNER, template_bytes=_BYTES)
        with pytest.raises(SnapshotTamperError):
            store.verify_content(
                rec.snapshot_id, owner_id=_OWNER, presented_digest="deadbeef"
            )


# ── 过期 / 跨身份 / 缺失拒绝 ──


class TestRejection:
    """有效期、归属与存在性守卫。"""

    def test_expired_rejected(self, tmp_path):
        """超过 30 天 → 过期拒绝。"""
        clock = _Clock()
        store = _store(tmp_path, clock)
        rec = store.save(_snapshot(), owner_id=_OWNER, template_bytes=_BYTES)
        clock.advance(days=31)
        with pytest.raises(SnapshotExpiredError):
            store.load(rec.snapshot_id, owner_id=_OWNER)

    def test_within_ttl_ok(self, tmp_path):
        """未到期（第 29 天）仍可加载。"""
        clock = _Clock()
        store = _store(tmp_path, clock)
        rec = store.save(_snapshot(), owner_id=_OWNER, template_bytes=_BYTES)
        clock.advance(days=29)
        assert store.load(rec.snapshot_id, owner_id=_OWNER).snapshot_id

    def test_cross_identity_rejected(self, tmp_path):
        """他人身份加载 → 跨身份拒绝。"""
        store = _store(tmp_path)
        rec = store.save(_snapshot(), owner_id=_OWNER, template_bytes=_BYTES)
        with pytest.raises(SnapshotOwnerMismatchError):
            store.load(rec.snapshot_id, owner_id=_OTHER)

    def test_not_found(self, tmp_path):
        """不存在的快照 ID → 缺失拒绝。"""
        store = _store(tmp_path)
        with pytest.raises(SnapshotNotFoundError):
            store.load("no-such-id", owner_id=_OWNER)


# ── 同秒不覆盖 & 字典变化仍按原快照 ──


class TestGenerationSemantics:
    """生成语义：同秒唯一、原快照稳定。"""

    def test_same_second_no_overwrite(self, tmp_path):
        """同一时刻两次生成 → 不同快照 ID，互不覆盖。"""
        clock = _Clock()
        store = _store(tmp_path, clock)
        r1 = store.save(_snapshot(), owner_id=_OWNER, template_bytes=_BYTES)
        r2 = store.save(_snapshot(), owner_id=_OWNER, template_bytes=_BYTES)
        assert r1.snapshot_id != r2.snapshot_id
        assert (tmp_path / f"{r1.snapshot_id}.json").exists()
        assert (tmp_path / f"{r2.snapshot_id}.json").exists()
        assert (tmp_path / f"{r1.snapshot_id}.xlsx").exists()
        assert (tmp_path / f"{r2.snapshot_id}.xlsx").exists()
        # 两条记录都能独立加载
        assert store.load(r1.snapshot_id, owner_id=_OWNER).snapshot_id
        assert store.load(r2.snapshot_id, owner_id=_OWNER).snapshot_id

    def test_dictionary_change_parses_by_original_snapshot(self, tmp_path):
        """字典后续变化不影响按原快照解析（加载仍得原字典）。"""
        store = _store(tmp_path)
        original = {"brand": [{"name": "安科瑞", "code": "1"}]}
        rec = store.save(
            _snapshot(dictionaries=original, mappings={"brand": {"安科瑞": "1"}}),
            owner_id=_OWNER,
            template_bytes=_BYTES,
        )
        # 模拟平台字典刷新（与已存快照无关）
        _changed = {"brand": [{"name": "安科瑞", "code": "777"}]}
        reopened = SnapshotStore(
            tmp_path, ttl_days=30, now_fn=_Clock()
        )
        loaded = reopened.load(rec.snapshot_id, owner_id=_OWNER)
        assert loaded.snapshot.dictionaries == original
        assert loaded.content_digest == compute_content_digest(
            original, {"brand": {"安科瑞": "1"}}
        )


# ── 归属摘要 & 清理 ──


class TestOwnerAndPurge:
    """归属摘要不可逆与过期清理。"""

    def test_derive_owner_id_properties(self):
        """归属摘要确定、区分、不可逆、空 Token 空摘要。"""
        a = derive_owner_id("tok-A")
        assert a == derive_owner_id("tok-A")
        assert a != derive_owner_id("tok-B")
        assert a != "tok-A" and len(a) == 64
        assert derive_owner_id("") == ""

    def test_purge_expired_removes_only_expired(self, tmp_path):
        """清理仅删除过期快照，保留有效期内快照。"""
        clock = _Clock()
        store = _store(tmp_path, clock)
        old = store.save(_snapshot(), owner_id=_OWNER, template_bytes=_BYTES)
        clock.advance(days=31)
        fresh = store.save(_snapshot(), owner_id=_OWNER, template_bytes=_BYTES)
        purged = store.purge_expired()
        assert purged == 1
        assert not (tmp_path / f"{old.snapshot_id}.json").exists()
        assert not (tmp_path / f"{old.snapshot_id}.xlsx").exists()
        assert (tmp_path / f"{fresh.snapshot_id}.json").exists()
        assert store.load(fresh.snapshot_id, owner_id=_OWNER).snapshot_id
