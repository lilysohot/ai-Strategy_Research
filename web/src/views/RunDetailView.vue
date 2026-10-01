<script setup lang="ts">
/**
 * Run detail / trajectory timeline replay (T3.5).
 *
 * Source of truth is ``GET /api/runs/{run_id}/trace`` which returns the raw
 * ``react_agent.jsonl`` records. Each record carries a ``t`` discriminator:
 *   - ``start``      run bootstrap (model, tool set, max_turns)
 *   - ``llm``        one model turn: assistant content + tool_calls + usage
 *   - ``result``     a tool call result (name, ok/error, short result, ms)
 *   - ``compaction`` context compaction notice
 *
 * We render them as a vertical timeline. Content is treated as untrusted (it is
 * agent/LLM output) so assistant text goes through the shared markdown sanitizer.
 */

import { computed, ref, watch } from 'vue'

import { ApiError } from '@/api/client'
import { runs as runsApi } from '@/api'
import { renderMarkdown } from '@/utils/markdown'
import { redactDeep, redactSecrets } from '@/utils/redact'
import {
  initialResultChars,
  nextResultChars,
  resultView,
  thinkingLabel,
  thinkingView,
  type ThinkingView,
} from '@/utils/traceView'
import type { RunTraceRecord, TraceCompleteness } from '@/types'
import { useRunStreamStore } from '@/stores/runs'

const props = defineProps<{ runId: string | null }>()

const runStream = useRunStreamStore()

const records = ref<RunTraceRecord[]>([])
const loading = ref(false)
const errorMsg = ref('')
/** F06: null until the server reports it — never assume "complete". */
const completeness = ref<TraceCompleteness | null>(null)

const hasContent = computed(() => records.value.length > 0)

/**
 * F06: an interrupted run must say so. A `partial` trace is still readable, so
 * this is a warning beside the records, not an error that replaces them.
 */
const completenessNotice = computed(() => {
  const c = completeness.value
  if (!c || c.state === 'complete') return ''
  if (c.state === 'unavailable') return c.reason || '没有可读的轨迹记录'
  return c.reason || '运行未正常结束，已保存的记录可能缺少最后一部分内容'
})

async function load() {
  if (!props.runId) {
    records.value = []
    return
  }
  loading.value = true
  errorMsg.value = ''
  try {
    const res = await runsApi.trace(props.runId)
    records.value = res.records
    completeness.value = res.completeness ?? null
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      errorMsg.value = '该运行不存在或无权限查看'
    } else {
      errorMsg.value = err instanceof ApiError ? err.message : '加载轨迹失败'
    }
    records.value = []
    completeness.value = null
  } finally {
    loading.value = false
  }
}

// How many characters of each tool result the reader has unlocked. Keyed by
// record index, reset on every (re)load so a previous run's expansion state
// never leaks into the next one (F05: reading is progressive, not lossy).
const revealed = ref<Record<number, number>>({})

// Reload whenever the active run changes (drawer may be reused across runs).
watch(
  () => props.runId,
  (id) => {
    revealed.value = {}
    completeness.value = null
    if (id) load()
    else records.value = []
  },
  { immediate: true },
)

function kindLabel(t: string): string {
  switch (t) {
    case 'start':
      return '运行开始'
    case 'llm':
      return `第 ${(records.value.find((r) => r.t === 'llm')?.turn ?? '?')} 轮 · 模型`
    case 'result':
      return '工具结果'
    case 'compaction':
      return '上下文压缩'
    default:
      return t
  }
}

function renderContent(c: string | null | undefined): string {
  if (!c) return ''
  return renderMarkdown(c)
}

/**
 * Tool results are rendered as text, not markdown, so they do not pass through
 * ``renderMarkdown``'s redaction — a ``read_file`` of an env file would
 * otherwise print its secrets verbatim. Redact deeply (results can be objects)
 * before stringifying.
 *
 * Truncation is now *progressive* rather than a silent 300-char cut: the first
 * slice is a preview and each further slice is explicit, so an error that begins
 * at char 301 stays reachable (F05).
 */
function resultText(rec: RunTraceRecord): string {
  if (rec.result == null) return ''
  const safe = redactDeep(rec.result)
  return typeof safe === 'string' ? safe : JSON.stringify(safe)
}

function shownChars(i: number): number {
  return revealed.value[i] ?? initialResultChars()
}

function viewOf(rec: RunTraceRecord, i: number) {
  return resultView(resultText(rec), shownChars(i))
}

/** Unlock the next slice of one result. A button, so it is keyboard-reachable. */
function readMore(i: number): void {
  revealed.value[i] = nextResultChars(shownChars(i))
}

