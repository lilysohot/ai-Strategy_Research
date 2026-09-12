<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { renderMarkdown } from '@/utils/markdown'
import { redactSecrets } from '@/utils/redact'
import { useRunStreamStore } from '@/stores/runs'
import { useSessionsStore } from '@/stores/sessions'
import { useAuthStore } from '@/stores/auth'
import { artifacts as artifactsApi, runs as runsApi } from '@/api'
import { ApiError } from '@/api/client'
import type { DiffFile } from '@/types'
import SessionList from '@/components/SessionList.vue'
import ArtifactPanel from '@/components/ArtifactPanel.vue'
import ActivityPanel from '@/components/ActivityPanel.vue'
import DiffPanel from '@/components/DiffPanel.vue'
import PlanPanel from '@/components/PlanPanel.vue'
import ApprovalDialog from '@/components/ApprovalDialog.vue'
import RunDetailView from '@/views/RunDetailView.vue'
// Aliased: the run-level statusLabel/statusTagType computeds below own the
// bare names; these are the per-tool-step variants (§5.3 status set).
import {
  statusLabel as stepStatusLabel,
  statusTagType as stepStatusTagType,
} from '@/utils/activity'
import { formatElapsed } from '@/utils/statusbar'
import { summarizeDiff } from '@/utils/diff'
import {
  filterSteps,
  findMatches,
  reportText,
  type TranscriptFilter,
} from '@/utils/transcript'

const sessions = useSessionsStore()
const runStream = useRunStreamStore()
const authStore = useAuthStore()

const input = ref('')
const sending = ref(false)
const stopping = ref(false)
const scrollEl = ref<HTMLElement | null>(null)

// T12: a failed submit stays on screen as an actionable banner (with the exact
// text preserved for one-click retry) instead of a toast that vanishes.
const sendFailure = ref<{ text: string; message: string } | null>(null)
// T12: same treatment for session bootstrap failures (list/restore).
const bootFailure = ref<string | null>(null)

// 移动端：默认隐藏会话列表
const sidebarOpen = ref(false)

const statusTagType = computed<'' | 'success' | 'danger' | 'warning' | 'info'>(() => {
  switch (runStream.status) {
    case 'running':
    case 'queued':
      return 'warning'
    case 'completed':
      return 'success'
    case 'failed':
    case 'stopped':
      return 'danger'
    default:
      return 'info'
  }
})

const statusLabel = computed(() => {
  switch (runStream.status) {
    case 'queued':
      return '排队中'
    case 'running':
      return '运行中'
    case 'completed':
      return '已完成'
    case 'failed':
      return '失败'
    case 'stopped':
      return '已停止'
    default:
      return '空闲'
  }
})

// §5.6 状态栏：1Hz 时钟仅在有活跃 run 时驱动（终态后由 endedAtMs 定格耗时）
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

// spec §5.6：context 余量 = 累计 tokens / 上下文窗口（口径同 T2.11，取累计 prompt）。
const contextLabel = computed(() => {
  const limit = runStream.meta.contextLimit
  if (!limit || limit <= 0) return ''
  return `${Math.round((runStream.usage.prompt / limit) * 100)}%`
})

const toolCount = computed(() => runStream.meta.toolNames?.length ?? 0)

interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  /** Plain text (user) or already-sanitized HTML (assistant). */
  html: string
  raw: string
  created_at: string | null
  run_id: string | null
}

