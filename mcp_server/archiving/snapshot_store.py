"""非敏感模板快照的服务端私有存储与权威核对（design §2 / §4）。

一次生成任务产出「服务端权威快照记录」：随机快照 ID、所属接入身份摘要、
生成文件摘要、字段契约版本及规范化字典内容，默认保留 30 天。快照与空白模板
只含非敏感内容，存放在服务私有状态目录 ``archive_templates/``，不进入 git
或 Skills 包，也**绝不**写入现场凭据、原始 Excel 或登录响应。

权威核对语义：
  - 解析已填写工作簿时以**原快照**为准，字典后续变化不影响按原快照解析。
  - 工作簿可查看字典／映射，但服务端核对其规范化内容与权威快照；篡改拒绝。
  - 过期、跨身份、缺失一律拒绝；不对整个已填文件做原模板字节相等检查。

归属身份由已验证 MCP Token 的不可逆摘要派生（:func:`derive_owner_id`），
不使用 IP、云端角色或用户传入字段；本模块只接收派生后的 ``owner_id``。
"""

from __future__ import annotations

__all__ = [
    "SnapshotRecord",
    "SnapshotStore",
    "SnapshotError",
    "SnapshotNotFoundError",
    "SnapshotOwnerMismatchError",
    "SnapshotExpiredError",
    "SnapshotTamperError",
    "ChunkedUploadError",
    "UploadIncompleteError",
    "UploadLimitError",
    "UploadExpiredError",
    "compute_content_digest",
    "derive_owner_id",
    "DEFAULT_TTL_DAYS",
    "DEFAULT_UPLOAD_TTL_MINUTES",
    "DEFAULT_UPLOAD_MAX_BYTES",
    "DEFAULT_UPLOAD_MAX_CHUNKS",
]

import hashlib
import json
import os
import secrets
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import TemplateSnapshot

# 默认保留天数（design §2）
DEFAULT_TTL_DAYS = 30
# 私有状态目录环境变量覆盖名
_STATE_DIR_ENV = "XLPA_TEMPLATE_STATE_DIR"
# 快照 ID 字节数（16 字节 → 32 位十六进制，足够随机避免同秒碰撞）
_SNAPSHOT_ID_BYTES = 16
# 分块上传会话默认有效期（分钟）
DEFAULT_UPLOAD_TTL_MINUTES = 60
# 单次分块上传总字节上限（远大于典型模板，防缓冲耗尽）
DEFAULT_UPLOAD_MAX_BYTES = 20 * 1024 * 1024
# 单次分块上传最大分片数
DEFAULT_UPLOAD_MAX_CHUNKS = 2000


