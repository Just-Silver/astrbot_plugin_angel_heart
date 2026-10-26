<!-- 职责：待办事项清单（发现了但这次不修的问题、验收中待办、后续计划）；不写：已完成的变更记录（见 CHANGELOG）、具体实现方案细节。 -->

# 待办清单

## 待修

### 提示词页重复加载 PromptModuleLoader 导致日志刷屏

**现象**

打开/切换提示词页、或在页内改字时，每次都重建 7 个模块并打印 DEBUG：

```
[DBUG] core.prompt_module_loader:46: 成功加载模块: identity.md   ×7
[DBUG] core.prompt_module_loader:81: 组装提示词模板，使用 instruction_prompts.md，总长度: 3756
```

每触发一次预览占 8 行。AstrBot 控制台环形缓冲只有 `CACHED_SIZE = 500`（`astrbot/core/log.py:33`，硬编码不可配），反复切换几十次就会把 `秘书决策` 这类真正要看的日志挤出去。

**根因**

`PromptModuleLoader.__init__` 会立即读取 7 个文件并打 DEBUG。任何 `new PromptModuleLoader()`
都会产生 8 行日志。目前有三个来源：

| 来源 | 位置 | 触发时机 | 频率 |
| --- | --- | --- | --- |
| 提示词页预览 | `web_api/prompt_preview.py` `_render_secretary()` 每次 `PromptModuleLoader()` | 切 tab、改字重算 | **高，每改一次字 8 行** |
| 配置保存 | `main.py:264/280` → `LLMAnalyzer.reload_config()` → `prompt_loader.reload_modules()` | WebUI 保存配置 | 低，可接受 |
| 插件启动 | `core/llm_analyzer.py:76` | 启动一次 | 一次性 |

其中只有**第一项**是需要修的用法错误：预览只是只读渲染，不该重建加载器。

**修法**

提示词页改为复用模块级单例：

```python
_PREVIEW_LOADER = PromptModuleLoader()   # 进程内只读一次 7 个文件
```

**影响面**：仅 `web_api/prompt_preview.py`，不涉及运行期链路。

**顺带**：`PromptModuleLoader` 本身已是「加载一次 + 显式 reload」的设计（只在 `__init__`
和 `reload_modules()` 读盘），预览侧每次 new 属于用法错误，不是设计缺陷。

**未决疑点**

实测日志出现相邻 0.6 秒的两次模板重建（`02:35:30.423`、`02:35:31.010`），
且时间点紧邻群消息巡检（`02:35:27`）。正常巡检不应重建模板，
需确认当时是否同时打开了提示词页并触发了两次草稿重算；若确认与群消息相关，
说明还有未定位的重建路径。

## 待验收

- 2.2.11-beta.2 的完整验收清单见 [`docs/acceptance_2.2.11.md`](acceptance_2.2.11.md)，当前进度：第 1 项（chat_id 告警）已通过。

## 待决策

### `decision_logic.md` 步骤二的「有犹豫就必须 false」

`prompts/modules/decision_logic.md` 第 35 行：

> 如果步骤一不满足……或对是否应该主动介入有任何犹豫，你的 `should_reply` 决策必须为 `false`。

与已修的 `behavior_rules.md`「绝对不参与未提及话题」属于同类抑制。本轮先只改最直接的一处，等 beta 实测接话率后再决定是否放宽。

**放宽方向**（若确认仍偏保守）：把「确认不合适」与「单纯没把握」区分开，仅前者放弃。