/** History turns (from the session) merged with the live run stream. */
const messages = computed<ChatMessage[]>(() => {
  const out: ChatMessage[] = sessions.activeTurns.map((t) => ({
    id: `turn-${t.seq}`,
    role: t.role === 'assistant' ? 'assistant' : 'user',
    raw: t.content ?? '',
    // Both paths redact: assistant text inside renderMarkdown, and user text here
    // — a user pasting an .env block is exactly the case T3.7 has to cover.
    html:
      t.role === 'assistant'
        ? renderMarkdown(t.content ?? '')
        : escapeText(redactSecrets(t.content ?? '')),
    created_at: t.created_at,
    run_id: t.run_id,
  }))

  // 当前正在进行的 run：用户提示词 + 流式累积的助手回答
  if (runStream.runId) {
    const last = out[out.length - 1]
    const streamingHtml = renderMarkdown(runStream.answer)
    if (last && last.run_id === runStream.runId && last.role === 'assistant') {
      last.html = streamingHtml
      last.raw = runStream.answer
    } else {
      out.push({
        id: `run-${runStream.runId}`,
        role: 'assistant',
        raw: runStream.answer,
        html: streamingHtml || '<span class="typing">思考中…</span>',
        created_at: null,
        run_id: runStream.runId,
      })
    }
  }
  return out
})

/** Sanitize a step's markdown/HTML for display (secrets redacted first). */
function renderStep(text: string | undefined): string {
  return renderMarkdown(redactSecrets(text ?? ''))
}

function escapeText(s: string): string {
  const div = document.createElement('div')
  div.textContent = s
  return div.innerHTML.replace(/\n/g, '<br>')
}

async function scrollToBottom() {
  await nextTick()
  if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight
}

/**
 * Load the previous page of turns when the user scrolls to the top.
 *
 * The scroll position has to be restored manually: prepending messages grows the
 * content above the viewport, which would otherwise jump the reader to a
 * completely different part of the conversation. Anchoring on the height delta
 * keeps the message they were looking at exactly where it was.
 */
async function onMessagesScroll() {
  const el = scrollEl.value
  if (!el || el.scrollTop > 40) return
  if (!sessions.hasMoreTurns || sessions.loadingOlder) return

  const heightBefore = el.scrollHeight
  try {
    await sessions.loadOlderTurns()
  } catch {
    return // the store already stashed the message; don't fight it with a jump
  }
  await nextTick()
  if (scrollEl.value) {
    scrollEl.value.scrollTop = scrollEl.value.scrollHeight - heightBefore
  }
}

// ── P2.6 transcript 导航（§5.5：/filter · /find · Ctrl-G · Ctrl-Y）──
const transcriptFilter = ref<TranscriptFilter>('all')
const visibleSteps = computed(() => filterSteps(runStream.steps, transcriptFilter.value))

const findQuery = ref('')
const matchIds = computed(() => findMatches(runStream.steps, findQuery.value))
const matchPos = ref(0)

watch(findQuery, () => {
  matchPos.value = 0
})

/** Flash-highlight a step element after scrolling it into view. */
async function flashStep(id: number) {
  let el = scrollEl.value?.querySelector(`[data-step-id="${id}"]`)
  if (!el && transcriptFilter.value !== 'all') {
    // The target step is hidden by the active filter — reset first.
    transcriptFilter.value = 'all'
    await nextTick()
    el = scrollEl.value?.querySelector(`[data-step-id="${id}"]`)
  }
  if (!el) return
  el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  el.classList.add('step-flash')
  window.setTimeout(() => el.classList.remove('step-flash'), 1200)
}

function jumpMatch(delta: number) {
  const ids = matchIds.value
  if (!ids.length) return
  matchPos.value = (matchPos.value + delta + ids.length) % ids.length
  flashStep(ids[matchPos.value])
}

function jumpToReport() {
  const visible = filterSteps(runStream.steps, 'report')
  if (visible.length) flashStep(visible[0].id)
}

async function copyReport() {
  const text = reportText(runStream.steps)
  if (!text) {
    ElMessage.warning('还没有可复制的报告')
    return
  }
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('报告已复制')
  } catch {
    ElMessage.error('复制失败')
  }
}

watch(
  () => [messages.value.length, runStream.answer, runStream.timeline.length],
  () => scrollToBottom(),
)

/**
 * Re-read the server's copy of the active session's turns.
 *
 * A finished run's reply is persisted by the orchestrator but is never streamed
 * again, and watching the *next* run clears the live buffers (``watch()`` resets
 * ``answer``/``steps``). Without pulling the persisted copies back, sending a
 * second message would take the previous answer off screen — the reply only ever
 * existed in that stream state.
 */
