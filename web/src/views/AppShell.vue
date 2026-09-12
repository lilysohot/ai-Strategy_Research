<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import DisclaimerBar from '../components/DisclaimerBar.vue'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const isWorkbench = computed(() => route.name === 'chat')

async function onLogout(): Promise<void> {
  await auth.logout()
  await router.push({ name: 'login' })
}
</script>

<template>
  <ElContainer class="shell" :class="{ 'shell--workbench': isWorkbench }">
    <ElHeader v-if="!isWorkbench" class="shell__header" height="56px">
      <el-button text type="primary" @click="router.push({ name: 'chat' })">
        返回工作台
      </el-button>
      <span class="shell__spacer" />
      <span v-if="auth.user" class="shell__user">{{ auth.user.username }}</span>
      <el-button link type="primary" @click="onLogout">退出</el-button>
    </ElHeader>

    <ElContainer class="shell__body">
      <ElMain class="shell__main" :class="{ 'shell__main--workbench': isWorkbench }">
        <RouterView />
      </ElMain>
    </ElContainer>

    <DisclaimerBar />
  </ElContainer>
</template>

<style scoped>
.shell {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-app);
  color: var(--text);
}

.shell__header {
  display: flex;
  align-items: center;
  gap: 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  padding: 0 16px;
}

.shell__spacer {
  flex: 1 1 auto;
}

.shell__user {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
}

.shell__body {
  flex: 1 1 auto;
  min-height: 0;
}

.shell__main {
  padding: 16px;
  overflow: auto;
}

.shell__main--workbench {
  padding: 0;
  overflow: hidden;
}

/* Under 768px the horizontal menu collapses and the brand loses its padding
   rather than pushing the nav off-screen. */
@media (max-width: 768px) {
  .shell__header {
    padding: 0 8px;
    gap: 8px;
  }

  .shell__main {
    padding: 8px;
  }

  .shell__main--workbench {
    padding: 0;
  }
}
</style>
