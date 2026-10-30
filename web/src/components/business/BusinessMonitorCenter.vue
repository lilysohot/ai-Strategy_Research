<script setup lang="ts">
import SessionMonitor from './SessionMonitor.vue'
import { useSessionsStore } from '@/stores/sessions'
const sessions = useSessionsStore()
</script>

<template>
  <section class="monitor-center">
    <h2>价格监控</h2>
    <p>每个会话最多设置三个长期监控目标，同轮达标只产生一个分析信号。取消后释放名额，历史记录保留。</p>
    <SessionMonitor v-if="sessions.activeId" :key="sessions.activeId" :research-id="sessions.activeId" />
    <p v-else>请先选择或新建一项研究，再为当前会话设置监控。</p>
  </section>
</template>

<style scoped>
.monitor-center { padding: 24px; }
</style>