async function reloadTurns(): Promise<void> {
  const id = sessions.activeId
  if (!id) return
  try {
    // Keep whatever the user already paged through: a plain one-page refresh
    // would drop the older turns loaded by scrolling up.
    await sessions.loadTurns(id, Math.max(sessions.activeTurns.length, 100))
  } catch {
    // Keep whatever the live stream already rendered; a failed refresh must not
    // blank a conversation the user can still read.
  }
}

async function onSend() {
  const text = input.value.trim()
  if (!text || sending.value) return
  if (!sessions.activeId) {
    ElMessage.warning('请先新建或选择一个会话')
    return
  }
  // Only one run is watched at a time: starting another would drop the live
  // stream of the previous one mid-flight, and its answer would be gone.
  if (runStream.isStreaming) {
    ElMessage.warning('上一条还在运行，请等它结束或点击停止')
    return
  }
  sending.value = true
  input.value = ''
  sendFailure.value = null
  try {
    // Re-read first: the reply of any earlier run lives only in the server's
    // copy at this point, and runStream.watch() below wipes the local stream
    // state it used to be rendered from.
    await reloadTurns()
    // 乐观插入用户消息
    sessions.appendLocalTurn({
      seq: (sessions.activeTurns.at(-1)?.seq ?? 0) + 1,
      role: 'user',
      content: text,
      run_id: null,
      created_at: null,
    })
    const res = await runsApi.submit({ session_id: sessions.activeId, message: text })
    runStream.watch(res.run_id)
  } catch (err) {
    // Keep the optimistic turn (it reads as "sent") and pair it with a banner
    // the user can retry; a self-dismissing toast made failures look lost.
    sendFailure.value = {
      text,
      message: err instanceof Error ? err.message : '发送失败',
    }
  } finally {
    sending.value = false
  }
}

/** Re-send the exact text that failed; onSend clears the banner on success. */
function retrySend(): void {
  if (!sendFailure.value || sending.value) return
  input.value = sendFailure.value.text
  sendFailure.value = null
  void onSend()
}

/**
 * P3.3: a revert rewrote files under the run, so every view derived from the
 * tree has to be re-read — the Diff tab drops what is no longer a change and
 * the artifact list drops a file the revert deleted.
 */
async function onReverted() {
  await loadDiff()
  await artifactPanelRef.value?.load()
  await runDetailRef.value?.load()
}

/**
 * Stop the active run (T3.6).
 *
 * ``runStream.stop()`` swallows the 409 ("run not running") because a race
 * between the user's click and the run finishing is normal — but the user still
 * needs to know why nothing happened, so we surface it as a warning here rather
 * than silently succeeding. We call the API directly to see the status.
 */
async function onStop() {
  if (!runStream.runId || stopping.value) return
  stopping.value = true
  try {
    await runsApi.stop(runStream.runId)
    ElMessage.success('已发送停止请求')
    // The worker writes artifacts on shutdown, so pull the final set once it
    // has had a moment to finish.
    window.setTimeout(() => {
      artifactPanelRef.value?.load()
      runDetailRef.value?.load()
      loadDiff()
    }, 1200)
  } catch (err) {
    if (err instanceof ApiError && err.status === 409) {
      ElMessage.warning('该运行已结束，无需停止')
    } else {
      ElMessage.error(err instanceof ApiError ? err.message : '停止失败')
    }
  } finally {
    stopping.value = false
  }
}

// 运行详情抽屉（T3.5 轨迹 + T3.6 产物）
const detailOpen = ref(false)
const detailTab = ref<'trace' | 'artifacts'>('trace')

// P2.5 Diff：run 结束后才有 diff.json；404/异常都收敛为"无变更"隐藏 Tab。
const diffFiles = ref<DiffFile[]>([])

// spec §5.6：状态栏"文件变更统计(+新增/-删除)"直接汇总自 Diff（§5.4）。
const diffSummary = computed(() => summarizeDiff(diffFiles.value))

