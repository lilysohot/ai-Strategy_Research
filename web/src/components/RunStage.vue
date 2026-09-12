<script setup lang="ts">
import { computed } from 'vue'

import { useRunStreamStore } from '@/stores/runs'

const props = defineProps<{
  elapsedLabel: string
  contextLabel: string
  toolCount: number
  diffLabel: string
  stopping: boolean
  detailsOpen: boolean
}>()

const emit = defineEmits<{
  stop: []
  retry: []
  toggleDetails: []
}>()

const runStream = useRunStreamStore()

const statusLabel = computed(() => {
  switch (runStream.status) {
    case 'queued':
      return '排队中'
    case 'running':
      return '执行中'
    case 'completed':
      return '已完成'
    case 'failed':
      return '失败'
    case 'stopped':
      return '已停止'
    default:
      return '空闲'
  }
})

const statusTone = computed(() => {
  switch (runStream.status) {
    case 'completed':
      return 'ok'
    case 'failed':
      return 'danger'
    case 'stopped':
      return 'quiet'
    case 'queued':
    case 'running':
      return 'active'
    default:
      return 'idle'
  }
})

const facts = computed(() =>
  [
    props.elapsedLabel,
    runStream.meta.pipelineId,
    runStream.meta.modelName,
    props.contextLabel ? `ctx ${props.contextLabel}` : '',
    props.toolCount ? `tools ${props.toolCount}` : '',
    runStream.steerQueued ? `插话 ${runStream.steerQueued}` : '',
    props.diffLabel,
  ].filter(Boolean),
)
</script>

<template>
  <section v-if="runStream.runId" class="run-stage" :class="`is-${statusTone}`" data-testid="run-stage">
    <div class="stage-main">
      <span class="stage-dot" aria-hidden="true" />
      <div class="stage-copy">
        <div class="stage-title">{{ statusLabel }}</div>
        <div class="stage-facts">
          <span v-for="f in facts" :key="f">{{ f }}</span>
        </div>
      </div>
    </div>

    <div class="stage-actions">
      <el-button
        v-if="runStream.isStreaming"
        size="small"
        type="danger"
        plain
        :loading="stopping"
        data-testid="stop-btn"
        @click="emit('stop')"
      >
        停止
      </el-button>
      <el-button
        v-else-if="runStream.lastError"
        size="small"
        plain
        data-testid="retry-btn"
        @click="emit('retry')"
      >
        重试
      </el-button>
      <el-button size="small" plain data-testid="detail-btn" @click="emit('toggleDetails')">
        {{ detailsOpen ? '收起过程' : '查看过程' }}
      </el-button>
    </div>
  </section>
</template>

<style scoped>
.run-stage {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--line);
  background: color-mix(in srgb, var(--bg-raised) 88%, black);
}

.stage-main {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 10px;
}

.stage-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  border: 1px solid currentColor;
  color: var(--quiet);
  flex: none;
}

.is-active .stage-dot {
  color: var(--accent);
  background: var(--accent);
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--accent) 14%, transparent);
}

.is-ok .stage-dot {
  color: var(--ok);
  background: var(--ok);
}

.is-danger .stage-dot {
  color: var(--danger);
  background: var(--danger);
}

.stage-copy {
  min-width: 0;
}

.stage-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--text);
}

.stage-facts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  color: var(--muted);
  font-size: 12px;
}

.stage-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: none;
}

@media (prefers-reduced-motion: no-preference) {
  .is-active .stage-dot {
    animation: pulse 1.4s ease-in-out infinite;
  }

  @keyframes pulse {
    0%, 100% {
      box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 12%, transparent);
    }
    50% {
      box-shadow: 0 0 0 7px color-mix(in srgb, var(--accent) 4%, transparent);
    }
  }
}

@media (max-width: 640px) {
  .run-stage {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
