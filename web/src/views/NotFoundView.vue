<script setup lang="ts">
/**
 * 404 page (T12): unknown deep links used to silently redirect to /, which read
 * as "the link worked but the app lost my place". Rendered inside the shell, so
 * the header nav stays available as a way out.
 */
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<template>
  <div class="not-found">
    <p class="not-found__code">404</p>
    <p class="not-found__text">页面不存在或链接已失效</p>
    <div class="not-found__actions">
      <el-button type="primary" @click="router.push({ name: 'chat' })">返回对话</el-button>
      <el-button text @click="router.back()">返回上一页</el-button>
    </div>
  </div>
</template>

<style scoped>
.not-found {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  text-align: center;
}

.not-found__code {
  font-size: 56px;
  font-weight: 700;
  color: var(--el-text-color-secondary);
  margin: 0;
  line-height: 1.2;
}

.not-found__text {
  color: var(--el-text-color-secondary);
  margin: 0 0 12px;
}

.not-found__actions {
  display: flex;
  gap: 8px;
}
</style>
