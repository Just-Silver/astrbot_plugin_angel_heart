<template>
  <div class="preview-pane">
    <!-- 助理画像：与配置 tab 共享同一份 draft 模型，改这里等于改配置 -->
    <n-card class="pv-card" :bordered="true">
      <template #header>
        <div class="pv-card-head">
          <span>助理的身份与关注范围</span>
          <n-button text size="tiny" @click="resetPersonality">
            <template #icon><Icon icon="lucide:rotate-ccw" /></template>
            恢复默认
          </n-button>
        </div>
      </template>

      <div v-for="field in personalityFields" :key="field.key" class="pv-field">
        <div class="pv-label">{{ field.label }}</div>
        <div class="pv-hint">{{ field.hint }}</div>
        <n-input
          v-model:value="personality[field.key]"
          type="textarea"
          :autosize="{ minRows: 3, maxRows: 8 }"
          :placeholder="field.placeholder"
        />
      </div>
    </n-card>

    <!-- 拼装结果 -->
    <n-card class="pv-card" :bordered="true">
      <template #header>
        <div class="pv-card-head">
          <span>拼装结果 · 5 步链路</span>
          <span class="pv-sub">上方字段已实时代入</span>
        </div>
      </template>

      <div class="pv-controls">
        <span class="pv-ctl-label">群聊</span>
        <n-select
          v-model:value="chatId"
          size="small"
          class="pv-ctl-select"
          :options="chatOptions"
          :consistent-menu-width="false"
        />
        <span class="pv-ctl-label pv-ctl-gap">模型</span>
        <span class="pv-ctl-value">{{ data?.meta?.is_reasoning_model ? '思维模型' : '普通模型' }}</span>
        <n-button size="tiny" quaternary :loading="loading" @click="load">
          <template #icon><Icon icon="lucide:refresh-cw" /></template>
        </n-button>
      </div>

      <n-alert v-if="data?.meta?.using_placeholder" type="warning" :bordered="false" class="pv-alert">
        未选择群聊或该群暂无对话记录，对话部分以 <code>&lt;占位&gt;</code> 标记展示结构。
      </n-alert>

      <div v-if="data" class="pv-timeline">
        <div
          v-for="(step, index) in data.steps"
          :key="step.key"
          class="pv-step"
          :class="{ muted: !step.injected, open: isOpen(step.key) }"
        >
          <div class="pv-dot" />
          <div class="pv-step-body">
            <div class="pv-step-head" @click="toggle(step)">
              <span class="pv-step-title">{{ index + 1 }} · {{ step.title }}</span>
              <span class="pv-badge" :class="step.injected ? 'inject' : 'none'">
                {{ step.injected ? '注入' : '不注入' }}
              </span>
              <span v-if="step.source" class="pv-source">{{ step.source }}</span>
            </div>
            <div class="pv-step-desc">{{ step.desc }}</div>

            <div v-if="step.note" class="pv-note">{{ step.note }}</div>

            <div v-else class="pv-expand">
              <div class="pv-expand-bar" @click="toggle(step)">
                <span>{{ isOpen(step.key) ? '收起' : '展开内容' }}</span>
                <span class="pv-count">{{ charCount(step.text) }} 字符</span>
              </div>
              <pre v-if="isOpen(step.key)" class="pv-code">{{ step.text }}</pre>
            </div>
          </div>
        </div>
      </div>
      <n-spin v-else-if="loading" style="margin: 32px auto; display: block" />
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { NAlert, NButton, NCard, NInput, NSelect, NSpin, useMessage } from 'naive-ui'
import { Icon } from '@iconify/vue'
import { GROUPS, type ChatStatusItem } from './fields'
import { useBridge } from './composables/useBridge'
import type { SchemaMeta } from './schema'

interface PreviewStep {
  key: string
  title: string
  desc: string
  injected: boolean
  source: string
  text: string
  note: string
}

interface PreviewData {
  steps: PreviewStep[]
  meta: {
    using_placeholder: boolean
    chat_id: string
    alias: string
    is_reasoning_model: boolean
    template_id: string
  }
}

const props = defineProps<{
  /** 与配置 tab 共享的 draft 模型（同一 ref，直接读写） */
  model: Record<string, Record<string, unknown>>
  schema: Record<string, SchemaMeta>
  chats: ChatStatusItem[]
  templateId?: string | null
  source: 'global' | 'template'
}>()

const { apiPost } = useBridge()
const message = useMessage()

const data = ref<PreviewData | null>(null)
const loading = ref(false)
// 展开状态按 step.key 独立记录，多个节点可同时展开
const openKeys = ref<Set<string>>(new Set(['secretary']))
// 默认选中第一个有对话记录的群聊：预览的意义就是看真实数据，不能默认落在占位模式
const chatId = ref<string>(firstChatWithData())

const personalityFields = computed(() => {
  const group = GROUPS.find((g) => g.key === 'personality')
  return group?.fields ?? []
})

