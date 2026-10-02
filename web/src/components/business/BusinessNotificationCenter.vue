<script setup lang="ts">
import { computed, ref } from 'vue'

type NoticeKind = 'receipt' | 'input' | 'market' | 'failure'

interface NoticeItem {
  id: string
  kind: NoticeKind
  title: string
  summary: string
  context: string
  time: string
  unread: boolean
  action: 'open_request' | 'open_research' | 'retry' | null
}

const scope = ref<'all' | 'unread'>('all')
const notices = ref<NoticeItem[]>([
  {
    id: 'notice-operation',
    kind: 'receipt',
    title: '最近一次提交结果待核定',
    summary: '页面重新连接后正在查询服务端最近操作，不会自动重发。',
    context: '业务资料 · 操作恢复',
    time: '状态时间待服务端返回',
    unread: true,
    action: null,
  },
  {
    id: 'notice-input',
    kind: 'input',
    title: '有 2 项资料需要补充',
    summary: '一项来自研究 Run，一项来自尚未创建 Run 的行情事件。',
    context: '补数请求 · 待回答',
    time: '持久请求',
    unread: true,
    action: 'open_request',
  },
  {
    id: 'notice-failure',
    kind: 'failure',
    title: '分析任务的派发与执行需要分开恢复',
    summary: '重试派发沿用原任务；重新分析会保留失败 Run，并创建关联的新分析。',
    context: '分析状态 · 前端预览',
    time: '等待 DATA-11/12',
    unread: true,
    action: 'retry',
  },
])

const visibleNotices = computed(() =>
  scope.value === 'unread' ? notices.value.filter((notice) => notice.unread) : notices.value,
)
const unreadCount = computed(() => notices.value.filter((notice) => notice.unread).length)

function markRead(id: string): void {
  const item = notices.value.find((notice) => notice.id === id)
  if (item) item.unread = false
}

function markAllRead(): void {
  for (const item of notices.value) item.unread = false
}

function kindLabel(kind: NoticeKind): string {
  return { receipt: '回执', input: '补数', market: '行情', failure: '失败' }[kind]
}

const emit = defineEmits<{ navigate: [area: 'requests' | 'research'] }>()
</script>

<template>
  <div class="notice-layout">
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
        <span class="sync-state">游标未连接</span>
        <div><strong>通知服务等待 DATA-12</strong><small>游标过期时重新同步，不以当前页面是否打开判断后台在线。</small></div>
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
            <el-button v-if="item.action === 'open_request'" size="small" @click="emit('navigate', 'requests'); markRead(item.id)">去补充</el-button>
            <template v-else-if="item.action === 'retry'">
              <el-tooltip content="等待原任务派发恢复接口" placement="top"><span><el-button size="small" disabled>重试派发</el-button></span></el-tooltip>
              <el-tooltip content="等待关联新 Run 接口" placement="top"><span><el-button size="small" disabled>重新分析</el-button></span></el-tooltip>
            </template>
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
