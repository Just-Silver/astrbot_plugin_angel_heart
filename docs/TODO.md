<!-- 职责：待办事项清单（发现了但这次不修的问题、验收中待办、后续计划）；不写：已完成的变更记录（见 CHANGELOG）、具体实现方案细节。 -->

# 待办清单

## 待修

### 提示词页每次渲染都重建 PromptModuleLoader（日志噪音，非 bug）

**现象**

`PromptModuleLoader.__init__` 每次构造都会读取 7 个文件并打 DEBUG，共 8 行：

```
[DBUG] core.prompt_module_loader:46: 成功加载模块: identity.md   ×7
[DBUG] core.prompt_module_loader:81: 组装提示词模板，使用 instruction_prompts.md，总长度: 3756
```

**实测频率（此前描述「刷屏」是夸大的，已更正）**

| 操作 | 触发次数 |
| --- | --- |
| 打开提示词页 | 1 次（`onMounted`） |
| 切换到提示词 tab 只看不操作 | 0 次 |
| 在页内改字 | 每次 1 次（`watch` 监听 draft） |
| 群消息巡检 | **0 次（已实测确认）** |

所以它不是持续刷屏，而是「每次进入/改字占 8 行」。

**真正会重建模板的三处**

| 位置 | 触发时机 |
| --- | --- |
| `core/llm_analyzer.py:76` `__init__` | 插件启动一次 |
| `core/llm_analyzer.py:107` `reload_config` | 保存配置一次 |
| `web_api/prompt_preview.py` `_render_secretary()` | 每次预览渲染一次 ← 只有这处是多余的 |

**已修（d652ff9）**

预览改为懒加载单例 `_get_preview_loader()`，同一进程只读一次文件。
属于降低日志噪音的优化，不影响功能。

**剩余观察**

AstrBot 控制台环形缓冲 `CACHED_SIZE = 500`（`astrbot/core/log.py:33`，硬编码不可配）。
高频改字预览仍会占用缓冲，若以后影响排查，再把预览的模块加载日志降级为不打印。

## 待验收

- 2.2.11-beta.2 的完整验收清单见 [`docs/acceptance_2.2.11.md`](acceptance_2.2.11.md)，当前进度：第 1 项（chat_id 告警）已通过。

## 待决策

### `decision_logic.md` 步骤二的「有犹豫就必须 false」

`prompts/modules/decision_logic.md` 第 35 行：

> 如果步骤一不满足……或对是否应该主动介入有任何犹豫，你的 `should_reply` 决策必须为 `false`。

与已修的 `behavior_rules.md`「绝对不参与未提及话题」属于同类抑制。本轮先只改最直接的一处，等 beta 实测接话率后再决定是否放宽。

**放宽方向**（若确认仍偏保守）：把「确认不合适」与「单纯没把握」区分开，仅前者放弃。
