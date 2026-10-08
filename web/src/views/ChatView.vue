<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { onBeforeRouteLeave } from 'vue-router'

import { artifacts as artifactsApi, link as linkApi, plans as plansApi, runs as runsApi } from '@/api'
import { ApiError } from '@/api/client'
import type {
  SessionPlanInput,
  SessionPlanPreview,
  WorkspaceArea,
  WorkspaceTarget,
} from '@/business-ui'
import ActivityPanel from '@/components/ActivityPanel.vue'
import ApprovalCard from '@/components/ApprovalCard.vue'
import AnalysisEvidence from '@/components/business/AnalysisEvidence.vue'
import AnalysisRerunPanel from '@/components/business/AnalysisRerunPanel.vue'
import BusinessWorkspace from '@/components/business/BusinessWorkspace.vue'
import BusinessInputRequestDialog from '@/components/business/BusinessInputRequestDialog.vue'
import SessionPlanManager from '@/components/business/SessionPlanManager.vue'
import DiffPanel from '@/components/DiffPanel.vue'
import PlanPanel from '@/components/PlanPanel.vue'
import ResearchCanvas from '@/components/ResearchCanvas.vue'
import ResearchComposer from '@/components/ResearchComposer.vue'
import ResearchRail from '@/components/ResearchRail.vue'
import RunStage from '@/components/RunStage.vue'
import { useAuthStore } from '@/stores/auth'
import { useBusinessStore } from '@/stores/business'
import { useRunStreamStore } from '@/stores/runs'
import { openRunStream, type SseEvent } from '@/sse'
import { useSessionsStore } from '@/stores/sessions'
import type { DiffFile } from '@/types'
import { renderMarkdown } from '@/utils/markdown'
import { redactSecrets } from '@/utils/redact'
import { dedupeAssistantTurns, sameRunId } from '@/utils/chat'
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
const detailTab = ref<'plan' | 'activity' | 'diff' | 'trace' | 'evidence'>('activity')
const workspaceArea = ref<WorkspaceArea>('research')
const workspaceRequestId = ref<string | null>(null)
const sessionPlanOpen = ref(false)
const business = useBusinessStore()
// The dialog + profile overview read plans from the server-backed store;
// every create/link change is a real write that lands back here.
const sessionPlans = computed<SessionPlanPreview[]>(() => business.planPreviews)
const businessDirty = ref(false)
const planDirty = ref(false)
const businessWorkspaceRef = ref<{ clearDraft: () => void } | null>(null)
const sessionPlanRef = ref<{ resetDraft: () => void } | null>(null)

function confirmDiscardDraft(): boolean {
  if (!businessDirty.value && !planDirty.value) return true
  if (!window.confirm('本页有未保存的资料，离开将丢弃草稿。是否继续？')) return false
  businessWorkspaceRef.value?.clearDraft()
  sessionPlanRef.value?.resetDraft()
  businessDirty.value = false
  planDirty.value = false
  return true
}

onBeforeRouteLeave(() => confirmDiscardDraft())

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
  thinking: string
  created_at: string | null
  run_id: string | null
}

function escapeText(s: string): string {
  const div = document.createElement('div')
  div.textContent = s
  return div.innerHTML.replace(/\n/g, '<br>')
}

/**
 * Per-run cached reasoning rehydrated from the run's trajectory after a
 * refresh. The turns API does not carry thinking, so a refreshed page would
 * otherwise lose every 「深度思考」 block; replaying each saved run rebuilds the
 * cache (see rehydrateThinking).
 *
 * An assistant turn maps to exactly one run, so thinking is keyed by run_id
 * alone — the trajectory's internal per-turn counter does NOT align with the
 * session's per-message ``seq``, so only run_id is a stable join key across the
 * two surfaces.
 */
const thinkingByRun = reactive(new Map<string, string>())
const thinkingRefreshing = new Set<string>()

