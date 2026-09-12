<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { artifacts as artifactsApi, runs as runsApi } from '@/api'
import { ApiError } from '@/api/client'
import ActivityPanel from '@/components/ActivityPanel.vue'
import ApprovalCard from '@/components/ApprovalCard.vue'
import DiffPanel from '@/components/DiffPanel.vue'
import PlanPanel from '@/components/PlanPanel.vue'
import ResearchCanvas from '@/components/ResearchCanvas.vue'
import ResearchComposer from '@/components/ResearchComposer.vue'
import ResearchRail from '@/components/ResearchRail.vue'
import RunStage from '@/components/RunStage.vue'
import { useAuthStore } from '@/stores/auth'
import { useRunStreamStore } from '@/stores/runs'
import { useSessionsStore } from '@/stores/sessions'
import type { DiffFile } from '@/types'
import { renderMarkdown } from '@/utils/markdown'
import { redactSecrets } from '@/utils/redact'
import { summarizeDiff } from '@/utils/diff'
import { formatElapsed } from '@/utils/statusbar'
import RunDetailView from '@/views/RunDetailView.vue'

const sessions = useSessionsStore()
const runStream = useRunStreamStore()
const authStore = useAuthStore()

const scrollEl = ref<HTMLElement | null>(null)
const composerRef = ref<{ focus: () => Promise<void> } | null>(null)
const canvasRef = ref<{ load: () => Promise<void> | void } | null>(null)
const runDetailRef = ref<{ load: () => Promise<void> | void } | null>(null)

const sending = ref(false)
const stopping = ref(false)
const steering = ref(false)
const railOpen = ref(false)
const detailsOpen = ref(false)
const canvasFocus = ref(false)
const detailTab = ref<'plan' | 'activity' | 'diff' | 'trace'>('activity')

const clock = ref(Date.now())
let clockTimer: ReturnType<typeof setInterval> | null = null

watch(
  () => runStream.isStreaming,
  (active) => {
    if (active && clockTimer === null) {
      clockTimer = setInterval(() => {
        clock.value = Date.now()
      }, 1000)
    } else if (!active && clockTimer !== null) {
      clearInterval(clockTimer)
      clockTimer = null
    }
  },
  { immediate: true },
)

const elapsedLabel = computed(() => {
  if (runStream.startedAtMs === null) return ''
  const end = runStream.endedAtMs ?? clock.value
  return formatElapsed(Math.max(0, end - runStream.startedAtMs))
})

const contextLabel = computed(() => {
  const limit = runStream.meta.contextLimit
  if (!limit || limit <= 0) return ''
  return `${Math.round((runStream.usage.prompt / limit) * 100)}%`
})

const toolCount = computed(() => runStream.meta.toolNames?.length ?? 0)

interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  html: string
  raw: string
  created_at: string | null
  run_id: string | null
}

function escapeText(s: string): string {
  const div = document.createElement('div')
  div.textContent = s
  return div.innerHTML.replace(/\n/g, '<br>')
}

const messages = computed<ChatMessage[]>(() => {
  const out: ChatMessage[] = sessions.activeTurns.map((t) => ({
    id: `turn-${t.seq}`,
    role: t.role === 'assistant' ? 'assistant' : 'user',
    raw: t.content ?? '',
    html:
      t.role === 'assistant'
        ? renderMarkdown(t.content ?? '')
        : escapeText(redactSecrets(t.content ?? '')),
    created_at: t.created_at,
    run_id: t.run_id,
  }))

  if (runStream.runId) {
    const last = out[out.length - 1]
    const streamText = runStream.answer || runStream.finalAnswer || ''
    const streamingHtml = renderMarkdown(streamText)
    if (last && last.run_id === runStream.runId && last.role === 'assistant') {
      last.html = streamingHtml || last.html
      last.raw = streamText || last.raw
    } else {
      out.push({
        id: `run-${runStream.runId}`,
        role: 'assistant',
        raw: streamText,
        html: streamingHtml || '<span class="typing">生成中...</span>',
        created_at: null,
        run_id: runStream.runId,
      })
    }
  }

  return out
})

const latestAssistant = computed(() => {
  for (let i = sessions.activeTurns.length - 1; i >= 0; i -= 1) {
    const turn = sessions.activeTurns[i]
    if (turn.role === 'assistant') return turn.content ?? ''
  }
  return ''
})