async function loadDiff() {
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

/**
 * Terminal state is when two things land: diff.json on disk, and the assistant
 * turn in the DB — so re-read both. The delay is deliberate: the SSE terminal
 * frame can beat the orchestrator's turn write by a few hundred ms, and pulling
 * too early would cache a history still missing that reply.
 */
watch(
  () => runStream.status,
  async (s) => {
    if (s !== 'completed' && s !== 'failed' && s !== 'stopped') return
    await new Promise((resolve) => setTimeout(resolve, 1200))
    await reloadTurns()
    void loadDiff()
  },
)

/** Both panels expose ``load()`` so a stop can pull the final data. */
interface ReloadablePanel {
  load: () => Promise<void> | void
}
const artifactPanelRef = ref<ReloadablePanel | null>(null)
const runDetailRef = ref<ReloadablePanel | null>(null)

function openDetail() {
  if (!runStream.runId) {
    ElMessage.warning('当前没有正在展示的运行')
    return
  }
  detailOpen.value = true
  // 打开抽屉时顺手刷新 Diff（运行可能在打开期间结束）。
  void loadDiff()
}

function onSelectSession() {
  // SessionList 内部已 select；切换会话时关闭旧 run 流
  runStream.reset()
  sidebarOpen.value = false
}

/**
 * Remember which session the user was last in.
 *
 * The store is in-memory, so a reload otherwise lands on an empty chat area even
 * though the server kept every session — it reads as "history was not saved"
 * when in fact nothing was selected.
 */
const lastSessionKey = computed(
  () => `frontier-agent.lastSession:${authStore.user?.id ?? 'anon'}`,
)

function rememberSession(id: string | null): void {
  try {
    if (id) localStorage.setItem(lastSessionKey.value, id)
    else localStorage.removeItem(lastSessionKey.value)
  } catch {
    /* storage unavailable — fall back to opening the most recent session */
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
  // A remembered id can belong to another account or have been deleted since;
  // in both cases fall back to the most recently updated session.
  const target = sessions.list.find((s) => s.id === remembered) ?? sessions.list[0]
  if (!target) return
  // Let the failure propagate: the caller (boot) turns it into the retryable
  // banner instead of a toast here.
  await sessions.select(target.id)
}

/**
 * Load the session list and restore the last-open one. Shared by the initial
 * mount and the retry button on the boot failure banner (T12).
 */
async function bootSessions(): Promise<void> {
  bootFailure.value = null
  try {
    if (!sessions.list.length) await sessions.loadList()
    await restoreSession()
  } catch {
    bootFailure.value = sessions.error ?? '加载会话失败'
  }
}

onMounted(() => {
  void bootSessions()
})

onBeforeUnmount(() => {
  runStream.close()
  if (clockTimer !== null) clearInterval(clockTimer)
})

// 当 SessionList 选中会话后自动刷新 turns
watch(
  () => sessions.activeId,
  (id) => {
    rememberSession(id)
    if (id) onSelectSession()
  },
)
</script>

<template>
  <div class="chat-layout">
    <SessionList class="chat-sidebar" :class="{ open: sidebarOpen }" />

    <section class="chat-main">
      <header class="chat-header">
        <el-button
          class="menu-btn"
          text
          :icon="'Menu'"
          @click="sidebarOpen = !sidebarOpen"
        />
        <span class="chat-title">{{ sessions.activeSession?.title || '未命名会话' }}</span>
        <el-tag v-if="runStream.runId" :type="statusTagType" size="small" data-testid="run-status">
          {{ statusLabel }}
        </el-tag>
        <!-- §5.6 状态栏事实行：耗时 · pipeline · model · ctx% · tools · 文件变更 -->
        <span v-if="runStream.runId" class="sb-facts" data-testid="sb-facts">
          <span v-if="elapsedLabel" class="sb-item">{{ elapsedLabel }}</span>
          <span v-if="runStream.meta.pipelineId" class="sb-item">{{ runStream.meta.pipelineId }}</span>
          <span v-if="runStream.meta.modelName" class="sb-item">{{ runStream.meta.modelName }}</span>
          <span v-if="contextLabel" class="sb-item">ctx {{ contextLabel }}</span>
          <span v-if="toolCount" class="sb-item">tools {{ toolCount }}</span>
          <span v-if="runStream.steerQueued" class="sb-item" data-testid="sb-steer">
            queued {{ runStream.steerQueued }}
          </span>
          <span v-if="diffFiles.length" class="sb-item" data-testid="sb-diff">
            文件 +{{ diffSummary.additions }}/-{{ diffSummary.deletions }}
          </span>
        </span>
        <el-button
          v-if="runStream.isStreaming"
          class="stop-btn"
          type="danger"
          size="small"
          plain
          :loading="stopping"
          data-testid="stop-btn"
          @click="onStop"
        >
          停止
        </el-button>
        <el-button
          v-else-if="runStream.lastError"
          class="retry-btn"
          size="small"
          plain
          data-testid="retry-btn"
          @click="runStream.retry()"
        >
          重试
        </el-button>
        <el-button
          v-if="runStream.runId"
          class="detail-btn"
          size="small"
          plain
          data-testid="detail-btn"
          @click="openDetail"
        >
          详情
        </el-button>
      </header>

      <!-- T12：会话加载失败时给可重试的内联提示，而不是一闪而过的 toast -->
      <el-alert
        v-if="bootFailure"
        class="boot-error-banner"
        type="error"
        :closable="false"
        show-icon
        :title="`加载会话失败：${bootFailure}`"
        data-testid="boot-error-banner"
      >
        <el-button size="small" type="primary" plain @click="bootSessions">重试</el-button>
      </el-alert>

      <!-- §5.7：失败原因可追溯 —— 仅状态栏的"失败"标签不够，必须给出 why -->
      <el-alert
        v-if="runStream.status === 'failed' && runStream.errorMessage"
        class="run-error-banner"
        type="error"
        :closable="false"
        show-icon
        :title="`运行失败：${runStream.errorMessage}`"
        data-testid="run-error-banner"
      />

      <!-- P2.6 transcript 导航栏：过滤 + 查找 + 跳报告/复制（对齐 /filter · /find · Ctrl-G/Y） -->
      <div v-if="runStream.runId" class="transcript-bar" data-testid="transcript-bar">
        <el-radio-group
          v-model="transcriptFilter"
          size="small"
          data-testid="transcript-filter"
        >
          <el-radio-button value="all">全部</el-radio-button>
          <el-radio-button value="thinking">思考</el-radio-button>
          <el-radio-button value="tools">工具</el-radio-button>
          <el-radio-button value="errors">错误</el-radio-button>
          <el-radio-button value="report">报告</el-radio-button>
        </el-radio-group>

        <div class="find-box">
          <el-input
            v-model="findQuery"
            size="small"
            clearable
            placeholder="查找…"
            data-testid="find-input"
            @keydown.enter.prevent="jumpMatch(1)"
          />
          <span class="find-count" data-testid="find-count">
            {{ matchIds.length ? `${matchPos + 1}/${matchIds.length}` : (findQuery ? '0' : '') }}
          </span>
          <el-button
            size="small"
            text
            :disabled="!matchIds.length"
            data-testid="find-prev"
            @click="jumpMatch(-1)"
          >
            上一个
          </el-button>
          <el-button
            size="small"
            text
            :disabled="!matchIds.length"
            data-testid="find-next"
            @click="jumpMatch(1)"
          >
            下一个
          </el-button>
          <el-button size="small" text type="primary" data-testid="jump-report" @click="jumpToReport">
            最终报告
          </el-button>
          <el-button size="small" text type="primary" data-testid="copy-report" @click="copyReport">
            复制
          </el-button>
        </div>
      </div>

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
        <el-empty
          v-if="!messages.length"
          description="开始你的第一条消息"
          class="messages-empty"
        />
        <div
          v-for="m in messages"
          :key="m.id"
          class="msg"
          :class="m.role"
        >
          <div class="bubble" v-html="m.html" />
          <!-- Full reasoning path for the live run (terminal-like trace). -->
          <div
            v-if="m.role === 'assistant' && runStream.runId && m.run_id === runStream.runId"
            class="steps"
          >
            <div v-for="s in visibleSteps" :key="s.id" class="step" :class="s.kind" :data-step-id="s.id">
              <details v-if="s.kind === 'thinking'" class="step-thinking">
                <summary class="step-label">
                  <span class="dot" />思考（turn {{ s.turn ?? '?' }}）
                </summary>
                <div class="step-body" v-html="renderStep(s.content)" />
              </details>

              <div v-else-if="s.kind === 'text'" class="step-text" v-html="renderStep(s.content)" />

              <div v-else class="tool-card" :class="s.status">
                <span class="tool-name">{{ redactSecrets(s.name ?? 'tool') }}</span>
                <el-tag size="small" :type="stepStatusTagType(s.status)">
                  {{ stepStatusLabel(s.status) || '…' }}
                </el-tag>
                <span v-if="s.ms" class="tool-ms">{{ s.ms }}ms</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- T12：发送失败保留原文并提供一键重试，而不是自消失的 toast -->
      <el-alert
        v-if="sendFailure"
        class="send-error-banner"
        type="error"
        :closable="false"
        show-icon
        :title="`发送失败：${sendFailure.message}`"
        data-testid="send-error-banner"
      >
        <el-button size="small" type="primary" plain @click="retrySend">重试发送</el-button>
      </el-alert>

      <footer class="composer">
        <el-input
          v-model="input"
          type="textarea"
          :rows="2"
          resize="none"
          placeholder="输入消息，Enter 发送，Shift+Enter 换行"
          data-testid="composer"
          @keydown.enter.exact.prevent="onSend"
        />
        <el-button
          type="primary"
          :loading="sending"
          :disabled="!input.trim() || sending"
          data-testid="send-btn"
          @click="onSend"
        >
          发送
        </el-button>
      </footer>
    </section>

    <el-drawer
      v-model="detailOpen"
      title="运行详情"
      direction="rtl"
      size="46%"
      :z-index="30"
    >
      <el-tabs v-model="detailTab" class="detail-tabs">
        <el-tab-pane label="Plan" name="plan">
          <PlanPanel :steps="runStream.steps" />
        </el-tab-pane>
        <el-tab-pane label="Activity" name="activity">
          <ActivityPanel :steps="runStream.steps" />
        </el-tab-pane>
        <!-- P2.5：无变更（无 diff.json / files 为空）时整个 Tab 隐藏 -->
        <el-tab-pane v-if="diffFiles.length" label="Diff" name="diff">
          <DiffPanel
            :files="diffFiles"
            :run-id="runStream.runId"
            @reverted="onReverted"
          />
        </el-tab-pane>
        <el-tab-pane label="轨迹回放" name="trace">
          <RunDetailView ref="runDetailRef" :run-id="runStream.runId" />
        </el-tab-pane>
        <el-tab-pane label="产物" name="artifacts">
          <ArtifactPanel ref="artifactPanelRef" :run-id="runStream.runId" />
        </el-tab-pane>
      </el-tabs>
    </el-drawer>

    <!-- P3.2 审批门：挂起时模态弹出，approval_resolved 后由 store 清除 -->
    <ApprovalDialog />
  </div>
</template>

<style scoped>
.chat-layout {
  display: flex;
  height: 100%;
  overflow: hidden;
}

.chat-sidebar {
  height: 100%;
}

.chat-main {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  height: 100%;
}

.chat-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.menu-btn {
  display: none;
}

.chat-title {
  font-weight: 600;
  font-size: 15px;
}

/* §5.6 状态栏事实行 */
.sb-facts {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  overflow: hidden;
}

.sb-item {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
}

.stop-btn,
.retry-btn {
  margin-left: auto;
}

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  background: var(--el-bg-color-page, #f5f7fa);
}

/* P2.6 transcript 导航栏 */
.transcript-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 16px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  flex-wrap: wrap;
}

.find-box {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-left: auto;
  min-width: 0;
}

.find-box .el-input {
  width: 160px;
}

.find-count {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
  min-width: 34px;
  text-align: center;
}

/* 查找/跳报告命中时的短暂高亮 */
:deep(.step-flash) {
  animation: step-flash 1.2s ease;
}

@keyframes step-flash {
  0%, 60% {
    background: var(--el-color-warning-light-7);
    box-shadow: 0 0 0 3px var(--el-color-warning-light-5);
    border-radius: 6px;
  }
  100% {
    background: transparent;
  }
}

.messages-empty {
  margin: auto;
}

/* Pagination header: "load older" affordance at the top of the transcript. */
.older-turns {
  display: flex;
  justify-content: center;
  padding: 2px 0 6px;
  flex-shrink: 0;
}

.older-turns-end {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.msg {
  display: flex;
  max-width: 100%;
}

.msg.user {
  justify-content: flex-end;
}

.msg.assistant {
  justify-content: flex-start;
  flex-direction: column;
  align-items: flex-start;
}

.bubble {
  max-width: 72%;
  padding: 10px 14px;
  border-radius: 12px;
  line-height: 1.6;
  font-size: 14px;
  word-break: break-word;
}

.msg.user .bubble {
  background: var(--el-color-primary);
  color: #fff;
  border-bottom-right-radius: 2px;
}

.msg.assistant .bubble {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-bottom-left-radius: 2px;
}

.msg.assistant .bubble :deep(pre) {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 10px;
  border-radius: 8px;
  overflow-x: auto;
}

.msg.assistant .bubble :deep(code) {
  background: var(--el-fill-color);
  padding: 1px 4px;
  border-radius: 4px;
  font-size: 13px;
}

.msg.assistant .bubble :deep(a) {
  color: var(--el-color-primary);
}

/* ── Reasoning trace (thinking / text / tool steps) ─────────── */
.steps {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 8px;
  max-width: 88%;
}

.step-thinking {
  border-left: 3px solid var(--el-color-info-light-3);
  padding: 4px 10px;
  border-radius: 6px;
  background: var(--el-fill-color-lighter);
}

.step-thinking .step-label {
  cursor: pointer;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  user-select: none;
  display: flex;
  align-items: center;
  gap: 6px;
}

.step-thinking .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--el-color-info);
  flex-shrink: 0;
}

