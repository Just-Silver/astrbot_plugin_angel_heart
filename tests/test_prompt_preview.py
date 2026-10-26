"""提示词预览：渲染链路与配置解析。

覆盖业务规则：
- 预览必须用真实模板拼装，配置槽位被代入
- 模板优先于群聊绑定，未绑定时回退全局
- 没有真实对话时用样例，有则用真实快照
- 只读：不改状态
"""

import pytest
from astrbot_plugin_angel_heart.core.chat_profile import ChatProfileStore
from astrbot_plugin_angel_heart.core.config_manager import ConfigManager
from astrbot_plugin_angel_heart.core.work_ledger import WorkLedger
from astrbot_plugin_angel_heart.web_api.prompt_preview import PromptPreviewBuilder


def make_config(**overrides):
    base = {
        "personality": {
            "ai_self_identity": "我是一个测试用的身份定位",
            "reply_strategy_guide": "只聊编程",
        },
        "wake_interaction": {"alias": "小鲸鱼"},
        "reply_length": {
            "focus_instructions": "分析",
            "normal_reply_max_chars": 20,
            "focus_reply_max_chars": 200,
        },
        "is_reasoning_model": False,
    }
    for key, value in overrides.items():
        if isinstance(value, dict):
            base.setdefault(key, {}).update(value)
        else:
            base[key] = value
    return base


class FakeLedger:
    def __init__(self, history=None, recent=None):
        self._history = history or []
        self._recent = recent or []

    def get_context_snapshot(self, chat_id, boundary_message_id=""):
        return self._history, self._recent, 0.0


@pytest.fixture
def store(tmp_path):
    return ChatProfileStore(str(tmp_path))


def build_preview(store, config, ledger=None):
    cm = ConfigManager(config)
    cm.attach_profile_store(store)
    builder = PromptPreviewBuilder(cm, ledger or FakeLedger(), WorkLedger())
    return builder.build(chat_id="")


def test_preview_has_five_steps_in_pipeline_order(store):
    data = build_preview(store, make_config())
    assert [s["key"] for s in data["steps"]] == [
        "ingest",
        "debounce",
        "secretary",
        "assistant",
        "send",
    ]


def test_debounce_and_send_steps_inject_nothing(store):
    data = build_preview(store, make_config())
    by_key = {s["key"]: s for s in data["steps"]}
    for key in ("debounce", "send"):
        assert by_key[key]["injected"] is False
        assert by_key[key]["text"] == ""


def test_secretary_step_substitutes_configured_slots(store):
    """秘书 prompt 必须代入配置里的身份与策略，否则预览就是假的。"""
    data = build_preview(store, make_config())
    secretary = next(s for s in data["steps"] if s["key"] == "secretary")

    assert "我是一个测试用的身份定位" in secretary["text"]
    assert "只聊编程" in secretary["text"]
    assert "小鲸鱼" in secretary["text"]
    # 未替换的占位符说明拼装链路断了
    assert "{alias}" not in secretary["text"]
    assert "{reply_strategy_guide}" not in secretary["text"]


def test_secretary_step_contains_both_dialogue_blocks(store):
    data = build_preview(store, make_config())
    secretary = next(s for s in data["steps"] if s["key"] == "secretary")
    assert "<已回应消息>" in secretary["text"]
    assert "<未回应消息>" in secretary["text"]


def test_template_overrides_global_config(store):
    """按模板预览时，模板值必须盖掉全局值。"""
    tpl = store.create_template(
        "编程群",
        config={"personality": {"alias": "群里的猫", "reply_strategy_guide": "只答技术问题"}},
    )
    # 模板字段白名单会过滤 alias（属于 wake_interaction），这里验证策略字段生效
    cm = ConfigManager(make_config())
    cm.attach_profile_store(store)
    view = cm.for_template(tpl["id"])

    assert view.reply_strategy_guide == "只答技术问题"
    assert view.ai_self_identity == "我是一个测试用的身份定位"


