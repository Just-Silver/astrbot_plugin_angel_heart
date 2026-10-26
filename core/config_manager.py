"""
AngelHeart 插件 - 配置管理器
用于集中管理插件的所有配置项。
支持新版嵌套 object 结构，兼容旧版扁平结构读取。
"""

try:
    from astrbot.api import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)


class ConfigManager:
    """
    配置管理器 - 提供对插件配置的中心化访问。

    配置格式（新版）：
    {
        "analyzer_model": "...",
        "timing": {"waiting_time": 30.0, ...},
        "leave_reply": {"leave_echo_reply": false, ...},
        ...
    }

    按群聊覆盖：通过 attach_profile_store() 挂载 ChatProfileStore 后，
    for_chat(chat_id) 返回的视图在读取模板字段时优先返回该群聊绑定模板的值，
    未出现在模板中的字段回退全局配置。
    """

    def __init__(self, config_data: dict):
        self._config = config_data or {}
        self._profile_store = None
        self._active_chat_id = ""
        # 直接按模板渲染（WebUI 提示词预览用），与 _active_chat_id 互斥且优先级更高。
        self._active_template_id = ""
        # 内存覆盖（WebUI 预览带入未保存草稿），优先级最高，从不落盘。
        self._overrides: dict = {}
        # 离线预览视图允许没有 chat_id，不按「调用方漏传」告警。
        self._allow_empty_chat = False

    def attach_profile_store(self, profile_store) -> None:
        """挂载群聊配置模板存储；重复挂载会替换旧引用。"""
        self._profile_store = profile_store

    def for_chat(self, chat_id: str) -> "ConfigManager":
        """返回按群聊覆盖的配置视图（共享全局配置与模板存储）。

        调用方应在事件处理链上显式传入 chat_id，禁止依赖 contextvar：
        防抖到期放行运行在 asyncio.create_task 的新任务中，上下文会丢失。

        chat_id 为空属于「无 ID 读取」异常路径，不静默回退全局，
        记 warning 暴露调用方漏传问题（不抛异常，避免打断运行时）。
        离线预览（for_template / with_overrides）本身就可能没有群聊，
        这类视图用 _allow_empty_chat 关掉该告警。
        """
        if not chat_id and not self._active_template_id and not self._allow_empty_chat:
            logger.warning("AngelHeart: for_chat 收到空 chat_id，本次读取将回退全局配置，请检查调用方是否漏传")
        view = ConfigManager(self._config)
        view._profile_store = self._profile_store
        view._active_chat_id = str(chat_id or "")
        # 下游（如 LLMAnalyzer._build_prompt）会用 for_chat("") 再取一次配置，
        # 这里必须把模板绑定与草稿覆盖带过去，否则预览拿到的就不是同一份值。
        view._active_template_id = self._active_template_id
        view._overrides = self._overrides
        view._allow_empty_chat = self._allow_empty_chat
        return view

    def for_template(self, template_id: str) -> "ConfigManager":
        """返回按指定模板渲染的配置视图，不依赖群聊绑定。

        只用于离线渲染（WebUI 提示词预览）；运行期事件链一律走 for_chat。
        """
        view = ConfigManager(self._config)
        view._profile_store = self._profile_store
        view._active_template_id = str(template_id or "")
        view._overrides = self._overrides
        view._allow_empty_chat = True
        return view

    def with_overrides(self, overrides: dict | None) -> "ConfigManager":
        """返回带内存覆盖的新视图（WebUI 预览用，不落盘）。

        覆盖按分组合并，只用于渲染，不参与任何运行期判断。
        """
        view = ConfigManager(self._config)
        view._profile_store = self._profile_store
        view._active_chat_id = self._active_chat_id
        view._active_template_id = self._active_template_id
        view._allow_empty_chat = True
        merged: dict = {}
        for source in (self._overrides, overrides or {}):
            if not isinstance(source, dict):
                continue
            for group, values in source.items():
                if isinstance(values, dict):
                    merged.setdefault(group, {}).update(values)
                else:
                    merged[group] = values
        view._overrides = merged
        return view

    def _template_override(self) -> dict | None:
        """当前视图直接绑定的模板覆盖值；未设置或模板已删时返回 None。"""
        if self._profile_store is None or not self._active_template_id:
            return None
        try:
            return self._profile_store.get_template_config(self._active_template_id)
        except Exception:
            return None

    def _get_grouped(self, group: str, key: str, default=None):
        """从分组中读取配置，兼容旧的扁平格式。

        优先级：内存覆盖 → 直接绑定的模板 → 当前群聊绑定模板 → 全局嵌套结构 → 旧扁平 key。
        """
        if isinstance(self._overrides, dict):
            grp = self._overrides.get(group)
            if isinstance(grp, dict) and key in grp:
                return grp[key]

        override = self._template_override()
        if override:
            grp = override.get(group)
            if isinstance(grp, dict) and key in grp:
                return grp[key]

        if self._profile_store is not None and self._active_chat_id:
            override = self._profile_store.resolve_override(self._active_chat_id)
            if override:
                grp = override.get(group)
                if isinstance(grp, dict) and key in grp:
                    return grp[key]
        # 优先从新的嵌套结构读取
        grp = self._config.get(group)
        if isinstance(grp, dict) and key in grp:
            return grp[key]
        # 回退到旧的扁平 key
        return self._config.get(key, default)

    def _get_top_level(self, key: str, default=None):
        """读取顶层键（不走分组），同样让位给内存覆盖。

        顶层键在旧格式里就是扁平 key（analyzer_model / is_reasoning_model 等），
        前端全局配置 draft 也是扁平结构，因此覆盖层按同名 key 直接命中。
        """
        if isinstance(self._overrides, dict) and key in self._overrides:
            return self._overrides[key]
        return self._config.get(key, default)

    # ========== 顶层配置 ==========

    @property
    def analyzer_model(self) -> str:
        return self._get_top_level("analyzer_model", "")

    @property
    def image_caption_provider_id(self) -> str:
        return self._get_top_level("image_caption_provider_id", "")

    @property
    def is_reasoning_model(self) -> bool:
        # 缺键时与 _conf_schema.json 的 default 保持一致（true = 走 instruction_prompts）。
        return bool(self._get_top_level("is_reasoning_model", True))

    # ========== timing ==========

    @property
    def waiting_time(self) -> float:
        return self._get_grouped("timing", "waiting_time", 30.0)

    @property
    def assistant_debounce_time(self) -> float:
        """点名等待时间（秒）。"""
        return self._get_grouped("timing", "assistant_debounce_time", 1.0)

    @property
    def secretary_debounce_time(self) -> float:
        """前台巡检最长等待时间（秒）。默认复用 waiting_time。"""
        return self._get_grouped("timing", "secretary_debounce_time", self.waiting_time)

    @property
    def accelerate_debounce_time(self) -> float:
        """连续点名加速等待时间（秒）。"""
        return self._get_grouped("timing", "accelerate_debounce_time", 1.0)

    @property
    def observation_timeout(self) -> int:
        return self._get_grouped("timing", "observation_timeout", 60)

    # ========== energy ==========

    @property
    def initial_energy(self) -> float:
        return self._get_grouped("energy", "initial_energy", 100.0)

    @property
    def max_energy(self) -> float:
        return self._get_grouped("energy", "max_energy", 100.0)

    @property
    def min_energy(self) -> float:
        return self._get_grouped("energy", "min_energy", -100.0)

    @property
    def recovery_per_second(self) -> float:
        return self._get_grouped("energy", "recovery_per_second", 0.6)

    @property
    def base_reply_cost(self) -> float:
        return self._get_grouped("energy", "base_reply_cost", 14.0)

    @property
    def reply_cost_per_character(self) -> float:
        return self._get_grouped("energy", "reply_cost_per_character", 0.12)

    # ========== reply_length ==========

    @property
    def focus_instructions(self) -> str:
        return self._get_grouped(
            "reply_length",
            "focus_instructions",
            "分析 总结 好好想想 为什么 到底",
        )

    @property
    def normal_reply_max_chars(self) -> int:
        raw = self._get_grouped("reply_length", "normal_reply_max_chars", 20)
        try:
            return max(1, int(raw))
        except (TypeError, ValueError):
            return 20

    @property
    def focus_reply_max_chars(self) -> int:
        raw = self._get_grouped("reply_length", "focus_reply_max_chars", 200)
        try:
            value = max(1, int(raw))
        except (TypeError, ValueError):
            value = 200
        return max(self.normal_reply_max_chars, value)

    # ========== leave_reply ==========

    @property
    def leave_echo_reply(self) -> bool:
        return self._get_grouped("leave_reply", "leave_echo_reply", False)

    @property
    def leave_dense_reply(self) -> bool:
        return self._get_grouped("leave_reply", "leave_dense_reply", False)

    @property
    def echo_detection_threshold(self) -> int:
        return self._get_grouped("leave_reply", "echo_detection_threshold", 3)

    @property
    def echo_detection_window(self) -> int:
        return self._get_grouped("leave_reply", "echo_detection_window", 30)

    @property
    def dense_conversation_threshold(self) -> int:
        return self._get_grouped("leave_reply", "dense_conversation_threshold", 30)

    @property
    def dense_conversation_window(self) -> int:
        return self._get_grouped("leave_reply", "dense_conversation_window", 600)

    @property
    def min_participant_count(self) -> int:
        return self._get_grouped("leave_reply", "min_participant_count", 5)

    @property
    def leave_reply_cooldown_duration(self) -> int:
        return self._get_grouped("leave_reply", "familiarity_cooldown_duration", 1800)

    # ========== wake_interaction ==========

    @property
    def enter_on_mention_only(self) -> bool:
        """仅点名入场：开启后离场时只有点名消息能进场，关闭后任何消息都入场处理。"""
        return self._get_grouped("wake_interaction", "enter_on_mention_only", True)

    @property
    def force_reply_when_summoned(self) -> bool:
        return self._get_grouped("wake_interaction", "force_reply_when_summoned", True)

    @property
    def reply_even_not_questioned(self) -> bool:
        return self._get_grouped("wake_interaction", "reply_even_not_questioned", True)

    @property
    def block_unapproved_wake_non_command(self) -> bool:
        return self._get_grouped("wake_interaction", "block_unapproved_wake_non_command", False)

    @property
    def alias(self) -> str:
        return self._get_grouped("wake_interaction", "alias", "AngelHeart")

    @property
    def slap_words(self) -> str:
        return self._get_grouped("wake_interaction", "slap_words", "")

    @property
    def speak_words(self) -> str:
        return self._get_grouped("wake_interaction", "speak_words", "张嘴")

    @property
    def silence_duration(self) -> int:
        return self._get_grouped("wake_interaction", "silence_duration", 600)

    # ========== access_control ==========

    @property
    def whitelist_enabled(self) -> bool:
        return self._get_grouped("access_control", "whitelist_enabled", False)

    @property
    def chat_ids(self) -> list:
        return self._get_grouped("access_control", "chat_ids", [])

    @property
    def group_chat_enhancement(self) -> bool:
        return self._get_grouped("access_control", "group_chat_enhancement", True)

    @property
    def takeover_private_chat_context(self) -> bool:
        return self._get_grouped("access_control", "takeover_private_chat_context", False)

    # ========== personality ==========

    @property
    def ai_self_identity(self) -> str:
        return self._get_grouped(
            "personality",
            "ai_self_identity",
            "你拥有强大的检索能力和庞大的知识储备和记忆能力。\n你喜爱跟群友进行语言游戏沟通。\n群友对AI的善意测试你必须回应满足群友的期待，展示你的能力。",
        )

    @property
    def reply_strategy_guide(self) -> str:
        return self._get_grouped("personality", "reply_strategy_guide", "")

    # ========== context_compression ==========

    @property
    def max_conversation_tokens(self) -> int:
        return self._get_grouped("context_compression", "max_conversation_tokens", 100000)

    @property
    def context_compression_threshold(self) -> float:
        return self._get_grouped("context_compression", "context_compression_threshold", 0.82)

    @property
    def context_content_retain_tokens(self) -> int:
        # 新 key: content_retain_tokens; 旧 key: context_content_retain_tokens
        grp = self._config.get("context_compression")
        if isinstance(grp, dict) and "content_retain_tokens" in grp:
            return grp["content_retain_tokens"]
        return self._config.get("context_content_retain_tokens", 10000)

    @property
    def context_tool_retain_tokens(self) -> int:
        grp = self._config.get("context_compression")
        if isinstance(grp, dict) and "tool_retain_tokens" in grp:
            return grp["tool_retain_tokens"]
        return self._config.get("context_tool_retain_tokens", 10000)

    @property
    def context_forgetting_timeout(self) -> int:
        grp = self._config.get("context_compression")
        if isinstance(grp, dict) and "forgetting_timeout" in grp:
            return grp["forgetting_timeout"]
        return self._config.get("context_forgetting_timeout", 86400)

    # ========== output_rewrite ==========

    @property
    def strip_markdown_enabled(self) -> bool:
        return self._get_grouped("output_rewrite", "strip_markdown_enabled", True)

    @property
    def strip_period_before_newline(self) -> bool:
        return self._get_grouped("output_rewrite", "strip_period_before_newline", False)

    # ========== 工具方法 ==========

    def get_config_summary(self) -> dict:
        return {
            "timing": {
                "waiting_time": self.waiting_time,
                "assistant_debounce_time": self.assistant_debounce_time,
                "secretary_debounce_time": self.secretary_debounce_time,
                "accelerate_debounce_time": self.accelerate_debounce_time,
                "cache_expiry": self.cache_expiry,
                "observation_timeout": self.observation_timeout,
            },
            "context_compression": {
                "max_conversation_tokens": self.max_conversation_tokens,
                "context_content_retain_tokens": self.context_content_retain_tokens,
                "context_tool_retain_tokens": self.context_tool_retain_tokens,
                "context_forgetting_timeout": self.context_forgetting_timeout,
            },
            "wake_interaction": {
                "alias": self.alias,
                "enter_on_mention_only": self.enter_on_mention_only,
                "force_reply_when_summoned": self.force_reply_when_summoned,
            },
            "reply_length": {
                "focus_instructions": self.focus_instructions,
                "normal_reply_max_chars": self.normal_reply_max_chars,
                "focus_reply_max_chars": self.focus_reply_max_chars,
            },
            "access_control": {
                "whitelist_enabled": self.whitelist_enabled,
                "group_chat_enhancement": self.group_chat_enhancement,
            },
        }
