import { createApp, h, ref } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import ResearchComposer from '../../src/components/ResearchComposer.vue'
import { useRunStreamStore } from '../../src/stores/runs'
import { useAuthStore } from '../../src/stores/auth'

const pinia = createPinia()
useAuthStore(pinia).setToken('isolated-browser-test')
const stream = useRunStreamStore(pinia)
const stopping = ref(false)
const error = ref('')
const app = createApp({ render: () => h('main', [
  h('div', { id: 'status' }, stream.status),
  h('div', { id: 'error' }, error.value),
  h(ResearchComposer, {
    disabled: false, sending: false, steering: false, sessionId: 'test',
    teamAvailable: false, teamUnavailableReason: '', modeLoading: false,
    streaming: stream.isStreaming || stream.status === 'queued' || stream.status === 'running',
    stopping: stopping.value,
    async onStop() {
      stopping.value = true
      try { await stream.stop() } catch (err) { error.value = String(err) }
      finally { stopping.value = false }
    },
  }),
]) })
app.use(pinia).use(ElementPlus)
Object.assign(window, { queuedStopTest: stream })
stream.watch('queued-first', undefined, 'test')
app.mount('#app')