/** The reasoning text for one run: rehydrated cache first, live stream second. */
function thinkingForRun(runId: string | null): string {
  if (!runId) return ''
  const cached = thinkingByRun.get(runId)
  if (cached) return cached
  const text = runStream.steps
    .filter((s) => s.kind === 'thinking')
    .map((s) => s.content ?? '')
    .join('\n')
  return text.trim()
}

/**
 * Replay a finished run's trajectory once to rebuild its reasoning text after
 * a refresh. Best-effort and fire-and-forget: a missing or 404 run just leaves
 * the cache empty (the answer itself still renders). The cache is reactive, so
 * populating it re-renders the message that reads it.
 */
function rehydrateThinking(runId: string): void {
  if (thinkingRefreshing.has(runId) || thinkingByRun.has(runId)) return
  // The live stream already carries this run's thinking; replaying it would
  // duplicate the text and hold a second tail connection for a run in flight.
  if (runStream.isStreaming && sameRunId(runStream.runId, runId)) return
  thinkingRefreshing.add(runId)
  let acc = ''
  const handle = openRunStream({
    url: runsApi.eventsUrl(runId),
    token: () => authStore.token,
    after: 0,
    onEvent: (event: SseEvent) => {
      if (event.type !== 'assistant_delta') return
      const thinking = (event as { thinking?: string }).thinking ?? ''
      const delta = (event as { thinking_text?: string }).thinking_text ?? ''
      const text = thinking !== '' ? thinking : delta
      if (!text) return
      acc += text
    },
    onDone: (reason) => {
      if (reason === 'completed' && acc.trim()) {
        thinkingByRun.set(runId, acc.trim())
      }
      thinkingRefreshing.delete(runId)
      handle.stop()
    },
    maxRetries: 0,
  })
}

/** (Re)fill the thinking cache for every saved assistant run in a turn list. */
function rehydrateAllThinking(turns: readonly { run_id: string | null }[]): void {
  const seen = new Set<string>()
  for (const t of turns) {
    if (t.run_id && !seen.has(t.run_id)) {
      seen.add(t.run_id)
      rehydrateThinking(t.run_id)
    }
  }
}

/**
 * True once the run has settled: the SSE stream is closed and the run reached a
 * terminal status.
 *
 * From then on the *persisted* answer is authoritative. The stream's accumulated
 * ``answer`` is only the per-turn agent text of the live/replay records, which is
 * not the run's final report — a stopped run (e.g. ``wall_deadline``) is persisted
 * with an explicit ``[partial: ...]`` tag, and a completed run's report is only
 * ever the summary's ``final_answer``. Rendering the streamed fragments after the
 * run ended was why the bubble differed from what a refresh showed.
 */
const runFinished = computed(
  () =>
    !runStream.isStreaming &&
    (runStream.status === 'completed' ||
      runStream.status === 'failed' ||
      runStream.status === 'stopped'),
)

