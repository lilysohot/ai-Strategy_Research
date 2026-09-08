<script setup lang="ts">
/**
 * Fixed compliance disclaimer (FR-4 / requirements-user-layer.md §6 合规).
 *
 * Rendered by the app shell so it cannot be forgotten on a new page and stays
 * visible while a run streams. The login page sits *outside* the shell (it has to
 * — the shell requires an authenticated user), so it renders the same component
 * with ``variant="inline"``; that is the only way the "every screen carries the
 * disclaimer" rule holds without duplicating the wording in two places.
 *
 * The text is intentionally a constant here rather than a prop: a caller-supplied
 * string is a caller that can quietly omit the disclaimer.
 */
withDefaults(defineProps<{ variant?: 'banner' | 'inline' }>(), { variant: 'banner' })
</script>

<template>
  <div
    class="disclaimer"
    :class="`disclaimer--${variant}`"
    role="note"
    aria-label="免责声明"
    data-testid="disclaimer"
  >
    本平台输出由 AI 生成，仅供参考，<strong>不构成投资建议</strong>。据此操作，风险自担。
  </div>
</template>

<style scoped>
.disclaimer {
  flex: 0 0 auto;
  padding: 6px 16px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-lighter);
  border-top: 1px solid var(--el-border-color-lighter);
  text-align: center;
}

.disclaimer strong {
  color: var(--el-color-warning);
}

/* Login / standalone pages: no shell chrome to sit under, so it floats at the
   bottom of the viewport instead. */
.disclaimer--inline {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 10;
  background: var(--el-fill-color);
  padding: 8px 16px;
}
</style>
