<script setup lang="ts">
/**
 * Root component + top-level error boundary (T12).
 *
 * A render/lifecycle error in any descendant used to blank the whole page with
 * no way back. ``onErrorCaptured`` here intercepts it, swaps in a fallback page
 * with 重试 / 返回首页, and returns ``false`` so the error stops propagating.
 * Bumping ``treeKey`` on retry remounts the routed subtree from scratch — the
 * cleanest recovery a render error can get.
 */
import { onErrorCaptured, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()

const error = ref<{ message: string } | null>(null)
/** Remount key for the routed subtree; "重试" bumps it to force a fresh mount. */
const treeKey = ref(0)

onErrorCaptured((err) => {
  error.value = { message: err instanceof Error ? err.message : String(err) }
  // The page shows a one-line summary; the full evidence stays in the console.
  console.error('[ErrorBoundary]', err)
  return false
})

// Navigating away (browser back, header menu) is itself a valid recovery —
// don't keep showing the fallback for a view that is no longer mounted.
watch(
  () => router.currentRoute.value.fullPath,
  () => {
    if (error.value) {
      error.value = null
      treeKey.value++
    }
  },
)

function onRetry(): void {
  error.value = null
  treeKey.value++
}

function onGoHome(): void {
  error.value = null
  treeKey.value++
  void router.push({ name: 'chat' })
}
</script>

<template>
  <RouterView v-if="!error" :key="treeKey" />
  <div v-else class="error-page">
    <p class="error-page__code">:(</p>
    <h1 class="error-page__title">页面出错了</h1>
    <p class="error-page__hint">
      界面渲染时发生意外错误，可以重试或返回首页；若反复出现，请联系管理员并附上以下信息。
    </p>
    <pre class="error-page__detail">{{ error.message }}</pre>
    <div class="error-page__actions">
      <el-button type="primary" @click="onRetry">重试</el-button>
      <el-button @click="onGoHome">返回首页</el-button>
    </div>
  </div>
</template>

<style scoped>
.error-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 24px;
  text-align: center;
}

.error-page__code {
  font-size: 48px;
  font-weight: 700;
  color: var(--el-text-color-secondary);
  margin: 0;
}

.error-page__title {
  font-size: 20px;
  margin: 0;
}

.error-page__hint {
  max-width: 420px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  margin: 0;
}

.error-page__detail {
  max-width: 560px;
  max-height: 140px;
  overflow: auto;
  margin: 0;
  padding: 8px 12px;
  font-size: 12px;
  color: var(--el-color-danger);
  background: var(--el-fill-color-light);
  border-radius: 6px;
  text-align: left;
  white-space: pre-wrap;
  word-break: break-all;
}

.error-page__actions {
  display: flex;
  gap: 8px;
}
</style>
