<script setup lang="ts">
import { computed, ref } from 'vue'

import type { SessionPlanPreview, WorkspaceArea } from '@/business-ui'
import BusinessMonitorCenter from './BusinessMonitorCenter.vue'
import BusinessNotificationCenter from './BusinessNotificationCenter.vue'
import BusinessProfileView from './BusinessProfileView.vue'
import BusinessRequestCenter from './BusinessRequestCenter.vue'

const props = defineProps<{
  area: Exclude<WorkspaceArea, 'research'>
  plans: readonly SessionPlanPreview[]
}>()
const emit = defineEmits<{
  navigate: [area: WorkspaceArea]
  toggleRail: []
}>()

const dirty = ref(false)

const meta = computed(() => {
  const entries = {
    profiles: { title: '交易账户资料', caption: '账户、计划关系与实际记录' },
    requests: { title: '待补资料与处理结果', caption: '按会话汇总的待办、冲突与业务回执' },
    monitoring: { title: '监控中心', caption: '创建、管理与观察后台规则' },
    notifications: { title: '通知', caption: '业务事件与可行动结果' },
  }
  return entries[props.area]
})
</script>

<template>
  <section class="business-workspace" :data-area="area">
    <header class="business-bar">
      <el-button class="rail-toggle" text @click="emit('toggleRail')">导航</el-button>
      <div class="business-title">
        <span>{{ meta.title }}</span>
        <small>{{ meta.caption }}</small>
      </div>
      <div class="business-status">
        <span v-if="dirty" class="dirty-mark">本页有未保存草稿</span>
        <span class="preview-mark">前端预览</span>
        <el-button size="small" plain @click="emit('navigate', 'research')">返回研究</el-button>
      </div>
    </header>

    <div class="business-body">
      <BusinessProfileView
        v-if="area === 'profiles'"
        :plans="plans"
        @dirty-change="dirty = $event"
      />
      <BusinessRequestCenter v-else-if="area === 'requests'" />
      <BusinessMonitorCenter v-else-if="area === 'monitoring'" />
      <BusinessNotificationCenter v-else @navigate="emit('navigate', $event)" />
    </div>
  </section>
</template>

<style scoped>
.business-workspace { min-width: 0; flex: 1 1 auto; display: flex; height: 100%; flex-direction: column; background: var(--bg-app); }
.business-bar { min-height: 58px; display: flex; align-items: center; gap: 10px; padding: 10px 16px; border-bottom: 1px solid var(--line); background: color-mix(in srgb, var(--bg-app) 92%, var(--accent) 8%); }
.business-title { min-width: 0; display: flex; flex-direction: column; }
.business-title span { font-weight: 700; }
.business-title small { color: var(--muted); }
.business-status { margin-left: auto; display: flex; align-items: center; gap: 10px; }
.preview-mark, .dirty-mark { padding: 3px 7px; border: 1px solid var(--line); border-radius: 999px; color: var(--muted); font-size: 11px; }
.preview-mark { border-color: color-mix(in srgb, var(--accent) 60%, var(--line)); color: var(--accent); }
.dirty-mark { border-color: color-mix(in srgb, var(--warning) 60%, var(--line)); color: var(--warning); }
.business-body { flex: 1; min-height: 0; overflow: auto; }
.rail-toggle { display: none; }
@media (max-width: 1023px) { .rail-toggle { display: inline-flex; } }
@media (max-width: 640px) {
  .business-bar { align-items: flex-start; padding: 9px 10px; }
  .business-title small { display: none; }
  .business-status { gap: 5px; }
  .dirty-mark { display: none; }
  .preview-mark { border: 0; padding-inline: 2px; }
}
</style>
