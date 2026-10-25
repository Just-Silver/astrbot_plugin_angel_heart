"""上下文快照边界字段（historical_count）的契约测试。

消费方（天使之魂）依赖该字段切分当前连续块，缺失即退回猜测 role 结构。
"""

from __future__ import annotations

import json
from types import SimpleNamespace


def _decision() -> SimpleNamespace:
    return SimpleNamespace(
        should_reply=True,
        reply_strategy="测试",
        model_dump=lambda: {"should_reply": True, "reply_strategy": "测试"},
    )


def _record(role: str, content: str, timestamp: float) -> dict:
    return {
        "role": role,
        "content": content,
        "sender_id": "10001" if role == "user" else "assistant",
        "sender_name": "群友" if role == "user" else "助理",
        "timestamp": timestamp,
    }


def _serialize(records, historical_count=None):
    from astrbot_plugin_angel_heart.core.utils.context_utils import (
        json_serialize_context,
    )

    if historical_count is None:
        return json.loads(json_serialize_context(records, _decision()))
    return json.loads(
        json_serialize_context(records, _decision(), historical_count=historical_count)
    )


def test_snapshot_declares_historical_prefix_length():
    """有历史前缀时必须显式声明条数，消费方才能精确切分当前块。"""
    records = [
        _record("system", "[当前摘要]", 0.5),
        _record("user", "第一句", 1.0),
        _record("assistant", "第一答", 2.0),
        _record("user", "第二句", 3.0),
    ]

    payload = _serialize(records, historical_count=1)

    assert payload["historical_count"] == 1
    assert len(payload["chat_records"]) == 4


def test_snapshot_without_historical_prefix_declares_zero():
    """纯当前块快照必须声明 0，不能省略字段。"""
    records = [_record("user", "第一句", 1.0), _record("assistant", "第一答", 2.0)]

    payload = _serialize(records, historical_count=0)

    assert payload["historical_count"] == 0


def test_snapshot_defaults_to_zero_for_legacy_callers():
    """旧调用方不传该参数时也要输出字段，避免消费方拿到 None。"""
    records = [_record("user", "第一句", 1.0)]

    payload = _serialize(records)

    assert payload["historical_count"] == 0


def test_negative_historical_count_is_clamped():
    """非法值必须钳制为 0，避免消费方切出负数下标。"""
    records = [_record("user", "第一句", 1.0)]

    payload = _serialize(records, historical_count=-3)

    assert payload["historical_count"] == 0


def test_historical_count_beyond_length_is_preserved_for_consumer_check():
    """越界值原样输出，由消费方判定非法并退回兜底，而不是静默改写。"""
    records = [_record("user", "第一句", 1.0)]

    payload = _serialize(records, historical_count=99)

    assert payload["historical_count"] == 99