// 直接代理到 draft，保证「预览里编辑」等于「配置里编辑」
const personality = computed<Record<string, unknown>>({
  get: () => props.model.personality ?? {},
  set: (value) => {
    props.model.personality = value
  },
})

const chatOptions = computed(() => [
  { label: '不指定（占位结构）', value: '' },
  ...props.chats.map((item) => ({
    label: item.display_name || item.chat_id,
    value: item.chat_id,
  })),
])

/** 默认选中第一个已知群聊：预览应优先展示真实数据，占位仅是兜底。 */
function firstChatWithData(): string {
  const first = props.chats[0]
  return first?.chat_id ?? ''
}

function charCount(text: string): string {
  return String((text || '').length).toLocaleString()
}

function isOpen(key: string): boolean {
  return openKeys.value.has(key)
}

function toggle(step: PreviewStep) {
  // Set 是浅比较，必须换新实例才能触发视图更新
  const next = new Set(openKeys.value)
  if (next.has(step.key)) next.delete(step.key)
  else next.add(step.key)
  openKeys.value = next
}

function resetPersonality() {
  const next: Record<string, unknown> = {}
  for (const field of personalityFields.value) {
    const meta = props.schema.personality?.items?.[field.key]
    next[field.key] = meta?.default ?? ''
  }
  props.model.personality = next
}

async function load() {
  loading.value = true
  try {
    const result = await apiPost<PreviewData>('prompt_preview/draft', {
      template_id: props.templateId || '',
      chat_id: chatId.value || '',
      draft: props.model,
    })
    data.value = result
  } catch (e) {
    message.error(`预览失败: ${(e as Error).message}`)
  } finally {
    loading.value = false
  }
}

// 草稿变化即重算：切到预览 tab 看到的就是当前值，不用手点刷新
watch(
  () => JSON.stringify(props.model),
  () => {
    void load()
  },
)

onMounted(() => {
  void load()
})
</script>

<style scoped>
.preview-pane {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.pv-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.pv-sub {
  font-size: 12px;
  color: var(--text-3);
  font-weight: 400;
}
.pv-field + .pv-field {
  margin-top: 16px;
}
.pv-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-1);
  margin-bottom: 3px;
}
.pv-hint {
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.5;
  margin-bottom: 7px;
}
.pv-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.pv-ctl-label {
  font-size: 12px;
  color: var(--text-3);
}
.pv-ctl-gap {
  margin-left: 8px;
}
.pv-ctl-select {
  width: 220px;
  max-width: 100%;
}
.pv-ctl-value {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-1);
}
.pv-alert {
  margin-bottom: 14px;
}
.pv-timeline {
  position: relative;
  padding-left: 22px;
}
.pv-timeline::before {
  content: '';
  position: absolute;
  left: 5px;
  top: 8px;
  bottom: 8px;
  width: 2px;
  background: var(--glass-divider);
}
.pv-step {
  position: relative;
  padding-bottom: 14px;
}
.pv-step:last-child {
  padding-bottom: 0;
}
.pv-dot {
  position: absolute;
  left: -21px;
  top: 4px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--glass-thick-bg);
  border: 2px solid var(--glass-divider);
  box-sizing: border-box;
}
.pv-step:not(.muted) .pv-dot {
  border-color: var(--accent);
  background: var(--accent);
}
.pv-step-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  cursor: pointer;
}
.pv-step-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-1);
}
.pv-step.muted .pv-step-title {
  color: var(--text-3);
  font-weight: 500;
}
.pv-badge {
  font-size: 10px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 4px;
}
.pv-badge.inject {
  background: var(--accent-soft);
  color: var(--accent);
}
.pv-badge.none {
  background: var(--glass-divider);
  color: var(--text-2);
}
.pv-source {
  font-size: 11px;
  color: var(--text-3);
}
.pv-step-desc {
  font-size: 12px;
  color: var(--text-2);
  line-height: 1.55;
  margin-top: 3px;
}
.pv-note {
  font-size: 11.5px;
  color: var(--text-3);
  margin-top: 6px;
  font-style: italic;
}
.pv-expand {
  margin-top: 7px;
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-xs);
  overflow: hidden;
}
.pv-expand-bar {
  display: flex;
  justify-content: space-between;
  padding: 6px 10px;
  font-size: 11.5px;
  color: var(--text-2);
  background: var(--bg-base);
  cursor: pointer;
}
.pv-count {
  color: var(--text-3);
}
.pv-code {
  margin: 0;
  padding: 11px 12px;
  font-family: inherit;
  font-size: 12.5px;
  line-height: 1.75;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 420px;
  overflow: auto;
  color: var(--text-1);
  background: var(--glass-thick-bg);
}

@media (max-width: 768px) {
  .pv-ctl-select {
    width: 100%;
  }
  .pv-code {
    font-size: 12px;
  }
}
</style>
