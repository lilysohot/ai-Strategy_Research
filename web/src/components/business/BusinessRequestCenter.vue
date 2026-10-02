<script setup lang="ts">
import { computed, ref } from 'vue'

import { useSessionsStore } from '@/stores/sessions'

type RequestStatus = 'pending' | 'answered' | 'cancelled' | 'expired'

interface DataRequestItem {
  id: string
  title: string
  purpose: string
  field: string
  unit: string
  known: string
  reason: string
  status: RequestStatus
  origin: string
  hasRun: boolean
  sessionId: string
  sessionTitle: string
}

interface BusinessReceiptItem {
  id: string
  title: string
  detail: string
  status: 'checking' | 'done' | 'failed'
  sessionId: string
  sessionTitle: string
}

const sessions = useSessionsStore()
const filter = ref<'all' | RequestStatus>('all')
const selectedId = ref('request-risk-budget')
const answer = ref('')
const acknowledgeNewValue = ref(false)

function sessionAt(index: number): { id: string; title: string } {
  const session = sessions.list[index] ?? sessions.list[0]
  return {
    id: session?.id ?? 'preview-session',
    title: session?.title || '尚未选择研究',
  }
}

const requests = computed<DataRequestItem[]>(() => {
  const primarySession = sessionAt(0)
  const secondarySession = sessionAt(1)
  return [{
    id: 'request-risk-budget',
    title: '风险预算单位不明确',
    purpose: '未成交计划分析',
    field: '风险预算',
    unit: '金额或百分比',
    known: '已收到数值，未收到单位',
    reason: '无法判断该值代表金额还是账户资金占比',
    status: 'pending',
    origin: '研究中的资料补充请求',
    hasRun: true,
    sessionId: primarySession.id,
    sessionTitle: primarySession.title,
  },
  {
    id: 'request-quote-basis',
    title: '行情口径需要确认',
    purpose: '自动事件触发前检查',
    field: '行情口径',
    unit: '成交价 / 买一 / 卖一',
    known: '规则已关联标的，尚未创建分析 Run',
    reason: '监控来源支持多个报价口径，不能自行选择',
    status: 'pending',
    origin: '行情事件 EVT-—',
    hasRun: false,
    sessionId: secondarySession.id,
    sessionTitle: secondarySession.title,
  },
  {
    id: 'request-account-basis',
    title: '资金口径已补充',
    purpose: '持仓成本计算',
    field: '资金口径',
    unit: '文本枚举',
    known: '回答已被后续 Run 采用',
    reason: '完成',
    status: 'answered',
    origin: '历史补数请求',
    hasRun: true,
    sessionId: primarySession.id,
    sessionTitle: primarySession.title,
  },
]})

const receipts = computed<BusinessReceiptItem[]>(() => {
  const session = sessionAt(0)
  return [{
    id: 'receipt-latest-operation',
    title: '正在查询最近一次资料提交',
    detail: '使用不含业务正文的操作标识恢复，不会盲目重新提交',
    status: 'checking',
    sessionId: session.id,
    sessionTitle: session.title,
  }]
})

const visibleRequests = computed(() =>
  filter.value === 'all' ? requests.value : requests.value.filter((item) => item.status === filter.value),
)
const selected = computed(() => requests.value.find((item) => item.id === selectedId.value) ?? requests.value[0])

function statusLabel(status: RequestStatus): string {
  return { pending: '待补充', answered: '已回答', cancelled: '已取消', expired: '已过期' }[status]
}
</script>

