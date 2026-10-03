<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { businessEvents as eventsApi } from '@/api'
import type { WorkspaceTarget } from '@/business-ui'
import { openRunStream, type SseStreamHandle } from '@/sse'
import { useAuthStore } from '@/stores/auth'
import type { BusinessEvent } from '@/types'

type NoticeKind = 'receipt' | 'input' | 'market' | 'failure'

interface NoticeItem extends BusinessEvent {
  kind: NoticeKind
  context: string
  time: string
  unread: boolean
  action: 'open_request' | 'open_research' | null
}

const scope = ref<'all' | 'unread'>('all')
const auth = useAuthStore()
const events = ref<BusinessEvent[]>([])
const cursor = ref(0)
const loading = ref(false)
let stream: SseStreamHandle | null = null

const notices = computed<NoticeItem[]>(() => events.value.map((item) => ({
  ...item,
  kind: item.kind.startsWith('input_') ? 'input' : 'receipt',
  context: item.request_id ? '补数请求' : '业务事件',
  time: item.created_at ? new Date(item.created_at).toLocaleString() : '时间未知',
  unread: !item.read,
  action: item.request_id && item.kind === 'input_required' ? 'open_request' : 'open_research',
})))

const visibleNotices = computed(() =>
  scope.value === 'unread' ? notices.value.filter((notice) => notice.unread) : notices.value,
)
const unreadCount = computed(() => notices.value.filter((notice) => notice.unread).length)

async function loadEvents(): Promise<void> {
  loading.value = true
  try {
    const recovered: BusinessEvent[] = []
    let after = 0
    for (;;) {
      const result = await eventsApi.list(after, 100)
      recovered.push(...result.items)
      after = result.cursor
      if (result.items.length < 100) break
    }
    mergeEvents(recovered)
    cursor.value = after
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载通知失败')
  } finally {
    loading.value = false
  }
}

function mergeEvents(incoming: BusinessEvent[]): void {
  const byId = new Map(events.value.map((item) => [item.id, item]))
  for (const item of incoming) byId.set(item.id, item)
  events.value = [...byId.values()].sort((left, right) => left.cursor - right.cursor)
}

function startStream(): void {
  stream?.stop()
  stream = openRunStream({
    url: eventsApi.streamUrl(),
    token: () => auth.token,
    after: cursor.value,
    terminalTypes: [],
    onCursor: (value) => { cursor.value = value },
    onEvent: (frame) => {
      if (frame.type !== 'business_event') return
      const item = (frame as typeof frame & { event?: BusinessEvent }).event
      if (item) mergeEvents([item])
    },
    onError: (error) => ElMessage.error(`通知连接失败：${error.message}`),
  })
}

async function markRead(id: string): Promise<void> {
  await eventsApi.markRead(id)
  const item = events.value.find((event) => event.id === id)
  if (item) item.read = true
}

async function markAllRead(): Promise<void> {
  await eventsApi.markAllRead(cursor.value)
  for (const item of events.value) item.read = true
}

function kindLabel(kind: NoticeKind): string {
  return { receipt: '回执', input: '补数', market: '行情', failure: '失败' }[kind]
}

async function openNotice(item: NoticeItem): Promise<void> {
  if (item.unread) await markRead(item.id)
  const target: WorkspaceTarget = {
    researchId: item.research_id,
    requestId: item.request_id ?? undefined,
    runId: item.run_id ?? undefined,
  }
  emit('navigate', item.action === 'open_request' ? 'requests' : 'research', target)
}

const emit = defineEmits<{
  navigate: [area: 'requests' | 'research', target?: WorkspaceTarget]
}>()
onMounted(async () => {
  await loadEvents()
  startStream()
})
onBeforeUnmount(() => stream?.stop())
</script>