const messages = computed<ChatMessage[]>(() => {
  const out: ChatMessage[] = dedupeAssistantTurns(sessions.activeTurns).map((t) => ({
    id: `turn-${t.seq}`,
    role: t.role === 'assistant' ? 'assistant' : 'user',
    raw: t.content ?? '',
    html:
      t.role === 'assistant'
        ? renderMarkdown(t.content ?? '')
        : escapeText(redactSecrets(t.content ?? '')),
    thinking:
      t.role === 'assistant'
        ? thinkingForRun(t.run_id ?? null)
        : '',
    created_at: t.created_at,
    run_id: t.run_id,
  }))

  if (runStream.runId) {
    // While the stream is live the accumulated deltas are the best view of the
    // answer; once it settles, the authoritative text wins.
    const streamText = runFinished.value
      ? runStream.finalAnswer || runStream.answer || ''
      : runStream.answer || runStream.finalAnswer || ''
    const streamingHtml = renderMarkdown(streamText)
    const existing = out.find(
      (message) =>
        message.role === 'assistant' && sameRunId(message.run_id, runStream.runId),
    )
    if (existing) {
      // Only the live stream may overwrite its own bubble. After the run ends the
      // persisted turn stays on screen: it is the final report (``[partial: ...]``
      // tag included), whereas the streamed fragments are just the raw turns.
      if (!runFinished.value) {
        existing.html = streamingHtml || existing.html
        existing.raw = streamText || existing.raw
      }
      existing.thinking = thinkingForRun(runStream.runId)
    } else {
      out.push({
        id: `run-${runStream.runId}`,
        role: 'assistant',
        raw: streamText,
        html: streamingHtml || '<span class="typing">生成中...</span>',
        thinking: thinkingForRun(runStream.runId),
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

// The canvas mirrors the thread: while a run is live it follows the streamed
// deltas, and once the run settles it shows the authoritative final answer rather
// than the last fragments of the stream.
const canvasAnswer = computed(() =>
  runFinished.value
    ? runStream.finalAnswer || latestAssistant.value || runStream.answer
    : runStream.answer || runStream.finalAnswer || latestAssistant.value,
)

const canvasTitle = computed(() => sessions.activeSession?.title || '本次研究')
const activeSessionPlanCount = computed(
  () => sessionPlans.value.filter((plan) => plan.sessionId === sessions.activeId).length,
)

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

// After a refresh (or a session switch) the turns are rebuilt from the history
// API, which carries no reasoning text. Replay each saved run's trajectory to
// rehydrate the 「深度思考」 blocks that would otherwise disappear. Keyed off the
// turns array reference + its length so it fires once per load, not per turn.
watch(
  () => [sessions.activeId, sessions.activeTurns, sessions.activeTurns.length],
  () => {
    if (sessions.activeTurns.length) rehydrateAllThinking(sessions.activeTurns)
  },
)

// ——— Agent 缺数据 → 结构化补数弹窗（2026-10-08）———
// 信号来自服务端：worker 声明意图后由 API 落库为 pending 的 input_request（issue 04）。
// 前端不解析自然语言，只按“该研究是否存在未提示过的 pending 请求”决定是否自动弹出。
import { inputRequests as inputRequestsApi } from '@/api'
import type { InputRequest } from '@/types'

const inputDialogOpen = ref(false)
const inputDialogRequest = ref<InputRequest | null>(null)
const promptedRequestIds = new Set<string>()

async function maybeOpenInputRequest(): Promise<void> {
  const id = sessions.activeId
  if (!id || inputDialogOpen.value) return
  try {
    const res = await inputRequestsApi.list({ research_id: id, status: 'pending', limit: 20 })
    const next = res.requests.find((item) => !promptedRequestIds.has(item.id))
    if (!next) return
    promptedRequestIds.add(next.id)
    inputDialogRequest.value = next
    inputDialogOpen.value = true
  } catch {
    // 补数查询失败不影响对话；HTTP 查询是恢复真源，下一次刷新会再试。
  }
}

async function reloadTurns(): Promise<void> {
  const id = sessions.activeId
  if (!id) return
  try {
    await sessions.loadTurns(id, Math.max(sessions.activeTurns.length, 100))
  } catch {
    // Keep the live stream visible if the authoritative refresh races.
  }
  await maybeOpenInputRequest()
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
    // F21: remember the newest submitted run per session so a refresh can
    // re-subscribe it while it is still active (a run parked on the approval
    // gate has no assistant turn yet — turns alone cannot point at it).
    if (sessions.activeId) runStream.rememberRun(sessions.activeId, res.run_id)
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

async function onSelectSession(): Promise<void> {
  workspaceArea.value = 'research'
  sessionPlanOpen.value = false
  runStream.reset()
  railOpen.value = false
  detailsOpen.value = false
  diffFiles.value = []
  const activeId = sessions.activeId
  if (activeId) await business.loadResearch(activeId)
}

async function onCreatedSession(): Promise<void> {
  workspaceArea.value = 'research'
  railOpen.value = false
  runStream.reset()
  await composerRef.value?.focus()
}

function onRerunStarted(runId: string): void {
  // A rerun creates a NEW run in the same session; switch the live view to it.
  if (sessions.activeId) runStream.rememberRun(sessions.activeId, runId)
  detailsOpen.value = false
  runStream.watch(runId)
}

async function onNavigate(area: WorkspaceArea, target?: WorkspaceTarget): Promise<void> {
  const sameDestination = area === workspaceArea.value
    && (!target?.requestId || target.requestId === workspaceRequestId.value)
    && (!target?.researchId || target.researchId === sessions.activeId)
  if (sameDestination || !confirmDiscardDraft()) return
  if (target?.researchId && target.researchId !== sessions.activeId) {
    await sessions.select(target.researchId)
  }
  workspaceRequestId.value = area === 'requests' ? target?.requestId ?? null : null
  workspaceArea.value = area
  railOpen.value = false
  canvasFocus.value = false
  detailsOpen.value = false
  if (area === 'research') void composerRef.value?.focus()
}

async function saveSessionPlan(input: SessionPlanInput): Promise<void> {
  const sessionId = sessions.activeId
  if (!sessionId) {
    ElMessage.warning('请先选择研究会话')
    return
  }

  // Build the server-side declared dict — every provided value is a pure string
  // so it survives DTO serialization; empty optional fields are simply omitted
  // and the server treats them as pending.
  const marketOf = (v: SessionPlanInput['market']) =>
    ({ CN: 'CN', HK: 'HK', US: 'US' } as const)[v]
  const declared: Record<string, unknown> = {
    symbol: { value: input.symbol },
    market: { value: marketOf(input.market) },
    direction: { value: input.direction },
  }
  const allocatedCapital = input.allocatedCapital.trim()
  if (allocatedCapital) declared.allocated_capital = { value: allocatedCapital }

  try {
    const res = await plansApi.create(
      sessionId,
      { name: input.name, declared, allow_incomplete: true },
      `plan.create:${sessionId}:${input.name}:${input.symbol}`,
    )
    const planId = String(res.plan_id)

    if (input.isPrimary) {
      await linkApi.set(
        sessionId,
        { account_id: null, primary_plan_id: planId },
        `link.set:${sessionId}:${planId}`,
      )
    }

    // Re-read authoritative plans so the preview reflects the real persisted value.
    await Promise.all([business.loadPlans(sessionId), business.loadLink(sessionId)])
    ElMessage.success(input.isPrimary ? '计划已创建并设为本会话主计划' : '计划已添加到当前会话')
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '创建计划失败')
  }
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
    return
  }
  // F21: a run still queued/running (e.g. parked on the approval gate) must
  // re-attach after the refresh — otherwise the dialog was live-only and the
  // run looked stuck with no way to answer it.
  await runStream.resumeForSession(target.id, () => sessions.activeId === target.id)
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
      :active-area="workspaceArea"
      :before-leave="confirmDiscardDraft"
      @selected="onSelectSession"
      @created="onCreatedSession"
      @navigate="onNavigate"
    />

    <template v-if="workspaceArea === 'research'">
      <main class="thread" aria-label="对话编排">
      <header class="thread-head">
        <el-button class="rail-toggle" text @click="railOpen = !railOpen">研究</el-button>
        <div class="thread-title">
          <span>{{ sessions.activeSession?.title || '未命名研究' }}</span>
          <small>{{ runStream.runId ? `Run ${runStream.runId.slice(0, 8)}` : '选择或新建研究后开始' }}</small>
        </div>
        <div class="thread-actions">
          <el-button
            plain
            size="small"
            :disabled="!sessions.activeId"
            @click="sessionPlanOpen = true"
          >
            会话计划
            <span v-if="activeSessionPlanCount" class="plan-count">{{ activeSessionPlanCount }}</span>
          </el-button>
          <el-button class="canvas-toggle" plain size="small" @click="canvasFocus = !canvasFocus">
            {{ canvasFocus ? '回到对话' : '打开画布' }}
          </el-button>
        </div>
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
          <el-tab-pane label="依据" name="evidence">
            <AnalysisEvidence :run-id="runStream.runId" />
          </el-tab-pane>
          <el-tab-pane label="轨迹" name="trace">
            <RunDetailView ref="runDetailRef" :run-id="runStream.runId" />
          </el-tab-pane>
        </el-tabs>
      </section>

      <AnalysisRerunPanel
        v-if="runStream.runId && (runStream.status === 'completed' || runStream.status === 'failed' || runStream.status === 'stopped')"
        :run-id="runStream.runId"
        :disabled="runStream.isStreaming"
        @rerun-started="onRerunStarted"
      />

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
          <details v-if="m.role === 'assistant' && m.thinking" class="turn-thinking">
            <summary class="turn-thinking__summary">深度思考<span class="turn-thinking__summary-caret">▾</span></summary>
            <pre class="turn-thinking__body">{{ m.thinking }}</pre>
          </details>
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

      <SessionPlanManager
        ref="sessionPlanRef"
        v-model="sessionPlanOpen"
        :session-id="sessions.activeId"
        :session-title="sessions.activeSession?.title || '未命名研究'"
        :plans="sessionPlans"
        @save="saveSessionPlan"
        @dirty-change="planDirty = $event"
      />

      <BusinessInputRequestDialog
        v-model="inputDialogOpen"
        :request="inputDialogRequest"
        @answered="reloadTurns"
      />

      <ResearchCanvas
        ref="canvasRef"
        :run-id="canvasRunId"
        :title="canvasTitle"
        :answer="canvasAnswer"
        :status="runStream.status"
        :full-screen="canvasFocus"
        @toggle-full-screen="canvasFocus = !canvasFocus"
      />
    </template>

    <BusinessWorkspace
      ref="businessWorkspaceRef"
      v-else
      :area="workspaceArea"
      :plans="sessionPlans"
      :target-request-id="workspaceRequestId"
      @navigate="onNavigate"
      @toggle-rail="railOpen = !railOpen"
      @dirty-change="businessDirty = $event"
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
}

.thread-actions { margin-left: auto; display: flex; align-items: center; gap: 8px; }
.thread-actions :deep(.el-button + .el-button) { margin-left: 0; }
.plan-count { display: inline-grid; place-items: center; min-width: 18px; height: 18px; margin-left: 5px; border-radius: 9px; background: var(--accent); color: var(--accent-text); font-size: 10px; }

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

.turn-role {
  grid-column: 1;
  grid-row: 1 / -1;
}

.turn-thinking,
.turn-body {
  grid-column: 2;
}

.turn-card.user {
  align-self: flex-end;
}

.turn-card.user .turn-body {
  border-color: color-mix(in srgb, var(--accent) 42%, var(--line));
  background: color-mix(in srgb, var(--accent) 10%, var(--bg-raised));
}

.turn-thinking {
  margin: 0 0 8px;
}

.turn-thinking__summary {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font-size: 12px;
  color: var(--muted);
  font-weight: 600;
  letter-spacing: 0.03em;
  user-select: none;
  padding: 0;
  border: none;
  background: none;
}

.turn-thinking__summary::before {
  content: '';
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--accent);
  flex: none;
}

.turn-thinking__summary-caret {
  margin-left: auto;
  font-size: 12px;
  opacity: 0.7;
  transition: transform 120ms;
}

.turn-thinking[open] .turn-thinking__summary-caret {
  transform: rotate(180deg);
}

.turn-thinking__body {
  margin: 8px 0 6px;
  border: 1px solid var(--line-strong);
  border-radius: 8px;
  background: color-mix(in srgb, var(--muted) 6%, var(--bg));
  padding: 12px 14px;
  max-height: 320px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12.5px;
  line-height: 1.65;
  color: var(--text-soft);
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