def _default_base_dir() -> Path:
    """返回默认私有状态目录（可被环境变量覆盖）。

    Returns:
        ``archive_templates`` 目录路径（不自动创建）。
    """
    override = os.getenv(_STATE_DIR_ENV, "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / "archive_templates"


def _now() -> datetime:
    """返回当前 UTC 感知时间。"""
    return datetime.now(timezone.utc)


def compute_content_digest(dictionaries: dict, mappings: dict) -> str:
    """计算规范化字典内容的 SHA-256 摘要。

    以键排序、紧凑分隔、保留非 ASCII 的规范化 JSON 为输入，保证同一逻辑
    内容在不同插入顺序下得到相同摘要。

    Args:
        dictionaries: 作用域到字典记录的映射。
        mappings: field_key 到 ``{友好名: 码值}`` 的映射。

    Returns:
        十六进制 SHA-256 摘要字符串。
    """
    canonical = json.dumps(
        {"dictionaries": dictionaries, "mappings": mappings},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def derive_owner_id(mcp_token: str) -> str:
    """由已验证 MCP Token 派生不可逆的归属身份摘要。

    仅用于绑定文件与任务归属；不存储、不返回原始 Token。

    Args:
        mcp_token: 已验证的 MCP 接入 Token。

    Returns:
        SHA-256 十六进制摘要；Token 为空时返回空串。
    """
    if not mcp_token:
        return ""
    return hashlib.sha256(mcp_token.encode("utf-8")).hexdigest()


class SnapshotError(Exception):
    """快照存储基类异常。"""


class SnapshotNotFoundError(SnapshotError):
    """快照不存在。"""


class SnapshotOwnerMismatchError(SnapshotError):
    """请求身份与快照归属不一致（跨身份拒绝）。"""


class SnapshotExpiredError(SnapshotError):
    """快照已过期，须重新获取模板。"""


class SnapshotTamperError(SnapshotError):
    """工作簿呈现的规范化内容与权威快照不一致（篡改拒绝）。"""


class ChunkedUploadError(SnapshotError):
    """分块上传基类异常。"""


class UploadIncompleteError(ChunkedUploadError):
    """分块不完整或会话不存在（缺片或未收任何片）。"""


class UploadLimitError(ChunkedUploadError):
    """分片数量或总字节超过上限。"""


class UploadExpiredError(ChunkedUploadError):
    """分块上传会话已过期，需重新开始。"""


@dataclass
class SnapshotRecord:
    """服务端权威快照记录（含归属、有效期与文件摘要）。

    Attributes:
        snapshot_id: 随机快照 ID。
        owner_id: 归属身份摘要。
        created_at: 创建时间（ISO 字符串）。
        expires_at: 到期时间（ISO 字符串）。
        template_sha256: 空白模板文件 SHA-256。
        template_name: 下载展示文件名。
        snapshot: 内嵌的 :class:`TemplateSnapshot`（字典／映射／契约版本）。
    """

    snapshot_id: str = ""
    owner_id: str = ""
    created_at: str = ""
    expires_at: str = ""
    template_sha256: str = ""
    template_name: str = ""
    snapshot: TemplateSnapshot = field(default_factory=TemplateSnapshot)

    @property
    def version(self) -> str:
        """模板结构版本。"""
        return self.snapshot.version

    @property
    def field_contract_version(self) -> str:
        """字段契约版本。"""
        return self.snapshot.field_contract_version

    @property
    def content_digest(self) -> str:
        """规范化字典内容摘要。"""
        return self.snapshot.content_digest

    def to_meta_dict(self) -> dict:
        """序列化为落盘元数据字典（不含模板字节）。

        Returns:
            含归属、有效期、文件摘要与内嵌快照的字典。
        """
        return {
            "snapshot_id": self.snapshot_id,
            "owner_id": self.owner_id,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "template_sha256": self.template_sha256,
            "template_name": self.template_name,
            "snapshot": self.snapshot.to_dict(),
        }

    @classmethod
    def from_meta_dict(cls, data: dict) -> "SnapshotRecord":
        """从落盘元数据反序列化。

        Args:
            data: 元数据字典。

        Returns:
            SnapshotRecord 实例。
        """
        data = data or {}
        return cls(
            snapshot_id=str(data.get("snapshot_id", "") or ""),
            owner_id=str(data.get("owner_id", "") or ""),
            created_at=str(data.get("created_at", "") or ""),
            expires_at=str(data.get("expires_at", "") or ""),
            template_sha256=str(data.get("template_sha256", "") or ""),
            template_name=str(data.get("template_name", "") or ""),
            snapshot=TemplateSnapshot.from_dict(data.get("snapshot") or {}),
        )


class SnapshotStore:
    """快照与空白模板的私有存储，负责归属、有效期与内容核对。

    目录布局（``base_dir`` 下）：
      - ``<snapshot_id>.json``：权威元数据记录。
      - ``<snapshot_id>.xlsx``：空白模板字节（下载用）。

    所有写入均为临时文件 + ``os.replace`` 原子落盘；随机快照 ID 保证同秒
    多次生成互不覆盖。
    """

    def __init__(
        self,
        base_dir: Path | str | None = None,
        *,
        ttl_days: int = DEFAULT_TTL_DAYS,
        now_fn: Callable[[], datetime] | None = None,
        upload_ttl_minutes: int = DEFAULT_UPLOAD_TTL_MINUTES,
        upload_max_bytes: int = DEFAULT_UPLOAD_MAX_BYTES,
        upload_max_chunks: int = DEFAULT_UPLOAD_MAX_CHUNKS,
    ):
        """初始化存储。

        Args:
            base_dir: 私有状态目录；None 时用默认（可被环境变量覆盖）。
            ttl_days: 快照有效期天数。
            now_fn: 当前时间回调（测试注入用），默认 UTC 现在。
            upload_ttl_minutes: 分块上传会话有效期分钟数。
            upload_max_bytes: 单次分块上传总字节上限。
            upload_max_chunks: 单次分块上传最大分片数。
        """
        self.base_dir = Path(base_dir) if base_dir else _default_base_dir()
        self.ttl_days = int(ttl_days)
        self._now_fn = now_fn or _now
        self.upload_ttl_minutes = int(upload_ttl_minutes)
        self.upload_max_bytes = int(upload_max_bytes)
        self.upload_max_chunks = int(upload_max_chunks)

    # ── 内部路径与原子写 ──

    def _meta_path(self, snapshot_id: str) -> Path:
        """返回快照元数据文件路径。"""
        return self.base_dir / f"{snapshot_id}.json"

    def _template_path(self, snapshot_id: str) -> Path:
        """返回空白模板文件路径。"""
        return self.base_dir / f"{snapshot_id}.xlsx"

    def _atomic_write_bytes(self, path: Path, payload: bytes) -> None:
        """原子写字节：先写临时文件再 ``os.replace``。"""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(payload)
        os.replace(tmp, path)

    # ── 写入 ──

    def save(
        self,
        snapshot: TemplateSnapshot,
        *,
        owner_id: str,
        template_bytes: bytes,
        template_name: str = "",
    ) -> SnapshotRecord:
        """保存权威快照记录与空白模板字节。

        若快照未带 ``snapshot_id`` 或 ``content_digest`` 则在此生成；随机 ID
        保证同秒生成不覆盖既有文件。

        Args:
            snapshot: 模板快照（字典／映射／契约版本）。
            owner_id: 归属身份摘要（由 :func:`derive_owner_id` 派生）。
            template_bytes: 空白模板文件字节。
            template_name: 下载展示文件名，默认 ``<snapshot_id>.xlsx``。

        Returns:
            已落盘的 :class:`SnapshotRecord`。

        Raises:
            SnapshotError: 归属为空或无法分配唯一快照 ID。
        """
        if not owner_id:
            raise SnapshotError("快照归属 owner_id 不能为空")

        stored = TemplateSnapshot.from_dict(snapshot.to_dict())
        if not stored.content_digest:
            stored.content_digest = compute_content_digest(
                stored.dictionaries, stored.mappings
            )

        snapshot_id = self._allocate_id(stored.snapshot_id)
        stored.snapshot_id = snapshot_id

        created = self._now_fn()
        expires = created + timedelta(days=self.ttl_days)
        record = SnapshotRecord(
            snapshot_id=snapshot_id,
            owner_id=owner_id,
            created_at=created.isoformat(timespec="seconds"),
            expires_at=expires.isoformat(timespec="seconds"),
            template_sha256=hashlib.sha256(template_bytes).hexdigest(),
            template_name=template_name or f"{snapshot_id}.xlsx",
            snapshot=stored,
        )
        meta = json.dumps(
            record.to_meta_dict(), ensure_ascii=False, indent=2
        ).encode("utf-8")
        self._atomic_write_bytes(self._template_path(snapshot_id), template_bytes)
        self._atomic_write_bytes(self._meta_path(snapshot_id), meta)
        return record

    def _allocate_id(self, requested: str = "") -> str:
        """分配唯一快照 ID，避免同秒或重复 ID 覆盖既有文件。

        Args:
            requested: 调用方期望的 ID（可空）；仅在其未占用时采用。

        Returns:
            未被占用的快照 ID。

        Raises:
            SnapshotError: 连续多次随机仍碰撞（极不可能）。
        """
        if requested and not self._meta_path(requested).exists():
            return requested
        for _ in range(100):
            candidate = secrets.token_hex(_SNAPSHOT_ID_BYTES)
            if not self._meta_path(candidate).exists():
                return candidate
        raise SnapshotError("无法分配唯一快照 ID，请检查状态目录")

    # ── 读取与核对 ──

    def load(self, snapshot_id: str, *, owner_id: str) -> SnapshotRecord:
        """按快照 ID 与归属加载记录，强制过期与身份校验。

        Args:
            snapshot_id: 快照 ID。
            owner_id: 请求方归属摘要。

        Returns:
            校验通过的 :class:`SnapshotRecord`。

        Raises:
            SnapshotNotFoundError: 快照不存在或元数据损坏。
            SnapshotOwnerMismatchError: 归属不一致。
            SnapshotExpiredError: 已过期。
        """
        meta_path = self._meta_path(snapshot_id)
        if not snapshot_id or not meta_path.exists():
            raise SnapshotNotFoundError(f"快照不存在: {snapshot_id}")
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise SnapshotNotFoundError(
                f"快照元数据损坏: {snapshot_id}"
            ) from exc
        record = SnapshotRecord.from_meta_dict(data)
        if record.owner_id != owner_id:
            raise SnapshotOwnerMismatchError(
                f"快照归属不匹配: {snapshot_id}"
            )
        if self._is_expired(record):
            raise SnapshotExpiredError(
                f"快照已过期，请重新获取模板: {snapshot_id}"
            )
        return record

    def _is_expired(self, record: SnapshotRecord) -> bool:
        """判断记录是否已过期（无法解析到期时间视为过期）。"""
        try:
            expires = datetime.fromisoformat(record.expires_at)
        except ValueError:
            return True
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return self._now_fn() > expires

    def read_template_bytes(
        self, snapshot_id: str, *, owner_id: str
    ) -> bytes:
        """读取空白模板字节（先经归属与有效期校验）。

        Args:
            snapshot_id: 快照 ID。
            owner_id: 请求方归属摘要。

        Returns:
            模板文件字节。

        Raises:
            SnapshotNotFoundError: 快照或模板文件缺失。
        """
        record = self.load(snapshot_id, owner_id=owner_id)
        path = self._template_path(record.snapshot_id)
        if not path.exists():
            raise SnapshotNotFoundError(
                f"模板文件缺失: {record.snapshot_id}"
            )
        return path.read_bytes()

    def verify_content(
        self,
        snapshot_id: str,
        *,
        owner_id: str,
        presented_digest: str = "",
        presented_dictionaries: dict | None = None,
        presented_mappings: dict | None = None,
    ) -> SnapshotRecord:
        """核对工作簿呈现的规范化内容与权威快照是否一致。

        归属与有效期先经 :meth:`load` 校验。呈现内容可用摘要或原始
        字典／映射给出；不一致即判篡改。

        Args:
            snapshot_id: 快照 ID。
            owner_id: 请求方归属摘要。
            presented_digest: 工作簿呈现内容的规范化摘要（优先）。
            presented_dictionaries: 呈现的字典（无摘要时用于计算）。
            presented_mappings: 呈现的映射（无摘要时用于计算）。

        Returns:
            校验通过的权威 :class:`SnapshotRecord`。

        Raises:
            SnapshotTamperError: 呈现内容与权威摘要不一致。
        """
        record = self.load(snapshot_id, owner_id=owner_id)
        if presented_digest:
            given = presented_digest
        else:
            given = compute_content_digest(
                presented_dictionaries or {}, presented_mappings or {}
            )
        if given != record.content_digest:
            raise SnapshotTamperError(
                f"工作簿字典／映射与权威快照不一致: {snapshot_id}"
            )
        return record

    # ── 分块上传缓冲 ──

    def _upload_root(self, owner_id: str) -> Path:
        """返回某归属下的分块上传根目录（owner 隔离）。"""
        return self.base_dir / "_uploads" / owner_id

    def _upload_meta_path(self, owner_id: str, upload_id: str) -> Path:
        """返回分块上传会话元数据路径。"""
        return self._upload_root(owner_id) / f"{upload_id}.json"

    def _upload_part_path(
        self, owner_id: str, upload_id: str, seq: int,
    ) -> Path:
        """返回单个分块的落盘路径。"""
        return self._upload_root(owner_id) / upload_id / f"{seq}.part"

    def _read_upload_meta(self, meta_p: Path) -> dict:
        """读取分块会话元数据；损坏视为不存在。"""
        try:
            return json.loads(meta_p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise UploadIncompleteError("分块上传会话元数据损坏") from exc

    def _write_upload_meta(self, meta_p: Path, meta: dict) -> None:
        """原子写分块会话元数据（临时文件 + os.replace）。"""
        meta_p.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            meta, ensure_ascii=False, indent=2
        ).encode("utf-8")
        tmp = meta_p.with_suffix(".json.tmp")
        tmp.write_bytes(payload)
        os.replace(tmp, meta_p)

    def _upload_expired(self, meta: dict) -> bool:
        """判断分块会话是否过期（无法解析到期时间视为过期）。"""
        try:
            expires = datetime.fromisoformat(str(meta.get("expires_at", "")))
        except ValueError:
            return True
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return self._now_fn() > expires

    def append_chunk(
        self, owner_id: str, upload_id: str, seq: int, data: bytes,
        *, is_last: bool = False,
    ) -> dict:
        """追加一个上传分片；首次追加隐式开启会话，末片置 is_last。

        Args:
            owner_id: 归属身份摘要（路径级隔离）。
            upload_id: 客户端选定的上传会话 ID。
            seq: 分片序号（非负）。
            data: 本分片原始字节。
            is_last: 是否为末片。

        Returns:
            含 upload_id / next_seq / received_chunks / received_bytes /
            is_last / complete 的会话状态。

        Raises:
            UploadLimitError: 参数缺失、分片或总字节超上限。
            UploadExpiredError: 既有会话已过期。
        """
        if not owner_id or not upload_id:
            raise UploadLimitError("owner_id 与 upload_id 不能为空")
        if seq < 0:
            raise UploadLimitError("seq 必须为非负整数")
        meta_p = self._upload_meta_path(owner_id, upload_id)
        if meta_p.exists():
            meta = self._read_upload_meta(meta_p)
            if self._upload_expired(meta):
                self.discard_upload(owner_id, upload_id)
                raise UploadExpiredError("分块上传会话已过期，请重新开始")
        else:
            created = self._now_fn()
            expires = created + timedelta(minutes=self.upload_ttl_minutes)
            meta = {
                "upload_id": upload_id,
                "owner_id": owner_id,
                "created_at": created.isoformat(timespec="seconds"),
                "expires_at": expires.isoformat(timespec="seconds"),
                "chunks": {},
                "is_last": False,
            }
        key = str(seq)
        if (
            key not in meta["chunks"]
            and len(meta["chunks"]) >= self.upload_max_chunks
        ):
            raise UploadLimitError("分块数量超过上限")
        part_p = self._upload_part_path(owner_id, upload_id, seq)
        part_p.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write_bytes(part_p, data)
        meta["chunks"][key] = len(data)
        total = sum(meta["chunks"].values())
        if total > self.upload_max_bytes:
            raise UploadLimitError("上传总字节超过上限")
        if is_last:
            meta["is_last"] = True
        self._write_upload_meta(meta_p, meta)
        received = sorted(int(k) for k in meta["chunks"])
        contiguous = received == list(range(len(received)))
        return {
            "upload_id": upload_id,
            "next_seq": (received[-1] + 1) if received else 0,
            "received_chunks": len(received),
            "received_bytes": total,
            "is_last": bool(meta["is_last"]),
            "complete": bool(meta["is_last"] and contiguous),
        }

    def read_merged_upload(self, owner_id: str, upload_id: str) -> bytes:
        """按 seq 顺序合并全部分片为完整字节，缺片则报错。

        Args:
            owner_id: 归属身份摘要。
            upload_id: 上传会话 ID。

        Returns:
            合并后的完整文件字节。

        Raises:
            UploadIncompleteError: 会话不存在、无分片或存在缺口。
            UploadExpiredError: 会话已过期。
        """
        meta_p = self._upload_meta_path(owner_id, upload_id)
        if not meta_p.exists():
            raise UploadIncompleteError("分块上传会话不存在或已过期")
        meta = self._read_upload_meta(meta_p)
        if self._upload_expired(meta):
            self.discard_upload(owner_id, upload_id)
            raise UploadExpiredError("分块上传会话已过期，请重新开始")
        seqs = sorted(int(k) for k in meta["chunks"])
        if not seqs:
            raise UploadIncompleteError("尚未收到任何分块")
        expected = list(range(max(seqs) + 1))
        missing = sorted(set(expected) - set(seqs))
        if missing:
            raise UploadIncompleteError(f"分块缺失: {missing}")
        parts: list[bytes] = []
        for s in expected:
            p = self._upload_part_path(owner_id, upload_id, s)
            if not p.exists():
                raise UploadIncompleteError(f"分块数据缺失: {s}")
            parts.append(p.read_bytes())
        return b"".join(parts)

    def discard_upload(self, owner_id: str, upload_id: str) -> None:
        """删除某分块上传会话的元数据与全部数据分片。"""
        if not owner_id or not upload_id:
            return
        root = self._upload_root(owner_id)
        try:
            (root / f"{upload_id}.json").unlink(missing_ok=True)
        except OSError:
            pass
        part_dir = root / upload_id
        if part_dir.exists():
            shutil.rmtree(part_dir, ignore_errors=True)

    def purge_expired_uploads(self) -> int:
        """回收所有归属下已过期的分块上传会话，返回清理数量。"""
        root = self.base_dir / "_uploads"
        if not root.exists():
            return 0
        purged = 0
        for meta_p in root.glob("*/*.json"):
            try:
                meta = json.loads(meta_p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if self._upload_expired(meta):
                owner_id = meta_p.parent.name
                upload_id = str(meta.get("upload_id") or meta_p.stem)
                self.discard_upload(owner_id, upload_id)
                purged += 1
        return purged

    # ── 清理 ──

    def purge_old_for_owner(self, owner_id: str) -> int:
        """同一归属只保留最新一份快照，删除其余旧快照。

        按 ``created_at`` 排序，保留最新一条，删除其余的元数据与模板文件。

        Args:
            owner_id: 归属身份摘要。

        Returns:
            被清理的快照数量。
        """
        if not owner_id or not self.base_dir.exists():
            return 0
        # 收集同一归属的所有快照
        entries: list[tuple[str, str]] = []  # (created_at, snapshot_id)
        for meta_path in self.base_dir.glob("*.json"):
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if str(data.get("owner_id", "")) != owner_id:
                continue
            snapshot_id = str(data.get("snapshot_id", "") or meta_path.stem)
            created_at = str(data.get("created_at", ""))
            entries.append((created_at, snapshot_id))
        if len(entries) <= 1:
            return 0
        # 按创建时间排序，保留最新一条
        entries.sort(key=lambda x: x[0])
        to_remove = entries[:-1]
        purged = 0
        for _created_at, snapshot_id in to_remove:
            for path in (self._meta_path(snapshot_id),
                         self._template_path(snapshot_id)):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            purged += 1
        return purged

    def purge_expired(self) -> int:
        """删除已过期快照的元数据与模板文件。

        Returns:
            被清理的快照数量。
        """
        if not self.base_dir.exists():
            return 0
        purged = 0
        for meta_path in self.base_dir.glob("*.json"):
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            record = SnapshotRecord.from_meta_dict(data)
            if self._is_expired(record):
                snapshot_id = record.snapshot_id or meta_path.stem
                for path in (meta_path, self._template_path(snapshot_id)):
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        pass
                purged += 1
        return purged