<template>
  <div class="notice-layout" v-loading="loading">
    <main class="notice-main">
      <header class="notice-head">
        <div>
          <p class="eyebrow">站内通知 · UI-09</p>
          <h2>每一条通知，都要能回到它发生的地方</h2>
          <p>业务事件与 Run 进度分流，断线按用户游标补读；重复推送不会生成重复卡片。</p>
        </div>
        <div class="notice-tools">
          <el-segmented v-model="scope" :options="[{ label: '全部', value: 'all' }, { label: `未读 ${unreadCount}`, value: 'unread' }]" />
          <el-button text :disabled="!unreadCount" @click="markAllRead">全部已读</el-button>
        </div>
      </header>

      <div class="sync-banner">
        <span class="sync-state">游标 {{ cursor }}</span>
        <div><strong>通知已从持久事件恢复</strong><small>刷新后按用户游标补读；单个 Run 的进度仍使用原有事件流。</small></div>
      </div>

      <section class="notice-list" aria-label="通知列表">
        <article v-for="item in visibleNotices" :key="item.id" class="notice-row" :class="{ unread: item.unread }">
          <div class="notice-mark" :data-kind="item.kind">{{ kindLabel(item.kind) }}</div>
          <div class="notice-copy">
            <div class="notice-titleline">
              <h3>{{ item.title }}</h3>
              <span v-if="item.unread" aria-label="未读" />
            </div>
            <p>{{ item.summary }}</p>
            <div class="notice-meta"><span>{{ item.context }}</span><span>{{ item.time }}</span></div>
          </div>
          <div class="notice-actions">
            <el-button v-if="item.action === 'open_request'" size="small" @click="openNotice(item)">去补充</el-button>
            <el-button v-else-if="item.action === 'open_research'" size="small" @click="openNotice(item)">打开研究</el-button>
            <el-button v-if="item.unread" text size="small" @click="markRead(item.id)">标为已读</el-button>
          </div>
        </article>
        <el-empty v-if="!visibleNotices.length" description="没有未读通知" :image-size="58" />
      </section>
    </main>

    <aside class="notice-aside">
      <div class="aside-section aside-section--accent">
        <span>通知边界</span>
        <h3>事件不是运行日志</h3>
        <p>站内通知承载可行动的业务变化；单个 Run 的 token、工具和阶段进度仍留在原有 SSE 面板。</p>
      </div>
      <div class="aside-section">
        <span>自动事件状态</span>
        <ul>
          <li>待分析 / 运行中 / 完成</li>
          <li>失败 / 过期 / 已合并</li>
          <li>预算阻止 / 待补资料</li>
        </ul>
      </div>
      <div class="aside-section">
        <span>登录与授权</span>
        <p>登录过期只影响页面访问，不会自动撤销已保存的监控授权。凭据失效则提供单独处理入口。</p>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.notice-layout { display: grid; grid-template-columns: minmax(0, 1fr) 320px; min-height: 100%; }
.notice-main { min-width: 0; padding: 28px clamp(20px, 3vw, 44px) 52px; overflow: auto; }
.notice-head { display: flex; justify-content: space-between; align-items: flex-end; gap: 24px; padding-bottom: 24px; border-bottom: 1px solid var(--line); }
.notice-head h2 { margin: 4px 0 8px; font-family: 'Songti SC', 'Source Han Serif SC', serif; font-size: clamp(24px, 3vw, 34px); line-height: 1.2; }
.notice-head p:not(.eyebrow) { max-width: 680px; margin: 0; color: var(--muted); }
.eyebrow { margin: 0; color: var(--accent); font-size: 11px; font-weight: 700; letter-spacing: .12em; }
.notice-tools { display: flex; align-items: center; gap: 8px; }
.sync-banner { display: grid; grid-template-columns: auto 1fr; gap: 16px; align-items: center; margin: 24px 0; padding: 13px 15px; border-block: 1px solid var(--line); background: color-mix(in srgb, var(--warning) 6%, transparent); }
.sync-state { color: var(--warning); font-size: 12px; font-weight: 700; }
.sync-banner > div { display: flex; flex-direction: column; }
.sync-banner small { color: var(--muted); }
.notice-list { border-top: 1px solid var(--line); }
.notice-row { display: grid; grid-template-columns: 52px minmax(0, 1fr) auto; gap: 16px; align-items: start; padding: 20px 10px; border-bottom: 1px solid var(--line); }
.notice-row.unread { background: color-mix(in srgb, var(--accent) 4%, transparent); }
.notice-mark { display: grid; place-items: center; min-height: 28px; border: 1px solid var(--line); color: var(--muted); font-size: 11px; }
.notice-mark[data-kind='input'] { border-color: var(--warning); color: var(--warning); }
.notice-mark[data-kind='failure'] { border-color: var(--danger); color: var(--danger); }
.notice-copy { min-width: 0; }
.notice-titleline { display: flex; align-items: center; gap: 8px; }
.notice-titleline h3 { margin: 0; font-size: 16px; }
.notice-titleline span { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); }
.notice-copy p { margin: 6px 0; color: var(--text-soft); }
.notice-meta { display: flex; flex-wrap: wrap; gap: 6px 16px; color: var(--muted); font-size: 12px; }
.notice-actions { display: flex; align-items: flex-end; flex-direction: column; gap: 6px; }
.notice-actions > span { width: 100%; }
.notice-actions > span :deep(.el-button) { width: 100%; }
.notice-aside { padding: 28px 22px; border-left: 1px solid var(--line); background: #141711; overflow: auto; }
.aside-section { padding: 18px 0; border-bottom: 1px solid var(--line); }
.aside-section:first-child { padding-top: 14px; }
.aside-section--accent { border-top: 2px solid var(--accent); }
.aside-section > span { color: var(--accent); font-size: 11px; font-weight: 700; letter-spacing: .09em; }
.aside-section h3 { margin: 7px 0; }
.aside-section p, .aside-section li { color: var(--muted); font-size: 13px; }
.aside-section ul { margin: 8px 0 0; padding-left: 18px; }
@media (max-width: 980px) { .notice-layout { grid-template-columns: 1fr; } .notice-aside { border-top: 1px solid var(--line); border-left: 0; } }
@media (max-width: 640px) {
  .notice-main { padding: 20px 14px 36px; }
  .notice-head { align-items: flex-start; flex-direction: column; }
  .notice-tools { width: 100%; justify-content: space-between; }
  .notice-row { grid-template-columns: 42px minmax(0, 1fr); }
  .notice-actions { grid-column: 2; align-items: flex-start; flex-direction: row; flex-wrap: wrap; }
}
</style>
