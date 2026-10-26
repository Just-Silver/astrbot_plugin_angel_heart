<!-- 职责：AngelHeart 全链路提示词分层——秘书判定提示词、主脑请求提示词、用户可配置项与写死隐藏提示词各自的来源与注入点；不写：双防抖与状态机规则、上下文压缩算法、ProviderRequest 通用生命周期（见对应文档）。 -->

# 提示词分层与注入点

## 功能目标

固定一个事实：**AngelHeart 有两套互不相通的提示词**——秘书（判定）一套、主脑（生成）一套。用户能在 WebUI 改的只有其中极少数变量，其余全部写死。排查“为什么它不接话/为什么它这样说话”时，先确认是哪一套在起作用。

## 触发时机

讨论接话判定、人格偏离、提示词调优、新增配置项，或怀疑某段提示词“没生效/不该生效”时，以本文为准。

## 核心流程

### 一、秘书侧（判定是否接话）

秘书**没有 `system_prompt`**。`LLMAnalyzer._call_ai_model()` 用 `provider.text_chat(prompt=...)` 把整套模板作为**一条 user prompt** 发出。

组装顺序由 `PromptModuleLoader.build_prompt_template()` 固定，以 `\n\n---\n\n` 连接：

| 顺序 | 模块 | 内容 | 可配置性 | WebUI 位置 |
| --- | --- | --- | --- | --- |
| 1 | `prompts/modules/identity.md` | 角色设定、对话格式、政治敏感界定 | 仅 `{alias}`、`{ai_self_identity}` | 点名与交互 → 唤醒词；助理画像 → 自我身份设定 |
| 2 | `prompts/modules/behavior_rules.md` | 回应原则、发言频率、敏感话题、社交机制 | 写死 | 无 |
| 3 | `prompts/modules/decision_logic.md` | 步骤一必须回应、步骤二主动介入与社交资格审查 | 写死（`{alias}` 除外） | 无 |
| 4 | `prompts/modules/conversation_analysis.md` | 步骤三核心话题、步骤四重复与时机判断 | 写死 | 无 |
| 5 | `prompts/modules/strategy_generation.md` | 步骤五生成策略，含 `{reply_strategy_guide}` 槽位 | 槽位内容可配置 | 助理画像 → 回复策略指引 |
| 6 | `instruction_prompts.md` 或 `reasoning_prompts.md` | 输出字段、JSON 示例、对话模板 | 二选一由 `is_reasoning_model` 决定 | 全局配置 → 常规 → 只输出 JSON |

变量替换点（`_build_prompt`）：

- `{historical_context}` → `<已回应消息>`，`{recent_dialogue}` → `<未回应消息>`
- `{reply_strategy_guide}` → `personality.reply_strategy_guide`
- `{alias}` → `wake_interaction.alias`
- `{ai_self_identity}` → `personality.ai_self_identity`

有工作账本时再追加 `<助理工作账本>` 段并要求“不要让助理处理重复的问题”。

### 二、可配置项的真实作用范围

WebUI 入口：AstrBot 管理面板 → 插件 → 天使之心 → **「群聊独立配置」页**（`pages/chat-config`）。左侧选「全局配置」= 未绑定群聊的默认值，选某个模板 = 该模板的独立覆盖。分组顺序即下方「分组」列。同名字段在 AstrBot 原生插件配置页也有（全局配置与该页同源）。

| 配置项 | WebUI 分组 → 字段 | 落点 | 真实影响 |
| --- | --- | --- | --- |
| `personality.ai_self_identity` | 助理画像 → 自我身份设定 | `identity.md` 的 AI 自我身份 | 影响 `is_interesting` 的判定依据，**对“接不接话”最有效** |
| `personality.reply_strategy_guide` | 助理画像 → 回复策略指引 | `strategy_generation.md` 步骤五 | 只决定“怎么回”，**不参与门闩** |
| `wake_interaction.alias` | 点名与交互 → 唤醒词 | `identity.md`、`decision_logic.md` | 昵称与 @ 识别（`|` 分隔多个） |
| `wake_interaction.reply_even_not_questioned` | 点名与交互 → 非提问也回复 | `_parse_and_validate_decision` 后置校验 | 唯一硬开关：关掉后必须 `is_questioned` 或 `is_interesting` 才放行 |
| `reply_length.focus_instructions` | 回复长度 → 焦点触发词 | 入库 metadata 的 `focus` 命中 | 只切字数提醒档位，**不影响是否接话** |
| `is_reasoning_model` | 全局配置 → 常规 → 只输出 JSON | 切换第 6 模块 | 选 `instruction_prompts.md` 还是 `reasoning_prompts.md`，**仅在全局配置，模板里没有该项** |

> `reply_strategy_guide` 的字段 hint 写的是「告诉前台助理关心什么话题、什么情况该接话、什么时候别打扰」，但机制上它只进入步骤五。要真正控制时机，应改 `ai_self_identity`、`reply_even_not_questioned`，或直接改 `decision_logic.md` / `behavior_rules.md`。

### 三、写死的判定类提示词

- `behavior_rules.md`：「只回应明确提及我的人，绝对不参与任何未提及我的话题」
- `decision_logic.md` 步骤二：社交资格审查——「你不是那个人就不能主动介入」
- `conversation_analysis.md`：话题模糊/情绪化不介入、刚参与过无人回应则暂缓、多人同时发言等时机
- `identity.md` 政治敏感界定：限于中国大陆与台湾、建国后议题

已知张力：`behavior_rules.md` 的“绝不参与未提及我的话题”与 `decision_logic.md` 步骤二的“资格审查后可主动介入”互相冲突，实际行为偏向更保守一侧。

### 四、代码内硬编码提示词

| 位置 | 内容 |
| --- | --- |
| `front_desk._build_reply_length_reminder` | 常规/焦点字数提醒话术（字数可配，话术写死） |
| `rewrite_prompt_for_llm` | 群聊首条 user 消息 `这是一个群聊场景。`；私聊 system_prompt 追加角色设定 |
| `WorkLedger.format_for_secretary` / `format_for_assistant` | 工作账本第三人称/第二人称话术 |
| `ConversationLedger.generate_captions_for_chat` | 图片转述固定问法 |
| `ConversationLedger.describe_image` | 按需看图固定问法 |
| `ConversationLedger._build_private_summary_prompt` | 私聊上下文交接摘要四条要求 |
| `AngelDescribeImageTool.description` | 工具描述 |

### 五、主脑侧（生成回复）

- `req.system_prompt` = AstrBot 原生人格 + （仅私聊）角色扮演补充
- 群聊不追加 system_prompt，改为把 `这是一个群聊场景。` 作为首条 user 消息放进 `contexts`
- 秘书决策**不注入主脑请求体**，只挂在 `event.angelheart_context` 供日志与下游钩子读取
- 临时上下文仅两类：工作账本提醒、回复字数提醒

### 六、历史遗留

`core/utils/context_utils.py` 的 `format_decision_xml()`（`<系统决策>` XML）仍存在并被 `core/utils/__init__.py` 导出，但主脑请求链已不再调用（`FrontDesk._generate_final_prompt` 固定传 `decision=None`）。读代码时不要误以为它还在生效。

`LLMAnalyzer.__init__` 的 `strategy_guide` 参数从未被使用，实际取值走 `cm.reply_strategy_guide`（按群模板解析）。
