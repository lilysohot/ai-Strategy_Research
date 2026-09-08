<script setup lang="ts">
/**
 * Activity timeline (cli-web-parity §5.3 / ticket P2.1).
 *
 * One row per tool call, terminal-style: status icon + tool name + duration +
 * one-line summary; a row expands to the full state / duration / call ID /
 * input-output detail. Data is the store's step buffer, fed by the live bridge
 * (tool_started / tool_finished) and the trajectory replay — the timeline is
 * purely a view over it, so a reconnect replays consistently for free.
 *
 * Status set mirrors the terminal Activity widget: running / done / error /
 * skipped (the call never ran) / interrupted (run ended with the call in
 * flight). A ``running`` row accumulates wall time in the browser from the
 * step's ``startedAt`` — the backend only sends a final ``ms``.
 */
import { computed, onUnmounted, ref, watch } from 'vue'

import type { RunStep } from '@/stores/runs'
import { statusLabel, statusTagType, stepSummary } from '@/utils/activity'
import { redactDeep, redactSecrets } from '@/utils/redact'

const props = defineProps<{ steps: RunStep[] }>()

/** Only tool calls form the activity timeline (thinking/text stay in chat). */
const toolSteps = computed(() => props.steps.filter((s) => s.kind === 'tool'))

/** Shared 1 Hz tick that drives the running rows' elapsed timer. */
const now = ref(Date.now())
let timer: ReturnType<typeof setInterval> | null = null

const hasRunning = computed(() => toolSteps.value.some((s) => s.status === 'running'))

watch(
  hasRunning,
  (active) => {
    if (active && timer === null) {
      timer = setInterval(() => {
        now.value = Date.now()
      }, 1000)
    } else if (!active && timer !== null) {
      clearInterval(timer)
      timer = null
    }
  },
  { immediate: true },
)

onUnmounted(() => {
  if (timer !== null) clearInterval(timer)
})

function formatMs(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return '—'
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

/** Final ``ms`` when known, else the live elapsed clock for running rows. */
function durationOf(step: RunStep): string {
  if (typeof step.ms === 'number') return formatMs(step.ms)
  if (step.status === 'running' && step.startedAt) return formatMs(now.value - step.startedAt)
  return '—'
}

/**
 * Pretty-print for the expand area, with secrets masked first (defence in
 * depth: the relay already redacts replay server-side, but the platform
 * contract is "no plaintext key anywhere on screen" — the last rendering hop
 * enforces it too, since args/results routinely quote credentials).
 */
function pretty(value: unknown): string {
  if (value === undefined || value === null) return '—'
  if (typeof value === 'string') return redactSecrets(value)
  try {
    return redactSecrets(JSON.stringify(redactDeep(value), null, 2))
  } catch {
    return String(value)
  }
}
</script>

<template>
  <div class="activity">
    <el-empty
      v-if="!toolSteps.length"
      description="暂无工具调用（运行中产生的调用会实时出现在这里）"
      :image-size="60"
    />

    <el-collapse v-else class="activity__list">
      <el-collapse-item v-for="s in toolSteps" :key="s.id" :name="s.id">
        <template #title>
          <span class="activity__row" :class="`is-${s.status ?? 'running'}`">
            <el-tag size="small" :type="statusTagType(s.status)" class="activity__state">
              {{ statusLabel(s.status) || '…' }}
            </el-tag>
            <span class="activity__name">{{ s.name ?? 'tool' }}</span>
            <span class="activity__duration">{{ durationOf(s) }}</span>
            <span class="activity__summary">{{ redactSecrets(stepSummary(s)) }}</span>
          </span>
        </template>

        <dl class="activity__detail">
          <div class="activity__kv">
            <dt>状态</dt>
            <dd>{{ statusLabel(s.status) || '—' }}</dd>
          </div>
          <div class="activity__kv">
            <dt>耗时</dt>
            <dd>{{ durationOf(s) }}</dd>
          </div>
          <div class="activity__kv">
            <dt>Call ID</dt>
            <dd>
              <code>{{ s.callId || '—' }}</code>
            </dd>
          </div>
          <div class="activity__kv">
            <dt>输入</dt>
            <dd><pre class="activity__io">{{ pretty(s.input) }}</pre></dd>
          </div>
          <div class="activity__kv">
            <dt>输出</dt>
            <dd><pre class="activity__io">{{ pretty(s.output) }}</pre></dd>
          </div>
        </dl>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<style scoped>
.activity {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.activity__list {
  border-top: none;
  overflow-y: auto;
  max-height: 62vh;
}

.activity__row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1;
  padding-right: 8px;
}

.activity__state {
  flex: none;
}

.activity__name {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 13px;
  font-weight: 500;
  flex: none;
}

.activity__duration {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  flex: none;
  min-width: 48px;
}

.activity__summary {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

.activity__row.is-error .activity__name {
  color: var(--el-color-danger);
}

.activity__row.is-skipped .activity__name,
.activity__row.is-interrupted .activity__name {
  color: var(--el-text-color-placeholder);
}

.activity__detail {
  margin: 0;
  padding: 4px 8px 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.activity__kv {
  display: flex;
  gap: 10px;
  align-items: baseline;
}

.activity__kv dt {
  flex: none;
  width: 56px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.activity__kv dd {
  margin: 0;
  min-width: 0;
  flex: 1;
  font-size: 12px;
}

.activity__io {
  margin: 0;
  padding: 8px;
  background: var(--el-fill-color-light);
  border-radius: 6px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 240px;
  overflow-y: auto;
}
</style>
