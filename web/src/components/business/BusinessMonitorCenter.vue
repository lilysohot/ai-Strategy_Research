<script setup lang="ts">
import SessionMonitor from './SessionMonitor.vue'
import { useSessionsStore } from '@/stores/sessions'
const sessions = useSessionsStore()
</script>

<template>
  <section class="monitor-center">
    <h2>价格监控</h2>
    <p>每个会话在实验阶段可设置一个当前监控。取消后可以新建，历史触发记录继续保留。</p>
    <SessionMonitor v-if="sessions.activeId" :key="sessions.activeId" :research-id="sessions.activeId" />
    <p v-else>请先选择或新建一项研究，再为当前会话设置监控。</p>
  </section>
</template>

<style scoped>
.monitor-center { padding: 24px; }
</style>
