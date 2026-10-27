"""离场应答（复读 / 热聊）的接话判定边界。

覆盖：
- 离场应答不受「仅点名入场」开关影响，也不因命中而进场
- 热聊只统计群友发言，助理自己的回复不凑人数
- 被写成 0 的阈值字段回退默认值，不让坏模板静默失效
"""

from __future__ import annotations

import time
import types
from unittest.mock import AsyncMock, MagicMock

import pytest
from astrbot_plugin_angel_heart.core.angel_heart_status import AngelHeartStatus, StatusChecker
from astrbot_plugin_angel_heart.core.config_manager import ConfigManager


class Plain:
    def __init__(self, text):
        self.text = text


class DummyEvent:
    def __init__(self, name="m1", text="哈哈"):
        self.message_obj = types.SimpleNamespace(message_id=name)
        self.unified_msg_origin = "aiocqhttp:GroupMessage:1"
        self.extras = {}
        self.is_at_or_wake_command = False
        self._text = text

    def set_extra(self, key, value):
        self.extras[key] = value

    def get_extra(self, key, default=None):
        return self.extras.get(key, default)

    def get_sender_id(self):
        return "u1"

    def get_sender_name(self):
        return "user1"

    def get_self_id(self):
        return "bot1"

    def get_message_outline(self):
        return self._text

    def get_messages(self):
        return [Plain(self._text)]

    def stop_event(self):
        pass


def make_config(leave=None, wake=None):
    leave_reply = {
        "leave_echo_reply": True,
        "leave_dense_reply": True,
        "echo_detection_threshold": 3,
        "echo_detection_window": 30,
        "dense_conversation_threshold": 30,
        "dense_conversation_window": 600,
        "min_participant_count": 5,
        "familiarity_cooldown_duration": 1800,
    }
    leave_reply.update(leave or {})
    wake_interaction = {
        "alias": "草王",
        "force_reply_when_summoned": True,
        "enter_on_mention_only": True,
    }
    wake_interaction.update(wake or {})
    return ConfigManager(
        {
            "analyzer_model": "mock-model",
            "timing": {"observation_timeout": 60},
            "energy": {},
            "wake_interaction": wake_interaction,
            "leave_reply": leave_reply,
            "access_control": {},
            "context_compression": {},
            "output_rewrite": {},
            "personality": {"ai_self_identity": "t", "reply_strategy_guide": ""},
        }
    )


def msg(sender_id, text="hi", age=0.0, role="user", kind=None):
    payload = {
        "role": role,
        "content": [{"type": "text", "text": text}],
        "sender_id": sender_id,
        "sender_name": sender_id,
        "timestamp": time.time() - age,
    }
    if kind:
        payload["kind"] = kind
    return payload


def build_checker(messages, **kwargs):
    angel = MagicMock()
    angel.conversation_ledger.get_all_messages.return_value = messages
    return StatusChecker(make_config(**kwargs), angel)