def test_template_view_survives_inner_for_chat_lookup(store):
    """_build_prompt 会用空 chat_id 再取一次配置，模板绑定不能丢。"""
    tpl = store.create_template("T", config={"personality": {"reply_strategy_guide": "模板策略"}})
    cm = ConfigManager(make_config())
    cm.attach_profile_store(store)

    assert cm.for_template(tpl["id"]).for_chat("").reply_strategy_guide == "模板策略"


def test_unknown_template_falls_back_to_global(store):
    cm = ConfigManager(make_config())
    cm.attach_profile_store(store)
    assert cm.for_template("不存在的模板").reply_strategy_guide == "只聊编程"


def test_real_dialogue_is_used_when_ledger_has_messages(store):
    """有真实群聊数据时不能用样例冒充。"""
    ledger = FakeLedger(
        history=[],
        recent=[
            {
                "role": "user",
                "sender_id": "1",
                "sender_name": "真实群友",
                "content": "真实消息内容",
                "timestamp": 1700000000,
                "chat_id": "aiocqhttp:GroupMessage:1",
            }
        ],
    )
    cm = ConfigManager(make_config())
    cm.attach_profile_store(store)
    data = PromptPreviewBuilder(cm, ledger, WorkLedger()).build(chat_id="aiocqhttp:GroupMessage:1")

    assert data["meta"]["using_placeholder"] is False
    secretary = next(s for s in data["steps"] if s["key"] == "secretary")
    assert "真实消息内容" in secretary["text"]


def test_placeholder_used_when_no_real_messages(store):
    data = build_preview(store, make_config())
    assert data["meta"]["using_placeholder"] is True


def test_placeholder_never_invents_people_or_content(store):
    """没有真实数据时只能出现占位标记，不得伪造人名或对话内容。"""
    data = build_preview(store, make_config())
    secretary = next(s for s in data["steps"] if s["key"] == "secretary")

    assert "<群友甲>" in secretary["text"]
    assert "<群友乙>" in secretary["text"]
    assert "<已回应消息占位>" in secretary["text"]
    assert "<未回应消息占位>" in secretary["text"]
    # 编辑器里不许出现任何编造的对话文本
    for invented in ("阿澈", "小林", "tokio", "select 和 spawn"):
        assert invented not in secretary["text"]


def test_reasoning_model_switch_changes_output_module(store):
    """is_reasoning_model 决定第 6 模块，预览必须反映它。

    注意方向：推理模型自带思维链，所以走「指令」版（instruction_prompts）；
    普通模型才需要「思维链指引」版（reasoning_prompts）。
    """
    normal = build_preview(store, make_config(is_reasoning_model=False))
    reasoning = build_preview(store, make_config(is_reasoning_model=True))

    normal_text = next(s for s in normal["steps"] if s["key"] == "secretary")["text"]
    reasoning_text = next(s for s in reasoning["steps"] if s["key"] == "secretary")["text"]

    assert normal_text != reasoning_text
    assert "思维链指引" in normal_text
    assert "思维链指引" not in reasoning_text


def test_preview_is_read_only(store):
    """预览不得改动账本与工作账本状态。"""
    ledger = FakeLedger()
    work = WorkLedger()
    cm = ConfigManager(make_config())
    cm.attach_profile_store(store)
    PromptPreviewBuilder(cm, ledger, work).build(chat_id="g1")

    assert work.get_recent_works("g1") == []
    assert ledger._history == [] and ledger._recent == []


def test_draft_overrides_win_over_saved_config(store):
    """预览必须反映未保存的草稿，否则用户改完看不到效果。"""
    cm = ConfigManager(make_config())
    cm.attach_profile_store(store)
    draft = {"personality": {"reply_strategy_guide": "草稿里的新策略"}}

    view = cm.for_template("").with_overrides(draft)
    assert view.reply_strategy_guide == "草稿里的新策略"