<template>
  <div class="request-layout">
    <main class="request-main">
      <header class="request-head">
        <div>
          <p class="eyebrow">待补资料与处理结果 · UI-04 / 07 / 09</p>
          <h2>每一项待办，都回到它所属的会话</h2>
          <p>一个会话可以产生多条待补资料和业务回执；每一条记录只属于一个会话，本页负责跨会话汇总。</p>
        </div>
        <el-segmented
          v-model="filter"
          :options="[
            { label: '全部', value: 'all' },
            { label: '待补充', value: 'pending' },
            { label: '已回答', value: 'answered' },
          ]"
        />
      </header>

      <section class="receipt-section" aria-labelledby="receipt-section-title">
        <header>
          <div>
            <span>会话业务回执</span>
            <h3 id="receipt-section-title">最近处理结果</h3>
          </div>
          <small>全局账户页的独立操作结果不在这里强行关联会话</small>
        </header>
        <article v-for="receipt in receipts" :key="receipt.id" class="receipt-strip">
          <div class="receipt-status"><span class="pulse" />结果核定中</div>
          <div>
            <strong>{{ receipt.title }}</strong>
            <small>{{ receipt.detail }}</small>
          </div>
          <div class="receipt-session">
            <span>所属会话</span>
            <strong>{{ receipt.sessionTitle }}</strong>
          </div>
        </article>
      </section>

      <section class="submission-pipeline" aria-label="附件提交阶段">
        <header>
          <div><span>带附件提交</span><strong>阶段回执预留</strong></div>
          <small>当前没有进行中的附件操作</small>
        </header>
        <ol>
          <li><span>01</span><strong>上传</strong><small>登记文件与操作标识</small></li>
          <li><span>02</span><strong>校验</strong><small>同名冲突就地处理</small></li>
          <li><span>03</span><strong>提交</strong><small>保存业务资料版本</small></li>
          <li><span>04</span><strong>派发</strong><small>复用已登记附件</small></li>
        </ol>
        <p>重试不会悄悄覆盖同名文件，也不会重复上传已成功登记的附件。</p>
      </section>

      <div class="request-list" role="list">
        <button
          v-for="item in visibleRequests"
          :key="item.id"
          type="button"
          class="request-row"
          :class="{ active: item.id === selectedId }"
          @click="selectedId = item.id"
        >
          <span class="request-index">{{ String(requests.indexOf(item) + 1).padStart(2, '0') }}</span>
          <span class="request-copy">
            <strong>{{ item.title }}</strong>
            <small>{{ item.sessionTitle }} · {{ item.purpose }} · {{ item.field }}</small>
          </span>
          <span class="status-label" :data-status="item.status">{{ statusLabel(item.status) }}</span>
        </button>
        <el-empty v-if="!visibleRequests.length" description="该状态下没有请求" :image-size="52" />
      </div>
    </main>

    <aside v-if="selected" class="request-detail" aria-label="补数请求详情">
      <div class="detail-topline">
        <span>{{ selected.hasRun ? '关联运行' : '事件预检查' }}</span>
        <span class="status-label" :data-status="selected.status">{{ statusLabel(selected.status) }}</span>
      </div>
      <h3>{{ selected.title }}</h3>
      <p class="detail-reason">{{ selected.reason }}</p>

      <dl class="detail-facts">
        <div><dt>所属会话</dt><dd>{{ selected.sessionTitle }}</dd></div>
        <div><dt>用途</dt><dd>{{ selected.purpose }}</dd></div>
        <div><dt>字段</dt><dd>{{ selected.field }}</dd></div>
        <div><dt>单位</dt><dd>{{ selected.unit }}</dd></div>
        <div><dt>已知值</dt><dd>{{ selected.known }}</dd></div>
        <div><dt>来源</dt><dd>{{ selected.origin }}</dd></div>
      </dl>

      <template v-if="selected.status === 'pending'">
        <label class="answer-field">
          <span>你的明确回答</span>
          <el-input
            v-model="answer"
            type="textarea"
            :rows="4"
            placeholder="只回答待澄清的事实；不确定时可说明仍需补充"
          />
        </label>

        <div class="conflict-card">
          <span>资料版本提醒</span>
          <strong>当前资料可能已在另一个窗口更新</strong>
          <p>接入接口后，这里会展示版本差异，并要求明确沿用新值或重新提交。</p>
          <el-checkbox v-model="acknowledgeNewValue">我已查看当前版本</el-checkbox>
        </div>

        <el-tooltip content="等待 DATA-07 请求回答接口" placement="top">
          <span class="full-action">
            <el-button type="primary" disabled>提交回答并继续</el-button>
          </span>
        </el-tooltip>
        <p class="integration-note">前端预览不会把输入标为“已回答”，也不会模拟生成后续 Run。</p>
      </template>

      <template v-else>
        <div class="answer-history">
          <span>已提交回答</span>
          <p>服务端接入后显示原始回答、采用版本、剩余待补项和后续 Run。</p>
        </div>
      </template>
    </aside>
  </div>