class TestLeaveReplyDoesNotDependOnEnterGate:
    """离场应答与「仅点名入场」是两个独立开关。"""

    @pytest.mark.parametrize("enter_on_mention_only", [True, False])
    @pytest.mark.asyncio
    async def test_leave_reply_detected_whatever_enter_gate(self, enter_on_mention_only):
        from astrbot_plugin_angel_heart.roles.front_desk import FrontDesk

        angel = MagicMock()
        angel.astr_context = MagicMock()
        angel.config_manager = make_config(wake={"enter_on_mention_only": enter_on_mention_only})
        angel.get_chat_status.return_value = AngelHeartStatus.NOT_PRESENT
        angel.is_present.return_value = False
        angel.is_leave_reply_in_cooldown.return_value = False
        angel.debounce_manager.schedule = AsyncMock(return_value=None)
        angel.debounce_manager.get_debounce_kind.return_value = "secretary"
        angel.debounce_manager.get_must_reply.return_value = False
        angel.transition_to_status = AsyncMock()
        angel.conversation_ledger.get_all_messages.return_value = []

        fd = FrontDesk(angel.config_manager, angel)
        fd.status_checker._detect_echo_chamber = MagicMock(return_value=True)

        await fd._schedule_group_debounce(DummyEvent())

        kwargs = angel.debounce_manager.schedule.await_args.kwargs
        assert kwargs["leave_reply_trigger"] == "echo_chamber"
        # 离场应答只回一次，不许顺手把助理拉进场
        assert kwargs["is_present"] is False

    @pytest.mark.asyncio
    async def test_leave_reply_reply_keeps_not_present(self):
        """命中离场应答后即使「仅点名入场」关闭，也不得转成在场。"""
        from astrbot_plugin_angel_heart.roles.front_desk import FrontDesk

        angel = MagicMock()
        angel.astr_context = MagicMock()
        angel.config_manager = make_config(wake={"enter_on_mention_only": False})
        angel.get_chat_status.return_value = AngelHeartStatus.NOT_PRESENT
        angel.is_present.return_value = False
        angel.is_leave_reply_in_cooldown.return_value = False
        angel.debounce_manager.schedule = AsyncMock(return_value=None)
        angel.debounce_manager.get_debounce_kind.return_value = "secretary"
        angel.debounce_manager.get_must_reply.return_value = False
        angel.transition_to_status = AsyncMock()
        angel.conversation_ledger.get_all_messages.return_value = []

        fd = FrontDesk(angel.config_manager, angel)
        fd.status_checker._detect_echo_chamber = MagicMock(return_value=True)

        await fd._schedule_group_debounce(DummyEvent())

        angel.transition_to_status.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_wake_word_still_enters_normally(self):
        """点名入场路径不受影响：命中点名照常进场。"""
        from astrbot_plugin_angel_heart.roles.front_desk import FrontDesk

        angel = MagicMock()
        angel.astr_context = MagicMock()
        angel.config_manager = make_config()
        angel.get_chat_status.return_value = AngelHeartStatus.NOT_PRESENT
        angel.is_present.return_value = False
        angel.is_leave_reply_in_cooldown.return_value = False
        angel.debounce_manager.schedule = AsyncMock(return_value=None)
        angel.debounce_manager.get_debounce_kind.return_value = "assistant"
        angel.debounce_manager.get_must_reply.return_value = True
        angel.transition_to_status = AsyncMock()
        angel.conversation_ledger.get_all_messages.return_value = []

        fd = FrontDesk(angel.config_manager, angel)
        fd.status_checker.is_event_wake = MagicMock(return_value=True)
        fd.status_checker._detect_echo_chamber = MagicMock(return_value=True)

        await fd._schedule_group_debounce(DummyEvent(text="草王"))

        kwargs = angel.debounce_manager.schedule.await_args.kwargs
        assert kwargs["is_present"] is True
        # 点名走自己的路，不该被离场应答截走
        assert kwargs["leave_reply_trigger"] == ""
        fd.status_checker._detect_echo_chamber.assert_not_called()


class TestDenseConversationCounting:
    """热聊按「群友发言」计数，助理自己的话不算多人热聊。"""

    def test_assistant_messages_do_not_inflate_participants(self):
        users = [msg(f"u{i}", age=i) for i in range(4)]
        bot = [msg("assistant", age=i * 0.5, role="assistant") for i in range(26)]
        checker = build_checker(users + bot)
        # 20 条真人消息凑不满 30 条，assistant 的 26 条也不该补上
        assert checker._detect_dense_conversation("g1") is False

    def test_real_crowd_still_triggers(self):
        users = [msg(f"u{i % 6}", age=i) for i in range(30)]
        checker = build_checker(users)
        assert checker._detect_dense_conversation("g1") is True

    def test_summary_message_not_counted(self):
        users = [msg(f"u{i % 6}", age=i) for i in range(29)]
        summary = [msg("system", age=0.5, kind="context_summary")]
        checker = build_checker(users + summary)
        assert checker._detect_dense_conversation("g1") is False


class TestDetectionConfigFallback:
    """阈值被写成 0 时按默认值处理，坏模板不能静默关掉功能。"""

    @pytest.mark.parametrize(
        ("field", "attr", "expected"),
        [
            ("echo_detection_window", "echo_detection_window", 30),
            ("echo_detection_threshold", "echo_detection_threshold", 3),
            ("dense_conversation_threshold", "dense_conversation_threshold", 30),
            ("dense_conversation_window", "dense_conversation_window", 600),
            ("min_participant_count", "min_participant_count", 5),
            ("familiarity_cooldown_duration", "leave_reply_cooldown_duration", 1800),
        ],
    )
    def test_zero_falls_back_to_default(self, field, attr, expected):
        cm = make_config(leave={field: 0})
        assert getattr(cm, attr) == expected

    def test_echo_triggers_after_zero_window_template(self):
        """旧模板把窗口写成 0 时，复读仍应能按默认窗口成立。"""
        messages = [msg(f"u{i}", "哈哈哈", age=1) for i in range(3)]
        checker = build_checker(messages, leave={"echo_detection_window": 0})
        assert checker._detect_echo_chamber("g1") is True

    def test_dense_not_always_true_after_zero_thresholds(self):
        """旧模板把阈值写成 0 时，不能变成「空账本也算热聊」。"""
        checker = build_checker(
            [],
            leave={"dense_conversation_threshold": 0, "min_participant_count": 0, "dense_conversation_window": 0},
        )
        assert checker._detect_dense_conversation("g1") is False
