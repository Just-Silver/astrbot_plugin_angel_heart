<!-- 职责：解释一次群聊/私聊回复中，AstrBot 核心与 AngelHeart 插件各自拥有哪部分数据、上下文由谁拼装、最终回复由谁生成与发送；不写：状态机与防抖调度细节（见 group_dual_debounce_state_machine.md）、上下文压缩算法（见 message_context_compression.md）、提示词模块分层（见 prompt_layers.md）。 -->

# LLM 请求归属：谁拼上下文、谁发起回复

## 功能目标

说清一次回复里两套系统的分工，避免把「主脑」当成插件内的第三个角色。所有关于缓存命中、上下文重建、事件放行的讨论都以本文为准。

## 结论摘要

| 环节 | 归属 |
| --- | --- |
| 加载持久化会话历史 | AstrBot 核心（读出来后被插件覆盖） |
| 拼装真正发给模型的上下文 | **AngelHeart 插件**（`ConversationLedger`） |
| 调用聊天模型 | AstrBot 核心 |
| 生成最终回复文本 | **AstrBot 核心**（插件的 5 处 LLM 调用都不产出回复） |
| 发送消息 | AstrBot 核心 |
| 决定「这一轮要不要回」 | AngelHeart 秘书（`should_reply`） |

「主脑」是口头称呼，指 **AstrBot 核心 + 用户配置的聊天模型**，不是插件内的独立组件。

## 为什么「主脑不是插件」

插件内所有模型调用都是辅助用途，没有一处生成回复：

| 位置 | 用途 |
| --- | --- |
| `core/llm_analyzer.py` `_call_ai_model` | 秘书决策，只返回 JSON |
| `core/conversation_ledger.py` 摘要 | 上下文压缩 |
| `core/conversation_ledger.py` 图片转述 | 已弃用，见下节 |
| `core/conversation_ledger.py` 图片理解工具 | 按需看图 |
| `roles/front_desk.py` `_text_chat` | 私聊摘要 |

最终回复文本来自 AstrBot 核心在 `on_llm_request` 钩子跑完之后发起的模型调用。

## 完整链路

```
入站消息
  ↓
① smart_reply_handler → _should_process
   戳一戳 / 上游命令 / @全体 / 自己发的 → 直接 return，不接手
  ↓
② FrontDesk 写入 ConversationLedger
  ↓
③ 防抖等待（群聊）
  ↓
④ 秘书决策（LLM 调用 #1）
   should_reply=False → event.stop_event()，链路终止，不产生任何回复
   should_reply=True  → 继续
  ↓
⑤ 事件放行，不再 stop_event
  ↓
⑥ AstrBot 核心接手：创建 ProviderRequest
   req.contexts = json.loads(conversation.history)     ← 核心自己的长会话
  ↓
⑦ 插件钩子 delegate_prompt_rewriting（priority=50）
   req.contexts = 账本重拼结果                          ← 整体替换，核心那份被丢弃
   req.prompt / req.system_prompt / req.image_urls 一并改写
  ↓
⑧ 核心用改写后的 req 调用模型（工具循环在同一轮内追加）
  ↓
⑨ 核心发送，本轮结束，写回自己的会话库
```

## 两套会话库并存

| | AstrBot 会话库 | AngelHeart 账本 |
| --- | --- | --- |
| 存储 | SQLite，`conversation.history` | 进程内 `ConversationLedger` |
| 键 | `unified_msg_origin` | `chat_id` |
| 写入方 | 核心 `_save_to_history` | 插件自己 |
| 读取方 | 核心（随后被插件覆盖） | 插件每轮真正使用 |
| 能力 | 只追加 | 可摘要压缩、带 sender/图片元数据 |

核心的库照常记录，但 AngelHeart 不使用它。原因：只有插件账本才能做摘要压缩、图片引用维护、sender 归一化。

## 关键代码位置

| 行为 | 位置 |
| --- | --- |
| 核心读会话历史 | `astrbot/core/astr_main_agent.py` `req.contexts = json.loads(conversation.history)` |
| 插件整体覆盖 | `roles/front_desk.py` `_update_request`，`req.contexts = contexts` |
| 覆盖前的重拼 | `roles/front_desk.py` `_build_contexts_with_processor` |
| 不回复时终止事件 | `roles/front_desk.py` `_call_secretary_and_execute` 内的 `event.stop_event()` |
| 核心写回历史 | `astrbot/.../agent_sub_stages/internal.py` `_save_to_history` |

## 对讨论的三条推论

**1. 事件一旦放行，就一定会回复。**

AstrBot 核心不会「看着办」。`should_reply=True` 之后走完 ⑧⑨，必然产生一条消息。所以任何「跳过秘书直接放行」的方案，代价都是**该消息必定得到回复**，不存在「放行但主脑可以不回」。

**2. 缓存命中不依赖「长会话追加」。**

每轮上下文都是重建的，但重建结果的前缀稳定（历史消息内容与顺序不变，只有尾部新增），因此服务端前缀缓存照样命中。实测秘书 79%、主脑 69% 的 cached 比例即此机制。

含义：**重建本身不费钱，重建得不稳定才费钱。** 触发上下文整理（如日志中的 `10 -> 2`）那一轮前缀会改变，缓存失效。

**3. 秘书看不到图片是结构性的。**

`_call_ai_model` 的调用是 `provider.text_chat(prompt=prompt)`，**签名上就没有传图片的位置**。这不是过滤，是秘书通道本身只有文本。

再叠加 `convert_content_to_string` 只取 `type == "text"` 的片段，`image_url` 被静默丢弃，于是：

| 消息 | 秘书看到 |
| --- | --- |
| `这个报错怎么解` + 截图 | `这个报错怎么解` |
| `好亮啊` + 照片 | `好亮啊` |
| 纯图片 | 空字符串 |

秘书甚至不知道这条消息带过图。

## 图片转述为什么是死代码

`core/conversation_ledger.py` 的 `process_image_captions_if_needed` 有完整实现（WEBP 压缩、dHash 缓存、降级），但**本仓库与上游都零调用方**。

上游 `CHANGELOG` 的现行说法是「新增按需图片理解工具：主模型需要某张图细节时，再调用 AngelHeart 的图片工具」。也就是说上游主动放弃了「预先把图转成文字喂给秘书」的路线，改走「主脑自己看图、需要细节再调工具」。

因此它属于**弃用遗留**，不是被改坏的调用链。
