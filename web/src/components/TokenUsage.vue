<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ClickOutside as vClickOutside } from 'element-plus'
import { runs as runsApi } from '@/api'
import type { UsageTotals } from '@/utils/statusbar'
import { tokenBreakdown, type TokenUsageFields } from '@/utils/tokenUsage'

const props = defineProps<{
  runId: string | null
  liveUsage?: UsageTotals | null
  streaming?: boolean
}>()

const saved = ref<TokenUsageFields | null>(null)
const loading = ref(false)
const loadFailed = ref(false)
const pinned = ref(false)
const hovered = ref(false)
const focused = ref(false)
const visible = computed(() => pinned.value || hovered.value || focused.value)

// Each message owns its run's summary. Re-read on completion, and discard stale
// replies after a session/run switch. Refreshing the page uses persisted usage.
watch(() => [props.runId, props.streaming] as const, async ([runId, streaming], _, onCleanup) => {
  let current = true
  onCleanup(() => { current = false })
  saved.value = null
  loadFailed.value = false
  loading.value = false
  if (!runId || streaming) return
  loading.value = true
  try {
    const summary = await runsApi.get(runId)
    if (current) saved.value = summary.usage ?? null
  } catch {
    if (current) loadFailed.value = true
  } finally {
    if (current) loading.value = false
  }
}, { immediate: true })

const source = computed<TokenUsageFields | null>(() => {
  if (saved.value) return saved.value
  const live = props.liveUsage
  if (!live || live.total <= 0) return null
  return {
    prompt_tokens: live.prompt, completion_tokens: live.completion, total_tokens: live.total,
    cache_read_tokens: live.cacheRead, cache_write_tokens: live.cacheWrite,
    reasoning_tokens: live.reasoning,
  }
})
const usage = computed(() => tokenBreakdown(source.value))
const partial = computed(() => source.value?.status === 'partial')
const format = (n: number | null) => n === null ? '—' : n.toLocaleString('en-US')
const rows = computed(() => [
  { label: '输入', value: usage.value.input, kind: 'input', sub: false },
  { label: '缓存命中', value: usage.value.read, kind: 'read', sub: true },
  { label: '缓存未命中', value: usage.value.miss, kind: 'miss', sub: true },
  { label: '缓存写入', value: usage.value.write, kind: 'write', sub: true },
  { label: '输出', value: usage.value.output, kind: 'output', sub: false },
  { label: '思考过程', value: usage.value.reasoning, kind: '', sub: true },
  { label: '回复内容', value: usage.value.reply, kind: '', sub: true },
])
const segments = computed(() => {
  const { input, read, write, miss } = usage.value
  if (!input || read === null || write === null || miss === null) return []
  return [
    { kind: 'read', width: read / input * 100 },
    { kind: 'write', width: write / input * 100 },
    { kind: 'miss', width: miss / input * 100 },
  ]
})
function close(): void {
  pinned.value = false
  hovered.value = false
  focused.value = false
}
function closeOutside(event: MouseEvent): void {
  if (event.target instanceof Element && event.target.closest('.token-usage-popover')) return
  close()
}
</script>

<template>
  <div v-click-outside="closeOutside" class="token-footer" data-testid="token-usage" :data-run-id="runId">
    <el-popover
      :visible="visible" placement="top-start" :width="302"
      popper-class="token-usage-popover" :show-arrow="false"
    >
      <template #reference>
        <button
          class="token-badge" type="button" aria-label="Token 消耗明细"
          :aria-expanded="visible" aria-haspopup="dialog"
          @mouseenter="hovered = true" @mouseleave="hovered = false"
          @focus="focused = true" @blur="focused = false"
          @click="pinned = !pinned; focused = false"
          @keydown.esc.stop="close"
        >
          <span aria-hidden="true">◉</span> Tokens: {{ partial ? '已知 ' : '' }}{{ format(usage.total) }}
          <span class="token-info" aria-hidden="true">ⓘ</span>
        </button>
      </template>
      <div
        class="token-panel" role="dialog" aria-label="Token 消耗明细"
        @mouseenter="hovered = true" @mouseleave="hovered = false"
        @keydown.esc.stop="close"
      >
        <div class="token-heading"><strong>Token 消耗明细</strong><span>总计 <b>{{ format(usage.total) }}</b></span></div>
        <div v-for="row in rows" :key="row.label" class="token-row" :class="{ sub: row.sub, separator: row.kind === 'output' }">
          <span><i v-if="row.kind" class="token-dot" :class="row.kind" />{{ row.label }}</span>
          <strong>{{ format(row.value) }}</strong>
        </div>
        <div class="token-row separator"><span>⚡ 缓存命中率</span><strong class="token-rate">{{ usage.hitRate === null ? '—' : `${usage.hitRate.toFixed(1)}%` }}</strong></div>
        <div v-if="segments.length" class="token-bar" aria-hidden="true">
          <span v-for="segment in segments" :key="segment.kind" :class="segment.kind" :style="{ width: `${segment.width}%` }" />
        </div>
        <div class="token-legend"><span><i class="token-dot read" />命中</span><span><i class="token-dot write" />写入</span><span><i class="token-dot miss" />未命中</span></div>
        <p class="token-note">
          {{ loading ? '正在读取本次运行用量…' : loadFailed ? '暂时无法读取用量，请刷新后重试。' : usage.total === null ? '模型服务尚未提供用量数据。' : streaming ? '本次运行已报告的累计用量，结束后更新最终统计。' : partial ? '部分用量未提供，仅展示已知消耗。' : '本次运行累计用量；思考消耗包含在输出中。' }}
        </p>
      </div>
    </el-popover>
  </div>
</template>

<style scoped>
.token-footer { grid-column: 2; min-width: 0; }
.token-badge { display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--line);
  border-radius: 16px; padding: 3px 9px; background: var(--bg-raised); color: var(--text-soft);
  font: inherit; font-size: 12px; font-variant-numeric: tabular-nums; cursor: pointer; }
.token-badge:hover, .token-badge:focus-visible { border-color: var(--accent); outline: none; }
.token-info { color: var(--muted); }
.token-panel { color: var(--text); font-size: 12px; font-variant-numeric: tabular-nums; }
.token-heading, .token-row { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.token-heading { margin-bottom: 10px; }
.token-heading > span, .token-row.sub, .token-legend, .token-note { color: var(--muted); }
.token-heading b, .token-row strong { color: var(--text-soft); }
.token-row { margin: 6px 0; }
.token-row.sub { padding-left: 18px; }
.token-dot { display: inline-block; width: 9px; height: 9px; border-radius: 2px; margin-right: 7px; }
.input { background: #4b9bff; } .output { background: #c084fc; }
.read { background: #2dce9c; } .write { background: #e9df80; } .miss { background: #fa6885; }
.separator { border-top: 1px solid var(--line); padding-top: 10px; margin-top: 10px; }
.token-row .token-rate { color: #2dce9c; }
.token-bar { display: flex; height: 6px; overflow: hidden; border-radius: 8px; margin: 10px 0; }
.token-legend { display: flex; gap: 15px; font-size: 11px; }
.token-note { font-size: 11px; line-height: 1.5; margin: 10px 0 0; }
@media (max-width: 640px) { .token-footer { grid-column: 1; } }
</style>

<style>
.el-popover.el-popper.token-usage-popover { max-width: calc(100vw - 32px); box-sizing: border-box;
  background: var(--bg-raised); border-color: var(--line-strong); border-radius: 6px;
  padding: 12px; box-shadow: 0 8px 28px #0004; }
</style>
