<script setup lang="ts">
/**
 * Plan board (P2.4, cli-web-parity.md §5.2 as corrected by the user: the
 * data source is the add_task / update_task tool calls, not a todo tool).
 *
 * Like ActivityPanel this is a pure projection of the collected tool steps —
 * the fold in utils/plan.ts rebuilds the board from scratch on every change,
 * so replays and reconnects cannot desynchronise it.
 */

import { computed } from 'vue'

import type { RunStep } from '@/stores/runs'
import { buildPlan, planDoneCount, type PlanTaskStatus } from '@/utils/plan'

const props = defineProps<{ steps: RunStep[] }>()

const plan = computed(() => buildPlan(props.steps))
const done = computed(() => planDoneCount(plan.value))

const STATUS_META: Record<PlanTaskStatus, { label: string; tag: 'info' | 'warning' | 'success' | 'danger' }> = {
  open: { label: '待处理', tag: 'info' },
  in_progress: { label: '进行中', tag: 'warning' },
  resolved: { label: '完成', tag: 'success' },
  cancelled: { label: '取消', tag: 'danger' },
}
</script>

<template>
  <div class="plan" data-testid="plan-panel">
    <template v-if="plan.length">
      <div class="plan__bar">
        <span class="plan__count">进度 {{ done }}/{{ plan.length }}</span>
        <el-progress
          class="plan__bar-track"
          :percentage="Math.round((done / plan.length) * 100)"
          :stroke-width="8"
        />
      </div>

      <ul class="plan__list">
        <li v-for="t in plan" :key="t.id" class="plan__item" :class="`is-${t.status}`">
          <span class="plan__id">{{ t.id }}</span>
          <span class="plan__desc" :title="t.description">{{ t.description }}</span>
          <el-tag size="small" :type="STATUS_META[t.status].tag">
            {{ STATUS_META[t.status].label }}
          </el-tag>
        </li>
      </ul>
    </template>

    <el-empty v-else description="no plan yet（Agent 尚未调用 add_task）" :image-size="60" />
  </div>
</template>

<style scoped>
.plan {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.plan__bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.plan__count {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
}

.plan__bar-track {
  flex: 1;
}

.plan__list {
  list-style: none;
  margin: 0;
  padding: 0;
  overflow-y: auto;
}

.plan__item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  margin-bottom: 6px;
}

.plan__id {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  flex-shrink: 0;
}

.plan__desc {
  flex: 1;
  font-size: 13px;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.plan__item.is-cancelled .plan__desc {
  text-decoration: line-through;
  color: var(--el-text-color-placeholder);
}
</style>
