<script setup lang="ts">
import { ref, watch } from 'vue'
import { runs } from '@/api'
import { redactDeep } from '@/utils/redact'

const props = defineProps<{ runId: string; status: string }>()
const audit = ref<unknown>(null)
const loading = ref(false)
const error = ref('')
let version = 0
watch(() => [props.runId, props.status], async () => {
  const current = ++version
  audit.value = null
  error.value = ''
  loading.value = true
  try {
    const result = await runs.audit(props.runId)
    if (current === version) audit.value = result.available ? redactDeep(result.audit) : null
  } catch {
    if (current === version) error.value = '核验记录加载失败，请重新打开此页重试。'
  } finally {
    if (current === version) loading.value = false
  }
}, { immediate: true })
</script>

<template>
  <section aria-label="核验记录" v-loading="loading">
    <p v-if="error" role="alert">{{ error }}</p>
    <template v-else-if="audit">
      <p>这里只记录具体检查与证据读取情况，不代表整份答案均已通过核验。</p>
      <details open>
        <summary>检查结果、证据关联与读取限制</summary>
        <pre class="audit-data">{{ JSON.stringify(audit, null, 2) }}</pre>
      </details>
    </template>
    <p v-else-if="!loading">尚无最终核验记录。运行结束后会刷新；旧运行可能未保存此记录。</p>
  </section>
</template>

<style scoped>
.audit-data { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; max-height: 60vh; overflow: auto; }
</style>
