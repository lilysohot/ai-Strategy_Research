<script setup lang="ts">
/**
 * App shell: navigation + routed content + the always-visible disclaimer.
 *
 * Mobile-readable is a milestone acceptance item, so the layout is a single
 * column that collapses to a stacked drawer trigger under 768px rather than a
 * fixed sidebar that would squeeze the message column.
 *
 * Element Plus is registered globally in main.ts, so ``el-*`` tags resolve
 * without per-component imports.
 */
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import DisclaimerBar from '../components/DisclaimerBar.vue'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const activeMenu = computed(() => {
  const name = route.name
  return name === 'models' ? 'models' : 'chat'
})

async function onLogout(): Promise<void> {
  await auth.logout()
  await router.push({ name: 'login' })
}
</script>

<template>
  <ElContainer class="shell">
    <ElHeader class="shell__header" height="56px">
      <span class="shell__brand">投研 Agent</span>
      <nav class="shell__nav">
        <ElMenu
          :default-active="activeMenu"
          mode="horizontal"
          :ellipsis="false"
          class="shell__menu"
        >
          <ElMenuItem index="chat" @click="router.push({ name: 'chat' })">
            对话
          </ElMenuItem>
          <ElMenuItem index="models" @click="router.push({ name: 'models' })">
            模型配置
          </ElMenuItem>
        </ElMenu>
      </nav>
      <span class="shell__spacer" />
      <span v-if="auth.user" class="shell__user">{{ auth.user.username }}</span>
      <el-button link type="primary" @click="onLogout">退出</el-button>
    </ElHeader>

    <ElContainer class="shell__body">
      <ElMain class="shell__main">
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
}

.shell__header {
  display: flex;
  align-items: center;
  gap: 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  padding: 0 16px;
}

.shell__brand {
  font-weight: 600;
  font-size: 16px;
  white-space: nowrap;
}

.shell__nav {
  flex: 0 1 auto;
  min-width: 0;
}

.shell__menu {
  border-bottom: none;
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

/* Under 768px the horizontal menu collapses and the brand loses its padding
   rather than pushing the nav off-screen. */
@media (max-width: 768px) {
  .shell__header {
    padding: 0 8px;
    gap: 8px;
  }

  .shell__brand {
    font-size: 14px;
  }

  .shell__main {
    padding: 8px;
  }
}
</style>