/**
 * Reasoning is shown only when it is prose. A turn with nothing recorded — or
 * one whose only reasoning is an encrypted/signed native block — gets an
 * explicit note instead of a fabricated explanation (F05).
 */
function thinkingOf(rec: RunTraceRecord): ThinkingView {
  return thinkingView({ thinking: rec.thinking, thinking_blocks: rec.thinking_blocks })
}

/** Readable reasoning text, or null when there is none to show. */
function thinkingText(rec: RunTraceRecord): string | null {
  const view = thinkingOf(rec)
  return view.state === 'visible' ? view.text : null
}

/** Note shown in place of reasoning when it is absent, empty or restricted. */
function thinkingNote(rec: RunTraceRecord): string {
  return thinkingLabel(thinkingOf(rec))
}

defineExpose({ load })
</script>

<template>
  <div class="run-detail">
    <el-alert
      v-if="errorMsg"
      :title="errorMsg"
      type="error"
      show-icon
      :closable="false"
    />

    <!--
      F06: completeness sits beside the records, not in place of them — a
      partial trace is still readable and must stay readable.
    -->
    <el-alert
      v-if="completenessNotice"
      :title="completenessNotice"
      type="warning"
      show-icon
      :closable="false"
    />

    <!--
      §6.4 P2：本次运行的工作目录（outputs/inputs 落点）+ 失败原因。
      Kept OUT of the v-if/else chain below: chaining it made the timeline the
      `v-else` branch, so any finished run (reconcile fills runDir) rendered the
      meta box *instead of* its records. Found by the F05 browser validation.
    -->
    <div v-if="runStream.runDir || runStream.errorMessage" class="run-detail__meta">
      <div v-if="runStream.runDir" class="run-detail__meta-row">
        <span class="run-detail__meta-label">运行目录</span>
        <code class="run-detail__meta-value">{{ runStream.runDir }}</code>
      </div>
      <div v-if="runStream.errorMessage" class="run-detail__meta-row run-detail__meta-error">
        <span class="run-detail__meta-label">失败原因</span>
        <span class="run-detail__meta-value">{{ runStream.errorMessage }}</span>
      </div>
    </div>

    <el-empty
      v-if="!loading && !hasContent"
      description="暂无轨迹记录（运行可能尚未产生输出）"
    />

    <div v-else v-loading="loading" class="timeline">
      <div v-for="(rec, i) in records" :key="i" class="tl-item" :class="`tl-${rec.t}`">
        <div class="tl-dot" />
        <div class="tl-body">
          <!-- start -->
          <template v-if="rec.t === 'start'">
            <div class="tl-head">
              <span class="tl-kind">运行开始</span>
              <span v-if="rec.model_name" class="tl-meta">模型：{{ rec.model_name }}</span>
            </div>
            <div v-if="rec.tool_names?.length" class="tl-tools">
              工具集：{{ rec.tool_names.join('、') }}
            </div>
            <div v-if="rec.max_turns" class="tl-meta">最大轮次：{{ rec.max_turns }}</div>
          </template>

          <!-- llm turn -->
          <template v-else-if="rec.t === 'llm'">
            <div class="tl-head">
              <span class="tl-kind">第 {{ rec.turn ?? '?' }} 轮 · 模型</span>
            </div>
            <div
              v-if="rec.content"
              class="tl-content bubble-assistant"
              v-html="renderContent(rec.content)"
            />
            <!--
              F05: the model's visible reasoning, collapsed by default (it can be
              long) and rendered as text — never as markdown, so it cannot inject
              markup. A turn without readable reasoning states why instead of
              showing an empty box.
            -->
            <details v-if="thinkingText(rec)" class="tl-thinking">
              <summary class="tl-thinking__summary">模型推理 / 说明</summary>
              <pre class="tl-thinking__body">{{ thinkingText(rec) }}</pre>
            </details>
            <div v-else class="tl-thinking-none">{{ thinkingNote(rec) }}</div>
            <div v-if="rec.tool_calls?.length" class="tl-toolcalls">
              <div v-for="(tc, j) in rec.tool_calls" :key="j" class="tl-toolcall">
                <code>{{ redactSecrets(tc.name ?? '') }}</code>
                <span v-if="tc.args" class="tl-args">{{ JSON.stringify(redactDeep(tc.args)) }}</span>
              </div>
            </div>
            <div v-if="rec.usage" class="tl-usage">
              tokens：prompt {{ rec.usage.prompt_tokens ?? 0 }} ·
              completion {{ rec.usage.completion_tokens ?? 0 }}
              <template v-if="rec.usage.cache_read_tokens != null">
                · cache_read {{ rec.usage.cache_read_tokens }}
              </template>
              <template v-if="rec.usage.cache_write_tokens != null">
                · cache_write {{ rec.usage.cache_write_tokens }}
              </template>
            </div>
          </template>

          <!-- result -->
          <template v-else-if="rec.t === 'result'">
            <div class="tl-head">
              <span class="tl-kind">工具结果</span>
              <el-tag
                v-if="rec.error === false"
                size="small"
                type="success"
              >成功</el-tag>
              <el-tag v-else-if="rec.error === true" size="small" type="danger">失败</el-tag>
              <span class="tl-meta">{{ rec.name }}</span>
              <span v-if="rec.ms != null" class="tl-meta">{{ rec.ms }}ms</span>
            </div>
            <!--
              F05: results keep a short preview, but the tail is never dropped
              silently — "继续读取" unlocks the next bounded slice so a failure
              message past char 300 stays reachable.
            -->
            <template v-if="rec.result != null">
              <pre class="tl-result">{{ viewOf(rec, i).visible }}</pre>
              <button
                v-if="viewOf(rec, i).hasMore"
                type="button"
                class="tl-result__more"
                @click="readMore(i)"
              >
                继续读取（还有 {{ viewOf(rec, i).hidden }} 字符，共
                {{ viewOf(rec, i).total }} 字符）
              </button>
            </template>
          </template>

          <!-- compaction / unknown -->
          <template v-else>
            <div class="tl-head">
              <span class="tl-kind">{{ kindLabel(rec.t) }}</span>
            </div>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.run-detail {
  height: 100%;
}