.step-thinking .step-body {
  margin-top: 6px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--el-text-color-regular);
  word-break: break-word;
}

.step-text {
  font-size: 13px;
  line-height: 1.6;
  padding: 2px 0;
  word-break: break-word;
}

.step-text :deep(pre) {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 8px;
  border-radius: 6px;
  overflow-x: auto;
}

.step-text :deep(p) {
  margin: 0 0 6px;
}

.tool-ms {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.tool-cards {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}

.tool-card {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  border-radius: 8px;
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-lighter);
  font-size: 12px;
}

.tool-card.error {
  border-color: var(--el-color-danger-light-5);
}

.tool-card.done {
  border-color: var(--el-color-success-light-5);
}

.composer {
  display: flex;
  gap: 10px;
  padding: 12px 16px;
  border-top: 1px solid var(--el-border-color-lighter);
  align-items: flex-end;
}

.composer .el-button {
  flex-shrink: 0;
}

/* 移动端：侧边栏抽屉化 */
@media (max-width: 768px) {
  .chat-sidebar {
    position: absolute;
    z-index: 20;
    transform: translateX(-100%);
    transition: transform 0.2s ease;
    box-shadow: 2px 0 8px rgba(0, 0, 0, 0.12);
  }

  .chat-sidebar.open {
    transform: translateX(0);
  }

  .menu-btn {
    display: inline-flex;
  }

  .bubble {
    max-width: 88%;
  }
}
</style>
