"""提示词预览：离线渲染一次群消息链路上的全部提示词注入点。

只读。不写账本、不改状态、不调 LLM，用真实组件（PromptModuleLoader /
WorkLedger / FrontDesk 的提醒构造）拼装，保证预览与线上一致。
"""

from __future__ import annotations

import time
from typing import Any

try:
    from astrbot.api import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)

# 无真实对话时的占位结构：只标明「这里会是一段消息」，绝不伪造内容与人名。
_PLACEHOLDER_HISTORY = [
    {
        "role": "user",
        "sender_id": "00000",
        "sender_name": "<群友甲>",
        "sender_role": "群友",
        "content": "<已回应消息占位>",
        "timestamp": 0,
        "chat_id": "preview:GroupMessage:0",
    },
]
_PLACEHOLDER_RECENT = [
    {
        "role": "user",
        "sender_id": "00001",
        "sender_name": "<群友乙>",
        "sender_role": "群友",
        "content": "<未回应消息占位>",
        "timestamp": 0,
        "chat_id": "preview:GroupMessage:0",
    },
]

# 预览节点定义：(key, 标题, 说明, 是否注入)
_STEPS = [
    {
        "key": "ingest",
        "title": "消息入账",
        "desc": "写入 ConversationLedger，同时记录命中列表",
        "injected": False,
        "source": "metadata.hits",
    },
    {
        "key": "debounce",
        "title": "防抖调度",
        "desc": "纯代码判断：未过入场门槛的消息在此丢弃，秘书根本不会被调用",
        "injected": False,
        "source": "",
    },
    {
        "key": "secretary",
        "title": "秘书判定是否接话",
        "desc": "7 个模块拼成一条 user prompt，输出 JSON 决策",
        "injected": True,
        "source": "prompts/modules/*.md",
    },
    {
        "key": "assistant",
        "title": "主脑生成回复",
        "desc": "重建上下文，追加场景说明、字数提醒与工作账本",
        "injected": True,
        "source": "roles/front_desk.py",
    },
    {
        "key": "send",
        "title": "发送",
        "desc": "输出清洗（Markdown 与句末句号），不涉及提示词",
        "injected": False,
        "source": "",
    },
]


def _now_ts() -> float:
    return time.time()


def _fill_placeholder_timestamps(messages: list[dict], base_ts: float) -> list[dict]:
    """占位消息补上递增时间戳，否则时间戳为 0 时格式化不出时间标签。"""
    filled = []
    for index, msg in enumerate(messages):
        item = dict(msg)
        item["timestamp"] = base_ts + index
        filled.append(item)
    return filled