const latestAssistantRunId = computed(() => {
  for (let i = sessions.activeTurns.length - 1; i >= 0; i -= 1) {
    const turn = sessions.activeTurns[i]
    if (turn.role === 'assistant' && turn.run_id) return turn.run_id
  }
  return null
})

const canvasRunId = computed(() => runStream.runId || latestAssistantRunId.value)

const canvasAnswer = computed(() =>
  runStream.answer || runStream.finalAnswer || latestAssistant.value,
)

const canvasTitle = computed(() => sessions.activeSession?.title || '本次研究')

const diffFiles = ref<DiffFile[]>([])
const diffSummary = computed(() => summarizeDiff(diffFiles.value))
const diffLabel = computed(() =>
  diffFiles.value.length ? `文件 +${diffSummary.value.additions}/-${diffSummary.value.deletions}` : '',
)

async function scrollToBottom(): Promise<void> {
  await nextTick()
  if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight
}

async function onMessagesScroll(): Promise<void> {
  const el = scrollEl.value
  if (!el || el.scrollTop > 40) return
  if (!sessions.hasMoreTurns || sessions.loadingOlder) return

  const heightBefore = el.scrollHeight
  try {
    await sessions.loadOlderTurns()
  } catch {
    return
  }
  await nextTick()
  if (scrollEl.value) {
    scrollEl.value.scrollTop = scrollEl.value.scrollHeight - heightBefore
  }
}

watch(
  () => [messages.value.length, runStream.answer, runStream.timeline.length],
  () => scrollToBottom(),
)

async function reloadTurns(): Promise<void> {
  const id = sessions.activeId
  if (!id) return
  try {
    await sessions.loadTurns(id, Math.max(sessions.activeTurns.length, 100))
  } catch {
    // Keep the live stream visible if the authoritative refresh races.
  }
}

function buildRunPayload(text: string, files: File[]): { message: string; session_id?: string } | FormData {
  if (!files.length) return { session_id: sessions.activeId ?? undefined, message: text }
  const form = new FormData()
  form.append('session_id', sessions.activeId ?? 'default')
  form.append('message', text)
  for (const file of files) form.append('files', file)
  return form
}

async function onSend(text: string, files: File[]): Promise<void> {
  if (!text.trim() || sending.value) return
  if (!sessions.activeId) {
    ElMessage.warning('请先新建或选择一项研究')
    return
  }
  if (runStream.isStreaming) {
    ElMessage.warning('上一条还在运行，请等它结束或点击停止')
    return
  }

  sending.value = true
  try {
    await reloadTurns()
    sessions.appendLocalTurn({
      seq: (sessions.activeTurns.at(-1)?.seq ?? 0) + 1,
      role: 'user',
      content: text,
      run_id: null,
      created_at: null,
    })
    const res = await runsApi.submit(buildRunPayload(text, files))
    detailsOpen.value = false
    runStream.watch(res.run_id)
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '发送失败')
  } finally {
    sending.value = false
  }
}

async function onStop(): Promise<void> {
  if (!runStream.runId || stopping.value) return
  stopping.value = true
  try {
    await runsApi.stop(runStream.runId)
    ElMessage.success('已发送停止请求')
    window.setTimeout(() => {
      void loadDiff()
      void canvasRef.value?.load()
      void runDetailRef.value?.load()
    }, 1200)
  } catch (err) {
    if (err instanceof ApiError && err.status === 409) {
      ElMessage.warning('该运行已结束，无需停止')
    } else {
      ElMessage.error(err instanceof Error ? err.message : '停止失败')
    }
  } finally {
    stopping.value = false
  }
}

async function onSteer(message: string): Promise<void> {
  if (!runStream.runId || steering.value) return
  steering.value = true
  try {
    await runsApi.steer(runStream.runId, message)
    ElMessage.success('已排队，下一工具边界生效')
  } catch (err) {
    const msg =
      err instanceof ApiError && err.status === 409
        ? '该运行已结束，无法插话'
        : err instanceof Error
          ? err.message
          : '插话失败'
    ElMessage.error(msg)
  } finally {
    steering.value = false
  }
}

async function loadDiff(): Promise<void> {
  const runId = runStream.runId
  if (!runId) {
    diffFiles.value = []
    return
  }
  try {
    diffFiles.value = (await artifactsApi.diff(runId)).files
  } catch {
    diffFiles.value = []
  }
}

async function onReverted(): Promise<void> {
  await loadDiff()
  await canvasRef.value?.load()
  await runDetailRef.value?.load()
}