.run-detail__meta {
  margin-bottom: 12px;
  padding: 8px 12px;
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
  background: var(--el-fill-color-light);
  font-size: 13px;
}

.run-detail__meta-row {
  display: flex;
  gap: 8px;
  align-items: baseline;
  word-break: break-all;
}

.run-detail__meta-label {
  flex: 0 0 auto;
  color: var(--el-text-color-secondary);
}

.run-detail__meta-value {
  font-family: var(--el-font-family-mono, monospace);
}

.run-detail__meta-error .run-detail__meta-value {
  color: var(--el-color-danger);
}

.timeline {
  position: relative;
  padding-left: 18px;
  max-height: 70vh;
  overflow-y: auto;
}

.timeline::before {
  content: '';
  position: absolute;
  left: 5px;
  top: 4px;
  bottom: 4px;
  width: 2px;
  background: var(--el-border-color);
}

.tl-item {
  position: relative;
  margin-bottom: 16px;
}

.tl-dot {
  position: absolute;
  left: -18px;
  top: 4px;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--el-color-primary);
}

.tl-result ~ .tl-dot,
.tl-llm .tl-dot {
  background: var(--el-color-info);
}

.tl-start .tl-dot {
  background: var(--el-color-success);
}

.tl-compaction .tl-dot {
  background: var(--el-color-warning);
}

.tl-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 4px;
}

.tl-kind {
  font-weight: 600;
  font-size: 13px;
}

.tl-meta {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.tl-content {
  font-size: 13px;
  line-height: 1.6;
}

.tl-content :deep(pre) {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 8px;
  border-radius: 6px;
  overflow-x: auto;
}

.tl-tools,
.tl-usage {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 2px;
}

.tl-toolcalls {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-top: 4px;
}

.tl-toolcall {
  font-size: 12px;
}

.tl-toolcall code {
  background: var(--el-fill-color);
  padding: 1px 5px;
  border-radius: 4px;
  margin-right: 6px;
}

.tl-args {
  color: var(--el-text-color-secondary);
  word-break: break-all;
}

/* F05: collapsible reasoning. <details>/<summary> gives keyboard support and
   focus for free; long reasoning is collapsed by default. */
.tl-thinking {
  margin-top: 4px;
  font-size: 12px;
}

.tl-thinking__summary {
  cursor: pointer;
  color: var(--el-text-color-secondary);
  user-select: none;
}

.tl-thinking__summary:focus-visible {
  outline: 2px solid var(--el-color-primary);
  outline-offset: 2px;
}

.tl-thinking__body {
  margin: 4px 0 0;
  padding: 8px;
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 240px;
  overflow-y: auto;
}

.tl-thinking-none {
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}

/* F05: the "read more" control for truncated tool results. */
.tl-result__more {
  margin-top: 4px;
  padding: 2px 8px;
  font-size: 12px;
  color: var(--el-color-primary);
  background: transparent;
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
  cursor: pointer;
}

.tl-result__more:focus-visible {
  outline: 2px solid var(--el-color-primary);
  outline-offset: 2px;
}

.tl-result {
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 8px;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
  margin: 4px 0 0;
  max-height: 200px;
  overflow-y: auto;
}
</style>