class PromptPreviewBuilder:
    """按给定配置视图拼装 5 步链路中每一步的真实提示词。"""

    def __init__(self, config_manager, conversation_ledger, work_ledger):
        self.config_manager = config_manager
        self.conversation_ledger = conversation_ledger
        self.work_ledger = work_ledger

    def build(self, chat_id: str = "") -> dict[str, Any]:
        """返回 {steps: [...], meta: {...}}，每步带真实文本或空。"""
        real_dialogue = self._load_real_dialogue(chat_id)
        using_placeholder = not real_dialogue
        history, recent = real_dialogue if real_dialogue else self._placeholder_dialogue()

        steps = []
        for spec in _STEPS:
            step = dict(spec)
            step["text"] = ""
            step["note"] = ""
            if spec["key"] == "ingest":
                step["text"] = self._render_ingest(chat_id, recent)
            elif spec["key"] == "secretary":
                step["text"] = self._render_secretary(history, recent, chat_id)
            elif spec["key"] == "assistant":
                step["text"] = self._render_assistant(chat_id, recent)
            elif not spec["injected"]:
                step["note"] = "此环节不注入任何提示词"
            steps.append(step)

        return {
            "steps": steps,
            "meta": {
                "using_placeholder": using_placeholder,
                "chat_id": chat_id,
                "alias": self.config_manager.alias,
                "is_reasoning_model": bool(self.config_manager.is_reasoning_model),
            },
        }

    # ---------- 各步骤渲染 ----------

    def _render_ingest(self, chat_id: str, recent: list[dict]) -> str:
        """入账阶段没有提示词，展示命中判定的落点，解释 alias/focus 会变成什么。"""
        alias = self.config_manager.alias
        focus = self.config_manager.focus_instructions
        return (
            "入账不产生提示词，只写 metadata，供后续步骤读取：\n\n"
            f"  chat_id      = {chat_id or '（未选择群聊）'}\n"
            "  body_text    = 本条消息纯文本\n"
            f"  hits[alias]  = 命中唤醒词 {alias} 时记录\n"
            f"  hits[focus]  = 命中焦点词（{focus}）时记录"
        )

    def _render_secretary(self, history: list[dict], recent: list[dict], chat_id: str) -> str:
        """调用真实 LLMAnalyzer 拼装逻辑，但用预览配置视图，不发请求。"""
        from ..core.llm_analyzer import LLMAnalyzer

        analyzer = LLMAnalyzer.__new__(LLMAnalyzer)
        from ..core.prompt_module_loader import PromptModuleLoader

        analyzer.prompt_loader = PromptModuleLoader()
        analyzer.config_manager = self.config_manager
        analyzer.analyzer_model_name = ""
        analyzer.strategy_guide = ""
        analyzer.is_ready = True
        analyzer.json_parser = None
        analyzer.base_prompt_template = analyzer.prompt_loader.build_prompt_template(
            bool(self.config_manager.is_reasoning_model)
        )
        # 传真实 chat_id：_build_prompt 内部会再取一次 for_chat，传空会触发
        # 「漏传 chat_id」的 warning，并把未绑定群的场景误报成调用方错误。
        # 模板/草稿覆盖在 _get_grouped 里优先命中，不依赖这里传空。
        prompt = analyzer._build_prompt(
            historical_context=history,
            recent_dialogue=recent,
            work_ledger_text=self._secretary_ledger_text(),
            chat_id=chat_id,
        )
        return prompt

    def _render_assistant(self, chat_id: str, recent: list[dict]) -> str:
        """主脑侧 3 类临时注入，取自真实构造函数。"""
        ledger_text = self._assistant_ledger_text(chat_id)
        length_text = self._reply_length_text(chat_id, recent)
        scene = "这是一个群聊场景。"

        blocks = [
            "主脑请求体由三部分构成（system_prompt 沿用 AstrBot 原生人格，不在此展示）：\n",
            "① 首条 user 消息 · 场景说明",
            scene,
            "",
            "② 临时上下文 · 回复字数提醒",
            length_text,
            "",
            "③ 临时上下文 · 工作账本（本轮之外的其他工作）",
            ledger_text,
        ]
        return "\n".join(blocks)

    # ---------- 数据来源 ----------

    def _load_real_dialogue(self, chat_id: str) -> tuple[list[dict], list[dict]] | None:
        """有真实群聊且账本有消息时取快照，否则返回 None 走占位。"""
        if not chat_id or self.conversation_ledger is None:
            return None
        try:
            history, recent, _ = self.conversation_ledger.get_context_snapshot(chat_id, "")
        except Exception:
            return None
        if not history and not recent:
            return None
        return history, recent

    def _placeholder_dialogue(self) -> tuple[list[dict], list[dict]]:
        """占位结构：用 <占位> 标记展示消息块位置，绝不伪造内容或人名。"""
        base = _now_ts() - 120
        return (
            _fill_placeholder_timestamps(_PLACEHOLDER_HISTORY, base),
            _fill_placeholder_timestamps(_PLACEHOLDER_RECENT, base + 60),
        )

    def _secretary_ledger_text(self) -> str:
        if self.work_ledger is None:
            return ""
        try:
            # 预览没有真实 work_id，用空值让账本按「无本轮工作」渲染。
            return self.work_ledger.format_for_secretary("", current_work_id="")
        except Exception:
            return ""

    def _assistant_ledger_text(self, chat_id: str) -> str:
        if self.work_ledger is None:
            return ""
        try:
            return self.work_ledger.format_for_assistant(chat_id, current_work_id="")
        except Exception:
            return ""

    def _reply_length_text(self, chat_id: str, recent: list[dict]) -> str:
        """复用 FrontDesk 的真实提醒构造函数，避免预览文案与线上漂移。"""
        from ..roles.front_desk import FrontDesk

        try:
            desk = FrontDesk.__new__(FrontDesk)
            desk._config_manager = self.config_manager
            focus = any(
                str(m.get("role") or "").lower() != "assistant" and desk._message_has_focus_hit(m, chat_id)
                for m in (recent or [])
            )
            return desk._build_reply_length_reminder(focus, chat_id)
        except Exception as exc:
            logger.debug(f"AngelHeart: 预览回复长度提醒失败: {exc}")
            return ""