watch(
  () => runStream.status,
  async (s) => {
    if (s !== 'completed' && s !== 'failed' && s !== 'stopped') return
    await new Promise((resolve) => setTimeout(resolve, 1200))
    await reloadTurns()
    await loadDiff()
    await canvasRef.value?.load()
  },
)

function onSelectSession(): void {
  runStream.reset()
  railOpen.value = false
  detailsOpen.value = false
  diffFiles.value = []
}

async function onCreatedSession(): Promise<void> {
  railOpen.value = false
  runStream.reset()
  await composerRef.value?.focus()
}

const lastSessionKey = computed(
  () => `frontier-agent.lastSession:${authStore.user?.id ?? 'anon'}`,
)

function rememberSession(id: string | null): void {
  try {
    if (id) localStorage.setItem(lastSessionKey.value, id)
    else localStorage.removeItem(lastSessionKey.value)
  } catch {
    // Storage is a preference cache only.
  }
}

async function restoreSession(): Promise<void> {
  if (sessions.activeId || !sessions.list.length) return
  let remembered: string | null = null
  try {
    remembered = localStorage.getItem(lastSessionKey.value)
  } catch {
    remembered = null
  }
  const target = sessions.list.find((s) => s.id === remembered) ?? sessions.list[0]
  if (!target) return
  try {
    await sessions.select(target.id)
  } catch {
    ElMessage.error(sessions.error ?? '打开研究失败')
  }
}

onMounted(async () => {
  if (!sessions.list.length) {
    try {
      await sessions.loadList()
    } catch {
      ElMessage.error(sessions.error ?? '加载研究失败')
    }
  }
  await restoreSession()
})

onBeforeUnmount(() => {
  runStream.close()
  if (clockTimer !== null) clearInterval(clockTimer)
})

watch(
  () => sessions.activeId,
  (id) => {
    rememberSession(id)
    if (id) onSelectSession()
  },
)
</script>

<template>
  <div class="workbench" :class="{ 'canvas-open': canvasFocus }">
    <ResearchRail
      class="workbench-rail"
      :class="{ open: railOpen }"
      @selected="onSelectSession"
      @created="onCreatedSession"
    />

    <main class="thread" aria-label="对话编排">
      <header class="thread-head">
        <el-button class="rail-toggle" text @click="railOpen = !railOpen">研究</el-button>
        <div class="thread-title">
          <span>{{ sessions.activeSession?.title || '未命名研究' }}</span>
          <small>{{ runStream.runId ? `Run ${runStream.runId.slice(0, 8)}` : '选择或新建研究后开始' }}</small>
        </div>
        <el-button class="canvas-toggle" plain size="small" @click="canvasFocus = !canvasFocus">
          {{ canvasFocus ? '回到对话' : '打开画布' }}
        </el-button>
      </header>

      <RunStage
        :elapsed-label="elapsedLabel"
        :context-label="contextLabel"
        :tool-count="toolCount"
        :diff-label="diffLabel"
        :stopping="stopping"
        :details-open="detailsOpen"
        @stop="onStop"
        @retry="runStream.retry()"
        @toggle-details="detailsOpen = !detailsOpen"
      />

      <el-alert
        v-if="runStream.status === 'failed' && runStream.errorMessage"
        class="run-error-banner"
        type="error"
        :closable="false"
        show-icon
        :title="`运行失败：${runStream.errorMessage}`"
        data-testid="run-error-banner"
      />

      <ApprovalCard />

      <section v-if="detailsOpen && runStream.runId" class="run-disclosure" aria-label="运行过程">
        <el-tabs v-model="detailTab">
          <el-tab-pane label="计划" name="plan">
            <PlanPanel :steps="runStream.steps" />
          </el-tab-pane>
          <el-tab-pane label="活动" name="activity">
            <ActivityPanel :steps="runStream.steps" />
          </el-tab-pane>
          <el-tab-pane v-if="diffFiles.length" label="变更" name="diff">
            <DiffPanel :files="diffFiles" :run-id="runStream.runId" @reverted="onReverted" />
          </el-tab-pane>
          <el-tab-pane label="轨迹" name="trace">
            <RunDetailView ref="runDetailRef" :run-id="runStream.runId" />
          </el-tab-pane>
        </el-tabs>
      </section>

      <div ref="scrollEl" class="messages" data-testid="messages" @scroll.passive="onMessagesScroll">
        <div v-if="messages.length" class="older-turns" data-testid="older-turns">
          <el-button
            v-if="sessions.hasMoreTurns"
            text
            size="small"
            :loading="sessions.loadingOlder"
            @click="onMessagesScroll"
          >
            加载更早消息
          </el-button>
          <span v-else class="older-turns-end">已经是最早的消息</span>
        </div>

        <el-empty v-if="!messages.length" description="开始你的第一项研究" class="messages-empty" />

        <article v-for="m in messages" :key="m.id" class="turn-card" :class="m.role">
          <div class="turn-role">{{ m.role === 'user' ? '你' : 'Agent' }}</div>
          <div class="turn-body" v-html="m.html" />
          <div v-if="m.role === 'assistant' && runStream.runId === m.run_id && runStream.isStreaming" class="generating">
            生成中
          </div>
        </article>
      </div>

      <ResearchComposer
        ref="composerRef"
        :disabled="!sessions.activeId"
        :sending="sending"
        :streaming="runStream.isStreaming"
        :stopping="stopping"
        :steering="steering"
        @send="onSend"
        @stop="onStop"
        @steer="onSteer"
      />
    </main>

    <ResearchCanvas
      ref="canvasRef"
      :run-id="canvasRunId"
      :title="canvasTitle"
      :answer="canvasAnswer"
      :status="runStream.status"
      :full-screen="canvasFocus"
      @toggle-full-screen="canvasFocus = !canvasFocus"
    />
  </div>