</template>

<style scoped>
.request-layout { display: grid; grid-template-columns: minmax(0, 1fr) 360px; min-height: 100%; }
.request-main { min-width: 0; padding: 28px clamp(20px, 3vw, 44px) 50px; overflow: auto; }
.request-head { display: flex; justify-content: space-between; align-items: flex-end; gap: 24px; padding-bottom: 24px; border-bottom: 1px solid var(--line); }
.request-head h2 { margin: 4px 0 8px; font-family: 'Songti SC', 'Source Han Serif SC', serif; font-size: clamp(24px, 3vw, 34px); line-height: 1.2; }
.request-head p:not(.eyebrow) { max-width: 680px; margin: 0; color: var(--muted); }
.eyebrow { margin: 0; color: var(--accent); font-size: 11px; font-weight: 700; letter-spacing: .12em; }
.receipt-section { margin: 24px 0; }
.receipt-section > header { display: flex; align-items: flex-end; justify-content: space-between; gap: 18px; margin-bottom: 10px; }
.receipt-section > header span { color: var(--accent); font-size: 10px; font-weight: 700; letter-spacing: .1em; }
.receipt-section > header h3 { margin: 3px 0 0; font-size: 16px; }
.receipt-section > header small { max-width: 420px; color: var(--muted); text-align: right; }
.receipt-strip { display: grid; grid-template-columns: auto 1fr minmax(150px, auto); gap: 16px; align-items: center; padding: 14px 16px; border-block: 1px solid var(--line); background: color-mix(in srgb, var(--warning) 6%, transparent); }
.receipt-status { display: flex; align-items: center; gap: 7px; color: var(--warning); font-size: 12px; font-weight: 700; }
.pulse { width: 7px; height: 7px; border-radius: 50%; background: var(--warning); box-shadow: 0 0 0 4px color-mix(in srgb, var(--warning) 18%, transparent); }
.receipt-strip > div:nth-child(2) { display: flex; flex-direction: column; }
.receipt-strip small { color: var(--muted); font-size: 12px; }
.receipt-session { display: flex; flex-direction: column; align-items: flex-end; }
.receipt-session span { color: var(--muted); font-size: 10px; letter-spacing: .08em; }
.receipt-session strong { max-width: 220px; overflow: hidden; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.submission-pipeline { margin-bottom: 26px; padding: 14px 16px; border: 1px solid var(--line); background: var(--bg-input); }
.submission-pipeline header { display: flex; justify-content: space-between; gap: 14px; }
.submission-pipeline header div { display: flex; gap: 10px; }
.submission-pipeline header span { color: var(--accent); font-size: 11px; font-weight: 700; letter-spacing: .08em; }
.submission-pipeline header small, .submission-pipeline li small, .submission-pipeline > p { color: var(--muted); }
.submission-pipeline ol { display: grid; grid-template-columns: repeat(4, 1fr); gap: 0; margin: 16px 0 10px; padding: 0; list-style: none; }
.submission-pipeline li { position: relative; display: flex; flex-direction: column; gap: 2px; padding: 0 10px 0 22px; border-left: 1px solid var(--line); }
.submission-pipeline li > span { position: absolute; left: 7px; top: 1px; color: var(--quiet); font-family: monospace; font-size: 9px; }
.submission-pipeline li strong { font-size: 12px; }
.submission-pipeline li small { font-size: 10px; }
.submission-pipeline > p { margin: 0; font-size: 11px; }
.request-list { display: flex; flex-direction: column; border-top: 1px solid var(--line); }
.request-row { display: grid; grid-template-columns: 46px minmax(0, 1fr) auto; gap: 14px; align-items: center; padding: 18px 12px; border: 0; border-bottom: 1px solid var(--line); background: transparent; color: var(--text); text-align: left; cursor: pointer; }
.request-row:hover, .request-row.active { background: color-mix(in srgb, var(--accent) 6%, transparent); }
.request-row.active { box-shadow: inset 2px 0 var(--accent); }
.request-index { color: var(--quiet); font-family: monospace; }
.request-copy { display: flex; min-width: 0; flex-direction: column; gap: 3px; }
.request-copy small { color: var(--muted); }
.status-label { padding: 3px 7px; border: 1px solid var(--line); border-radius: 999px; color: var(--muted); font-size: 11px; white-space: nowrap; }
.status-label[data-status='pending'] { border-color: color-mix(in srgb, var(--warning) 60%, var(--line)); color: var(--warning); }
.status-label[data-status='answered'] { border-color: color-mix(in srgb, var(--ok) 60%, var(--line)); color: var(--ok); }
.request-detail { padding: 30px 24px; border-left: 1px solid var(--line); background: #141711; overflow: auto; }
.detail-topline { display: flex; justify-content: space-between; color: var(--muted); font-size: 12px; }
.request-detail h3 { margin: 18px 0 8px; font-family: 'Songti SC', 'Source Han Serif SC', serif; font-size: 24px; }
.detail-reason { margin: 0 0 20px; color: var(--text-soft); }
.detail-facts { margin: 0; padding-block: 10px; border-block: 1px solid var(--line); }
.detail-facts div { display: grid; grid-template-columns: 76px 1fr; gap: 10px; padding: 8px 0; }
.detail-facts dt { color: var(--muted); }
.detail-facts dd { margin: 0; }
.answer-field { display: flex; flex-direction: column; gap: 8px; margin-top: 22px; }
.answer-field > span, .conflict-card > span, .answer-history > span { color: var(--accent); font-size: 11px; font-weight: 700; letter-spacing: .08em; }
.conflict-card { margin: 18px 0; padding: 14px; border: 1px solid var(--line); background: var(--bg-input); }
.conflict-card strong { display: block; margin: 6px 0; }
.conflict-card p, .integration-note, .answer-history p { color: var(--muted); font-size: 12px; }
.full-action, .full-action :deep(.el-button) { width: 100%; }
.integration-note { margin: 8px 0 0; text-align: center; }
.answer-history { margin-top: 22px; padding-top: 18px; border-top: 1px solid var(--line); }
@media (max-width: 980px) { .request-layout { grid-template-columns: 1fr; } .request-detail { border-top: 1px solid var(--line); border-left: 0; } }
@media (max-width: 640px) {
  .request-main { padding: 20px 14px 36px; }
  .request-head { align-items: flex-start; flex-direction: column; }
  .receipt-section > header { align-items: flex-start; flex-direction: column; }
  .receipt-section > header small { text-align: left; }
  .receipt-strip { grid-template-columns: 1fr; gap: 6px; }
  .receipt-session { align-items: flex-start; padding-top: 8px; border-top: 1px solid var(--line); }
  .submission-pipeline ol { grid-template-columns: repeat(2, 1fr); gap: 12px 0; }
  .request-row { grid-template-columns: 32px minmax(0, 1fr); }
  .request-row .status-label { grid-column: 2; justify-self: start; }
}
</style>
