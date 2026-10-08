<script setup lang="ts">
/**
 * UI-06 用新资料重算 · DATA-05/06。
 *
 * 一键停止旧执行并排队一个新的 Run（POST /runs/{id}/rerun，幂等键防重）。
 * 旧轨迹与旧快照原样保留，只在成功建 Run 后提示；派发延迟不误报为资料丢失。
 */
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

import { runs as runsApi } from '@/api'
import { ApiError } from '@/api/client'

const props = defineProps<{
  runId: string | null
  disabled?: boolean
}>()

const emit = defineEmits<{
  rerunStarted: [runId: string]
}>()

const busy = ref(false)

let actionCounter = 0

async function rerun(): Promise<void> {
  if (!props.runId || busy.value) return
  const confirm = window.confirm(
    '将以当前最新资料重算本次分析：旧执行会停止并保留原轨迹与快照，另建一个新 Run。是否继续？',
  )
  if (!confirm) return
  busy.value = true
  const key = `rerun:${props.runId}:${Date.now()}:${actionCounter++}`
  try {
    const res = await runsApi.rerun(props.runId, {}, key)
    ElMessage.success('已用新资料重算并排队新 Run')
    emit('rerunStarted', res.run_id)
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      ElMessage.error('该运行不可重算（无业务快照或不存在）')
    } else {
      ElMessage.error(err instanceof Error ? err.message : '重算失败')
    }
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="analysis-rerun">
    <span>资料已变更时，可用当前最新值重新排队本次分析；原报告保留。</span>
    <el-button size="small" :disabled="disabled || busy || !runId" :loading="busy" @click="rerun">
      用新资料重算
    </el-button>
  </div>
</template>

<style scoped>
.analysis-rerun { display: flex; align-items: center; justify-content: flex-end; gap: 12px; color: var(--muted); font-size: 12px; }
</style>