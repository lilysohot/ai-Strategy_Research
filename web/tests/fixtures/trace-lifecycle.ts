import { createApp, h, ref } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import RunDetailView from '../../src/views/RunDetailView.vue'
import { useRunStreamStore } from '../../src/stores/runs'

const pinia = createPinia()
const runId = ref('trace-first')
const app = createApp({ render: () => h(RunDetailView, { runId: runId.value }) })
app.use(pinia).use(ElementPlus)
const stream = useRunStreamStore(pinia)
stream.runId = runId.value
stream.status = 'running'
Object.assign(window, {
  traceTest: {
    finish() { stream.status = 'completed' },
    switchRun(id: string) { runId.value = id; stream.runId = id; stream.status = 'running' },
  },
})
app.mount('#app')
