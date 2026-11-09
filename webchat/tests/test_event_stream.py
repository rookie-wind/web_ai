"""SSE 增量读取：建连偏移、只读新增完整行、半行与缺失文件。"""

from __future__ import annotations

import json

from webchat.event_store import EventStore


def test_replay_with_offset_then_incremental(tmp_path):
    """建连偏移等于当前文件末尾；之后只读到新增事件。"""
    store = EventStore(tmp_path)
    store.append("s1", "text_delta", {"text": "a"})
    events, offset = store.replay_with_offset("s1")
    assert [e["payload"]["text"] for e in events] == ["a"]
    assert offset == (tmp_path / "s1.jsonl").stat().st_size

    # 无新增：偏移不变、事件为空
    more, same = store.read_after_offset("s1", offset)
    assert more == [] and same == offset

    store.append("s1", "text_delta", {"text": "b"})
    more, moved = store.read_after_offset("s1", offset)
    assert [e["payload"]["text"] for e in more] == ["b"]
    assert moved > offset


def test_replay_with_offset_filters_after_seq(tmp_path):
    """建连时仍按 after_seq 过滤历史，偏移始终指向文件末尾。"""
    store = EventStore(tmp_path)
    store.append("s1", "text_delta", {"text": "a"})
    store.append("s1", "text_delta", {"text": "b"})
    events, offset = store.replay_with_offset("s1", after_seq=1)
    assert [e["payload"]["text"] for e in events] == ["b"]
    assert offset == (tmp_path / "s1.jsonl").stat().st_size


def test_incremental_read_ignores_partial_line(tmp_path):
    """写入中的半行不解析，补齐换行后才下发。"""
    store = EventStore(tmp_path)
    store.append("s1", "text_delta", {"text": "a"})
    _, offset = store.replay_with_offset("s1")

    event = {
        "v": 1, "seq": 2, "session_id": "s1",
        "ts": 1.0, "type": "text_delta", "payload": {"text": "b"},
    }
    line = json.dumps(event).encode("utf-8")
    path = tmp_path / "s1.jsonl"
    with path.open("ab") as fp:
        fp.write(line[:10])  # 半行

    store._sizes.pop("s1", None)  # 绕过 append 直接写盘：让缓存按实际文件大小刷新
    more, same = store.read_after_offset("s1", offset)
    assert more == [] and same == offset

    with path.open("ab") as fp:
        fp.write(line[10:] + b"\n")
    more, moved = store.read_after_offset("s1", offset)
    assert [e["payload"]["text"] for e in more] == ["b"]
    assert moved == offset + len(line) + 1


def test_incremental_read_missing_file_keeps_offset(tmp_path):
    """文件不存在（会话未建/已删除）时安全返回空，不移动偏移。"""
    store = EventStore(tmp_path)
    more, same = store.read_after_offset("missing", 100)
    assert more == [] and same == 100
    events, offset = store.replay_with_offset("missing")
    assert events == [] and offset == 0