</template>

<style scoped>
.workbench {
  position: relative;
  display: flex;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  background: var(--bg-app);
  color: var(--text);
}

.thread {
  min-width: 520px;
  flex: 1 1 560px;
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-app);
}

.thread-head {
  min-height: 58px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--line);
}

.rail-toggle {
  display: none;
}

.thread-title {
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.thread-title span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 700;
}

.thread-title small,
.older-turns-end,
.generating,
.turn-role {
  color: var(--muted);
  font-size: 12px;
}

.canvas-toggle {
  display: none;
  margin-left: auto;
}

.run-error-banner {
  border-radius: 0;
}

.run-disclosure {
  max-height: 42%;
  min-height: 220px;
  overflow: auto;
  padding: 0 14px 12px;
  border-bottom: 1px solid var(--line);
  background: var(--bg-raised);
}

.messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 18px 16px;
}

.messages-empty {
  margin: auto;
}

.older-turns {
  display: flex;
  justify-content: center;
  padding: 2px 0 4px;
}

.turn-card {
  max-width: min(760px, 92%);
  display: grid;
  grid-template-columns: 52px minmax(0, 1fr);
  gap: 10px;
  align-self: flex-start;
}

.turn-card.user {
  align-self: flex-end;
}

.turn-card.user .turn-body {
  border-color: color-mix(in srgb, var(--accent) 42%, var(--line));
  background: color-mix(in srgb, var(--accent) 10%, var(--bg-raised));
}

.turn-body {
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--bg-raised);
  color: var(--text);
  line-height: 1.72;
  word-break: break-word;
}

.turn-body :deep(p:first-child) {
  margin-top: 0;
}

.turn-body :deep(p:last-child) {
  margin-bottom: 0;
}

.turn-body :deep(pre) {
  overflow-x: auto;
  padding: 10px;
  border-radius: 6px;
  background: #0d0e0b;
  border: 1px solid var(--line);
}

.turn-body :deep(code) {
  background: rgba(255, 255, 255, 0.06);
  padding: 1px 4px;
  border-radius: 4px;
}

.turn-body :deep(a) {
  color: var(--accent);
}

.generating {
  grid-column: 2;
}

@media (max-width: 1279px) {
  .thread {
    min-width: 0;
  }
}

@media (max-width: 1023px) {
  .workbench-rail {
    position: absolute;
    inset: 0 auto 31px 0;
    z-index: 30;
    transform: translateX(-100%);
    transition: transform 0.2s ease;
  }

  .workbench-rail.open {
    transform: translateX(0);
  }

  .rail-toggle,
  .canvas-toggle {
    display: inline-flex;
  }

  .turn-card {
    max-width: 100%;
  }
}

@media (max-width: 640px) {
  .thread-head {
    align-items: flex-start;
  }

  .turn-card {
    grid-template-columns: 1fr;
  }

  .turn-role,
  .generating {
    grid-column: 1;
  }

  .messages {
    padding: 12px;
  }
}
</style>
