<script setup lang="ts">
/**
 * Run diff panel (P2.5 §5.4) + revert (P3.3 §6.3).
 *
 * The parent owns the data (``GET /api/runs/{run_id}/diff``, already filtered by
 * ownership server-side). ``source: "file_tool"`` entries carry snapshot-based
 * unified hunks and are the ONLY ones that can be reverted; ``bash_scan``
 * entries are detection-only (real status, no hunks) and stay listed with the
 * reason they cannot be undone — a silently missing checkbox reads as a bug.
 */
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { runs as runsApi } from '@/api'
import { ApiError } from '@/api/client'
import type { DiffFile } from '@/types'
import {
  classifyDiffLines,
  diffStatusLabel,
  diffStatusTagType,
  summarizeDiff,
} from '@/utils/diff'
import {
  REVERT_SCAN_REASON,
  diffKey,
  isRevertable,
  revertTargets,
  summarizeRevert,
} from '@/utils/revert'

const props = defineProps<{ files: DiffFile[]; runId: string | null }>()

/** Emitted with the restored paths so the parent refreshes what it displays. */
const emit = defineEmits<{ reverted: [string[]] }>()

const summary = computed(() => summarizeDiff(props.files))

const expanded = ref<Set<string>>(new Set())

function toggle(key: string) {
  const next = new Set(expanded.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expanded.value = next
}

/** Distinct keys: a path can appear once per source; keep both rows stable. */
function keyOf(f: DiffFile): string {
  return diffKey(f)
}

function expandable(f: DiffFile): boolean {
  return f.hunks.length > 0
}

// ── P3.3 回滚 ────────────────────────────────────────────────────
const selected = ref<Set<string>>(new Set())
const reverting = ref(false)

/** What would actually be sent — scan rows are never in here. */
const targets = computed(() => revertTargets(props.files, selected.value))

function toggleSelect(key: string, on: boolean) {
  const next = new Set(selected.value)
  if (on) next.add(key)
  else next.delete(key)
  selected.value = next
}

/**
 * Reverting is destructive, so it says what it did: a mixed batch reports both
 * counts rather than pretending the refused rows went through.
 */
async function onRevert() {
  if (!props.runId || !targets.value.length || reverting.value) return
  reverting.value = true
  try {
    const res = await runsApi.revert(props.runId, targets.value)
    const outcome = summarizeRevert(res.results)
    selected.value = new Set()
    if (outcome.reverted) {
      ElMessage.success(`已回滚 ${outcome.reverted} 个文件`)
    }
    if (outcome.rejected) {
      ElMessage.warning(`${outcome.rejected} 个文件无法回滚，需手动处理`)
    }
    if (res.reverted.length) emit('reverted', res.reverted)
  } catch (err) {
    const msg =
      err instanceof ApiError && err.status === 409
        ? '该运行尚未结束，无法回滚'
        : err instanceof Error
          ? err.message
          : '回滚失败'
    ElMessage.error(msg)
  } finally {
    reverting.value = false
  }
}
</script>

<template>
  <div class="diff-panel" data-testid="diff-panel">
    <div class="diff-panel__summary" data-testid="diff-summary">
      {{ summary.files }} 个文件 ·
      <span class="diff-add-text">+{{ summary.additions }}</span>
      <span class="diff-del-text">−{{ summary.deletions }}</span>
    </div>

    <!-- P3.3 回滚操作条：只对有基线的 file_tool 行开放 -->
    <div v-if="files.length" class="diff-panel__bar">
      <el-button
        size="small"
        type="danger"
        plain
        :disabled="!targets.length || reverting"
        :loading="reverting"
        data-testid="diff-revert-btn"
        @click="onRevert"
      >
        回滚所选{{ targets.length ? `（${targets.length}）` : '' }}
      </el-button>
      <span class="diff-panel__note" data-testid="diff-revert-note">
        仅文件工具写入的改动可回滚
      </span>
    </div>

    <el-empty
      v-if="!files.length"
      description="本次运行没有文件变更"
      :image-size="60"
    />

    <ul v-else class="diff-panel__list">
      <li
        v-for="f in files"
        :key="keyOf(f)"
        class="diff-panel__item"
      >
        <div class="diff-panel__row">
          <el-checkbox
            v-if="isRevertable(f)"
            :model-value="selected.has(keyOf(f))"
            :disabled="reverting"
            data-testid="diff-revert-check"
            :aria-label="`选择回滚 ${f.path}`"
            @change="(v: boolean) => toggleSelect(keyOf(f), v)"
          />
          <span
            v-else
            class="diff-panel__hint"
            :title="REVERT_SCAN_REASON"
            data-testid="diff-scan-mark"
          >
            扫描
          </span>
          <button
            class="diff-panel__main"
            :disabled="!expandable(f)"
            data-testid="diff-file-row"
            @click="toggle(keyOf(f))"
          >
            <el-tag size="small" :type="diffStatusTagType(f.status)">
              {{ diffStatusLabel(f.status) }}
            </el-tag>
            <span class="diff-panel__path" :title="f.path">{{ f.path }}</span>
            <span class="diff-panel__stat">
              <span v-if="f.additions" class="diff-add-text">+{{ f.additions }}</span>
              <span v-if="f.deletions" class="diff-del-text">−{{ f.deletions }}</span>
            </span>
            <span v-if="expandable(f)" class="diff-panel__chevron">
              {{ expanded.has(keyOf(f)) ? '收起' : '展开' }}
            </span>
          </button>
        </div>

        <pre
          v-if="expandable(f) && expanded.has(keyOf(f))"
          class="diff-panel__hunks"
          data-testid="diff-hunks"
        ><code><span
          v-for="(line, i) in classifyDiffLines(f.hunks)"
          :key="i"
          class="diff-line"
          :class="`diff-line--${line.type}`"
        >{{ line.text }}
</span></code></pre>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.diff-panel__summary {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin-bottom: 10px;
}

.diff-add-text {
  color: var(--el-color-success);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.diff-del-text {
  color: var(--el-color-danger);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.diff-panel__list {
  list-style: none;
  margin: 0;
  padding: 0;
  overflow-y: auto;
  max-height: 62vh;
}

.diff-panel__item {
  margin-bottom: 6px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  overflow: hidden;
}

/* P3.3：左侧回滚选择 + 右侧展开按钮，两者是独立的可交互元素 */
.diff-panel__bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.diff-panel__note {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.diff-panel__row {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 6px 10px;
}

.diff-panel__main {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
  padding: 0;
  border: none;
  background: transparent;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.diff-panel__main:disabled {
  cursor: default;
}

.diff-panel__path {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
}

.diff-panel__stat {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}

.diff-panel__hint {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.diff-panel__chevron {
  flex-shrink: 0;
  font-size: 12px;
  color: var(--el-color-primary);
}

.diff-panel__hunks {
  margin: 0;
  padding: 8px 10px;
  background: var(--el-fill-color-light);
  border-top: 1px solid var(--el-border-color-lighter);
  overflow-x: auto;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  line-height: 1.5;
}

.diff-panel__hunks code {
  display: block;
  white-space: pre;
}

.diff-line {
  display: block;
}

.diff-line--add {
  background: var(--el-color-success-light-9);
  color: var(--el-color-success-dark-2);
}

.diff-line--del {
  background: var(--el-color-danger-light-9);
  color: var(--el-color-danger-dark-2);
}

.diff-line--hunk {
  color: var(--el-color-info);
}

.diff-line--meta {
  color: var(--el-text-color-secondary);
}
</style>