def test_draft_overrides_do_not_leak_to_base_view(store):
    """覆盖层只作用于派生的预览视图，不能污染运行期配置。"""
    cm = ConfigManager(make_config())
    cm.attach_profile_store(store)
    cm.for_template("").with_overrides({"personality": {"reply_strategy_guide": "草稿"}})

    assert cm.reply_strategy_guide == "只聊编程"


def test_draft_overrides_survive_inner_for_chat_lookup(store):
    """_build_prompt 内部再取配置时，草稿覆盖同样不能丢。"""
    cm = ConfigManager(make_config())
    cm.attach_profile_store(store)
    view = cm.for_template("").with_overrides({"personality": {"reply_strategy_guide": "草稿策略"}})

    assert view.for_chat("").reply_strategy_guide == "草稿策略"


def test_draft_reaches_secretary_prompt(store):
    """端到端：草稿值必须出现在渲染出的秘书提示词里。"""
    cm = ConfigManager(make_config())
    cm.attach_profile_store(store)
    view = cm.for_template("").with_overrides({"personality": {"reply_strategy_guide": "草稿专属策略词"}})
    data = PromptPreviewBuilder(view, FakeLedger(), WorkLedger()).build(chat_id="")

    secretary = next(s for s in data["steps"] if s["key"] == "secretary")
    assert "草稿专属策略词" in secretary["text"]


def test_reasoning_switch_missing_key_defaults_to_instruction():
    """缺键时必须与 _conf_schema.json 的 default(true) 一致，否则会静默切到思维链版。"""
    cm = ConfigManager({"personality": {}})
    assert cm.is_reasoning_model is True


def test_draft_can_toggle_reasoning_switch(store):
    """「只输出 JSON」是顶层键，草稿改了预览必须跟着换模块。"""
    cm = ConfigManager(make_config(is_reasoning_model=True))
    cm.attach_profile_store(store)

    on = PromptPreviewBuilder(cm, FakeLedger(), WorkLedger()).build("")
    off_view = cm.with_overrides({"is_reasoning_model": False})
    off = PromptPreviewBuilder(off_view, FakeLedger(), WorkLedger()).build("")

    on_text = next(s for s in on["steps"] if s["key"] == "secretary")["text"]
    off_text = next(s for s in off["steps"] if s["key"] == "secretary")["text"]

    assert "思维链指引" not in on_text
    assert "思维链指引" in off_text


def test_preview_without_chat_does_not_warn_missing_chat_id(store):
    """预览未选群聊是合法状态，不应报「调用方漏传 chat_id」。

    真实事件链漏传才有意义；预览报这条会把正常操作变成噪音。
    """
    from astrbot_plugin_angel_heart.core import config_manager as cm_module

    cm = ConfigManager(make_config())
    cm.attach_profile_store(store)

    # 测试环境 logger 是 MagicMock，直接对调用做断言
    cm_module.logger.warning.reset_mock()
    PromptPreviewBuilder(cm.for_template(""), FakeLedger(), WorkLedger()).build("")

    assert not any("漏传" in str(call) for call in cm_module.logger.warning.call_args_list)


def test_event_chain_still_warns_on_empty_chat_id(store):
    """运行期视图没有豁免：空 chat_id 仍然要暴露调用方问题。"""
    from astrbot_plugin_angel_heart.core import config_manager as cm_module

    cm = ConfigManager(make_config())
    cm.attach_profile_store(store)

    cm_module.logger.warning.reset_mock()
    cm.for_chat("")

    assert any("漏传" in str(call) for call in cm_module.logger.warning.call_args_list)


def test_preview_uses_real_chat_id_for_secretary(store):
    """秘书 prompt 用真实 chat_id 渲染，避免触发漏传告警。"""
    cm = ConfigManager(make_config())
    cm.attach_profile_store(store)
    data = PromptPreviewBuilder(cm.for_template(""), FakeLedger(), WorkLedger()).build("aiocqhttp:GroupMessage:1")

    assert data["meta"]["chat_id"] == "aiocqhttp:GroupMessage:1"
