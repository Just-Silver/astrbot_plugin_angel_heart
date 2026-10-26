<!-- 职责：本 fork 与上游的关系、上游修复的同步流程与追踪方式、改动禁区（减少长期冲突）；不写：上游代码本身的实现细节、本项目功能设计（见对应架构文档）。 -->

# 上游同步与维护策略

## 功能目标

固定本 fork 的维护边界：**不合并回上游，但持续吸收上游的 bug 修复**。本文说明为什么这么做、怎么追踪、以及怎么写代码才能让同步长期低成本。

## 触发时机

以下任一情形先读本文：

- 发现上游有新提交或新版本
- 准备修改 `roles/front_desk.py`、`core/conversation_ledger.py`、`core/angel_heart_status.py`、`main.py`
- 想新增功能，需要决定代码放哪里

## 核心判断

**不能放弃上游。**

| 理由 | 说明 |
| --- | --- |
| 上游是免费的 QA 通道 | 本 fork 实际使用者只有维护者一人，长尾 bug 基本踩不到；上游有真实用户群，它的 issue 与修复就是现成的 bug 探测结果 |
| 上游修复质量可用 | 2.2.9 / 2.2.10 的四处修复（#78 图片折叠丢失、#79 仅@卡住 300s、#82 摘要角色、#83 调度中清理图片）都是真实故障 |
| 同步成本可控 | 上游单个版本约 15 文件 / 600 行，按语义移植而非整包合并，工作量在可接受范围 |

## 为什么不能直接 merge

与「是不是 fork」无关。分叉点之后两边都在改同一批文件：

```
        a1e1b05 (2.2.8, fork 点)
        /                    \
  我方 master              上游 master
  67 文件 +1538/-1626      15 文件 +608/-27
```

冲突集中在双方都大改的三个文件：

| 文件 | 上游改动 | 我方改动 |
| --- | --- | --- |
| `roles/front_desk.py` | +58 | +124 / -271 |
| `core/conversation_ledger.py` | +111 / -13 | +84 / -116 |
| `main.py` | +12 | +58 / -131 |

`git merge` 报 8 处冲突，单提交 `cherry-pick` 仍然冲突。**直接合并的代价大于按语义移植。**

## 同步流程

1. **拉取上游**
   ```
   git fetch upstream --tags
   git log --oneline <上次同步点>..upstream/master
   ```
2. **逐提交评估价值**：读 commit message + `CHANGELOG.md` 差异，判断是 bug 修复（值得合）、纯重构（谨慎）、还是新功能（多半不要）。
3. **查冲突面**：`git diff --stat <同步点>..upstream/master`，对比我方改动过的文件。
4. **按语义手工移植**，不要 `cherry-pick`。移植时保留上游的注释与判断逻辑，只适配到本仓库的结构。
5. **必须连带移植上游的测试**。测试是上游给的 bug 探测能力，比代码本身更有长期价值。
6. **补一条 CHANGELOG 的「同步自上游」小节**，记录同步了哪些提交、原因是直接合并还是手工移植。
7. **更新同步点**：把 `docs/upstream_sync_point.txt` 改成上游最新提交 hash，下次检查才不会重复报告。
8. 跑完整门禁（`ruff check .`、`ruff format --check .`、`pytest`、`npm run build`）。

### 追踪记录

`docs/upstream_sync_point.txt` 保存**上次同步到的上游提交 hash**，`scripts/check_upstream.py` 默认以它为起点。每完成一次同步，把该文件改成上游最新提交。

不用 `merge-base` 作为默认起点：分叉点只是两个历史的分开处，不等于已经同步到哪，用它会把早已同步的提交反复报出来。

本文件末尾的「同步记录」表登记每次同步的区间与处理方式，供下次考古。

### 检查脚本的工作原理

```bash
git fetch upstream --tags        # 脚本不联网，必须先手动 fetch
python scripts/check_upstream.py
```

脚本只读本地 git 对象，跑三条命令：

| 命令 | 作用 |
| --- | --- |
| `git log --oneline <同步点>..upstream/master` | 列出新增提交 |
| `git diff --name-only <同步点>..upstream/master` | 上游改了哪些文件 |
| `git merge-tree --write-tree HEAD upstream/master` | **在内存里试算合并**，得到真实冲突文件列表 |

`merge-tree` 是关键：它不像 `git merge` 那样动工作区，也不像「双方都改过的文件清单」那样只是近似。它按三路合并算法真算一遍，输出需要人工裁决的文件——就是 `git merge` 时会报 `CONFLICT` 的那些。

因此脚本给出的冲突数是**当前 HEAD 对该上游版本的真实同步成本**。

## 降低长期冲突的三条规则

1. **少动上游频繁改动的文件**：`roles/front_desk.py`、`core/conversation_ledger.py`、`core/angel_heart_status.py`、`main.py`。必须改时保持改动小而准，避免整段重写。
2. **自有功能放在新文件**：如 `web_api/prompt_preview.py`、`webui/src/PreviewPane.vue` 这类上游不涉及的位置，天然零冲突。
3. **新增配置走既有加载路径**：往 `ConfigManager` 追加 property、往 `_conf_schema.json` 追加分组，而不是重构配置结构。

## 同步记录

| 同步日期 | 我方版本 | 上游区间 | 上游提交 | 处理方式 |
| --- | --- | --- | --- | --- |
| 2026-10-27 | 2.2.11-beta.1 | 2.2.8 → 2.2.10 | `8370a7b`(#79)、`6b01a43`(#82)、`63c0725`(#78 #83) | 手工移植；连带移植 `test_no_text_event_boundaries` / `test_summary_message_role` / `test_summary_image_refs` / `test_media_cleanup_defer` |
