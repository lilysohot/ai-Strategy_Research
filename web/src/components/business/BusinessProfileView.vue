<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'

import type { SessionPlanPreview } from '@/business-ui'
import {
  countDraftErrors,
  type BusinessDraft,
  type BusinessDraftErrors,
  validateBusinessDraft,
} from '@/utils/business'
import { useSessionsStore } from '@/stores/sessions'

const props = defineProps<{ plans: readonly SessionPlanPreview[] }>()
const emit = defineEmits<{ dirtyChange: [dirty: boolean] }>()

const section = ref<'account' | 'plan' | 'records'>('account')
const errors = ref<BusinessDraftErrors>({})
const checked = ref(false)
const dirty = ref(false)
let trackingEnabled = true
const sessions = useSessionsStore()
const accountSessionIds = ref<string[]>(sessions.activeId ? [sessions.activeId] : [])

const draft = reactive<BusinessDraft>({
  accountName: '',
  currency: 'CNY',
  capitalBasis: '',
  totalCapital: '',
  availableCapital: '',
  asOf: '',
  symbol: '',
  market: '',
  direction: '',
  planPrice: '',
  planPriceLow: '',
  planPriceHigh: '',
  targetPrice: '',
  riskBudget: '',
  riskBudgetUnit: 'amount',
  positionLimit: '',
  timeWindow: '',
  invalidation: '',
  purchased: false,
  actualPrice: '',
  useCase: 'general_reading',
})

const errorCount = computed(() => countDraftErrors(errors.value))
const canSubmit = computed(() => checked.value && errorCount.value === 0)

const accountLinkedSessions = computed(() =>
  accountSessionIds.value.map((id) => ({
    id,
    title: sessions.list.find((item) => item.id === id)?.title || '未命名研究',
  })),
)

function markDirty(): void {
  if (!trackingEnabled) return
  dirty.value = true
  checked.value = false
  emit('dirtyChange', true)
}

function syncAccountSessions(_ids: string[]): void {
  markDirty()
}

watch(
  draft,
  () => {
    if (!trackingEnabled) return
    dirty.value = true
    checked.value = false
    errors.value = {}
    emit('dirtyChange', true)
  },
  { deep: true },
)

function checkDraft(): void {
  errors.value = validateBusinessDraft(draft)
  checked.value = true
  const firstError = document.querySelector<HTMLElement>('[data-business-error="true"]')
  firstError?.focus()
}

function clearDraft(): void {
  trackingEnabled = false
  Object.assign(draft, {
    accountName: '',
    currency: 'CNY',
    capitalBasis: '',
    totalCapital: '',
    availableCapital: '',
    asOf: '',
    symbol: '',
    market: '',
    direction: '',
    planPrice: '',
    planPriceLow: '',
    planPriceHigh: '',
    targetPrice: '',
    riskBudget: '',
    riskBudgetUnit: 'amount',
    positionLimit: '',
    timeWindow: '',
    invalidation: '',
    purchased: false,
    actualPrice: '',
    useCase: 'general_reading',
  } satisfies BusinessDraft)
  accountSessionIds.value = sessions.activeId ? [sessions.activeId] : []
  errors.value = {}
  checked.value = false
  void nextTick(() => {
    trackingEnabled = true
    dirty.value = false
    emit('dirtyChange', false)
  })
}

function marketLabel(market: SessionPlanPreview['market']): string {
  return { CN: '中国内地', HK: '香港', US: '美国' }[market]
}

function beforeUnload(event: BeforeUnloadEvent): void {
  if (!dirty.value) return
  event.preventDefault()
  event.returnValue = ''
}

onMounted(() => window.addEventListener('beforeunload', beforeUnload))
onBeforeUnmount(() => window.removeEventListener('beforeunload', beforeUnload))
</script>

<template>
  <div class="profile-layout">
    <main class="profile-main">
      <section class="profile-summary" aria-labelledby="profile-summary-title">
        <div>
          <p class="eyebrow">资料闭环 · UI-01—04</p>
          <h2 id="profile-summary-title">把真实资料和研究假设分开</h2>
          <p>
            账户独立维护，计划归属一个研究；空值保持为空，不以计划价或行情价替代真实成交。
          </p>
        </div>
        <div class="summary-state" aria-label="当前资料状态">
          <span class="state-dot" />
          <span>尚未绑定服务端资料</span>
        </div>
      </section>

      <nav class="section-switch" aria-label="资料类型">
        <button type="button" :class="{ active: section === 'account' }" @click="section = 'account'">
          01 账户
        </button>
        <button type="button" :class="{ active: section === 'plan' }" @click="section = 'plan'">
          02 计划
        </button>
        <button type="button" :class="{ active: section === 'records' }" @click="section = 'records'">
          03 实际记录
        </button>
      </nav>

      <section v-show="section === 'account'" class="form-section">
        <header class="section-heading">
          <div>
            <span>账户资料</span>
            <h3>资金口径与数据时点</h3>
          </div>
          <span class="section-note">金额按字符串传输</span>
        </header>

        <div class="form-grid">
          <label class="field field--wide">
            <span>账户名称 <em>必填</em></span>
            <el-input v-model="draft.accountName" placeholder="例如：长期投资主账户" />
            <small v-if="errors.accountName" data-business-error="true" tabindex="-1">{{ errors.accountName }}</small>
          </label>

          <label class="field">
            <span>币种 <em>必填</em></span>
            <el-select v-model="draft.currency" placeholder="选择币种">
              <el-option label="人民币 CNY" value="CNY" />
              <el-option label="美元 USD" value="USD" />
              <el-option label="港币 HKD" value="HKD" />
            </el-select>
            <small v-if="errors.currency" data-business-error="true" tabindex="-1">{{ errors.currency }}</small>
          </label>

          <label class="field">
            <span>资金口径 <em>必填</em></span>
            <el-select v-model="draft.capitalBasis" placeholder="明确口径">
              <el-option label="可交易资产" value="tradable_assets" />
              <el-option label="证券账户总资产" value="brokerage_total" />
              <el-option label="专项策略资金" value="strategy_budget" />
            </el-select>
            <small v-if="errors.capitalBasis" data-business-error="true" tabindex="-1">{{ errors.capitalBasis }}</small>
          </label>

          <label class="field">
            <span>总资金 <i>可选</i></span>
            <el-input v-model="draft.totalCapital" inputmode="decimal" placeholder="真实金额">
              <template #append>{{ draft.currency }}</template>
            </el-input>
            <small v-if="errors.totalCapital" data-business-error="true" tabindex="-1">{{ errors.totalCapital }}</small>
          </label>

          <label class="field">
            <span>可用资金 <i>可选</i></span>
            <el-input v-model="draft.availableCapital" inputmode="decimal" placeholder="真实可用金额">
              <template #append>{{ draft.currency }}</template>
            </el-input>
            <small v-if="errors.availableCapital" data-business-error="true" tabindex="-1">{{ errors.availableCapital }}</small>
          </label>

          <label class="field field--wide">
            <span>数据时点 <em>必填</em></span>
            <el-date-picker
              v-model="draft.asOf"
              type="datetime"
              value-format="YYYY-MM-DDTHH:mm"
              placeholder="选择资料对应时点"
            />
            <small v-if="errors.asOf" data-business-error="true" tabindex="-1">{{ errors.asOf }}</small>
          </label>
        </div>

        <section class="research-linker" aria-labelledby="account-research-link-title">
          <header>
            <div>
              <span>引用关系</span>
              <h4 id="account-research-link-title">引用账户的研究会话</h4>
            </div>
            <small>账户独立存在，可供多个研究引用</small>
          </header>

          <label class="field research-select">
            <span>选择研究会话 <i>可多选</i></span>
            <el-select
              v-model="accountSessionIds"
              multiple
              filterable
              collapse-tags
              collapse-tags-tooltip
              placeholder="搜索引用该账户的研究"
              @change="syncAccountSessions"
            >
              <el-option
                v-for="session in sessions.list"
                :key="session.id"
                :label="session.title || '未命名研究'"
                :value="session.id"
              />
            </el-select>
          </label>

          <div v-if="accountLinkedSessions.length" class="linked-research-list">
            <div
              v-for="session in accountLinkedSessions"
              :key="session.id"
              class="linked-research-row linked-research-row--reference"
            >
              <span class="research-monogram">研</span>
              <span class="linked-research-copy">
                <strong>{{ session.title }}</strong>
                <small>{{ session.id === sessions.activeId ? '当前研究正在引用' : '该研究可使用此账户' }}</small>
              </span>
              <span class="relationship-badge">引用</span>
            </div>
          </div>
          <div v-else class="research-empty">
            账户可先独立保存，之后再由一个或多个研究会话引用。
          </div>
        </section>
      </section>

      <section v-show="section === 'plan'" class="form-section">
        <header class="section-heading">
          <div>
            <span>计划总览</span>
            <h3>计划与所属会话</h3>
          </div>
          <span class="section-note">只读关系清单</span>
        </header>

        <div class="plan-list-guidance">
          <strong>计划从研究会话创建</strong>
          <p>本页只用于核对计划归属。进入具体研究会话，使用标题栏的“会话计划”入口创建或设为主计划。</p>
        </div>

        <div class="plan-list-head" aria-hidden="true">
          <span>计划</span>
          <span>所属会话</span>
          <span>状态</span>
        </div>
        <div v-if="props.plans.length" class="plan-overview-list">
          <article v-for="plan in props.plans" :key="plan.id" class="plan-overview-row">
            <div class="plan-overview-identity">
              <strong>{{ plan.name }}</strong>
              <span>{{ plan.symbol }} · {{ marketLabel(plan.market) }} · {{ plan.direction === 'buy' ? '买入' : '卖出' }}</span>
            </div>
            <div class="plan-session-cell">
              <span class="research-monogram">研</span>
              <span>
                <strong>{{ plan.sessionTitle }}</strong>
                <small>唯一所属会话</small>
              </span>
            </div>
            <div class="plan-status-cell">
              <span v-if="plan.isPrimary" class="plan-primary-label">当前主计划</span>
              <span v-else class="plan-draft-label">草稿</span>
            </div>
          </article>
        </div>
        <div v-else class="plan-overview-empty">
          <strong>暂无计划</strong>
          <p>请返回任一研究会话，从“会话计划”入口创建。创建后会在这里显示其唯一所属会话。</p>
        </div>
      </section>

      <section v-show="section === 'records'" class="form-section">
        <header class="section-heading">
          <div>
            <span>实际记录</span>
            <h3>计划、成交与持仓互不冒充</h3>
          </div>
        </header>
        <div class="execution-status">
          <button type="button" :class="{ active: !draft.purchased }" @click="draft.purchased = false">
            <strong>未成交</strong><small>实际成交价保持为空</small>
          </button>
          <button type="button" :class="{ active: draft.purchased }" @click="draft.purchased = true">
            <strong>已买入</strong><small>需要真实成交信息</small>
          </button>
        </div>
        <div v-if="draft.purchased" class="form-grid record-grid">
          <label class="field">
            <span>实际成交价 <em>必填</em></span>
            <el-input v-model="draft.actualPrice" inputmode="decimal" placeholder="用户明确提供的价格" />
            <small v-if="errors.actualPrice" data-business-error="true" tabindex="-1">{{ errors.actualPrice }}</small>
          </label>
          <div class="record-placeholder">
            数量、费用与成交时间将在成交登记页按同一版本提交；本页不根据持仓反推成交。
          </div>
        </div>
        <p v-if="errors.purchased" class="record-error" data-business-error="true" tabindex="-1">{{ errors.purchased }}</p>
      </section>
    </main>

    <aside class="profile-aside" aria-label="资料提交状态">
      <div class="aside-block aside-block--accent">
        <span class="aside-kicker">交互预览</span>
        <h3>服务端契约尚未接入</h3>
        <p>这里不会把业务正文写入 localStorage，也不会把“前端已校验”显示为“资料已保存”。</p>
      </div>

      <div class="aside-block">
        <span class="aside-kicker">提交前检查</span>
        <dl class="readiness-list">
          <div><dt>当前视图</dt><dd>{{ section === 'plan' ? '计划关系总览' : section === 'account' ? '账户资料' : '实际记录' }}</dd></div>
          <div><dt>账户引用</dt><dd>{{ accountLinkedSessions.length }} 个研究</dd></div>
          <div><dt>计划数量</dt><dd>{{ props.plans.length }} 项</dd></div>
          <div><dt>草稿</dt><dd>{{ dirty ? '仅本页内存' : '尚未填写' }}</dd></div>
          <div><dt>校验</dt><dd>{{ checked ? (errorCount ? `${errorCount} 项待处理` : '前端检查通过') : '尚未检查' }}</dd></div>
          <div><dt>服务端版本</dt><dd>待 DATA-01</dd></div>
        </dl>
      </div>

      <div v-if="section === 'plan'" class="aside-block">
        <span class="aside-kicker">入口规则</span>
        <h3>计划从会话进入</h3>
        <p>返回具体研究会话，点击标题栏“会话计划”。资料中心不提供跨会话创建或重新绑定。</p>
      </div>

      <div v-else-if="checked" class="aside-block" :class="{ 'aside-block--ok': canSubmit }" aria-live="polite">
        <span class="aside-kicker">检查结果</span>
        <h3>{{ canSubmit ? '可以进入服务端校验' : '请先处理定位到的字段' }}</h3>
        <p v-if="canSubmit">前端只检查格式与用途必填项；真实性、归属和版本仍由服务端强制校验。</p>
        <p v-else>页面已在字段下方标出问题。一般阅读不会因资金为空而被阻断。</p>
      </div>

      <div v-if="section !== 'plan'" class="aside-actions">
        <el-button type="primary" @click="checkDraft">检查可提交性</el-button>
        <el-tooltip content="等待 DATA-01/03 接口与幂等契约" placement="top">
          <span><el-button disabled>保存资料</el-button></span>
        </el-tooltip>
        <el-tooltip content="等待 DATA-05/06 分析快照接口" placement="top">
          <span><el-button disabled>保存并分析</el-button></span>
        </el-tooltip>
        <el-button text :disabled="!dirty" @click="clearDraft">清除本页草稿</el-button>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.profile-layout { display: grid; grid-template-columns: minmax(0, 1fr) 320px; min-height: 100%; }
.profile-main { min-width: 0; padding: 28px clamp(20px, 3vw, 44px) 56px; overflow: auto; }
.profile-summary { display: flex; justify-content: space-between; gap: 28px; padding-bottom: 26px; border-bottom: 1px solid var(--line); }
.profile-summary h2 { margin: 4px 0 8px; max-width: 720px; font-family: 'Songti SC', 'Source Han Serif SC', serif; font-size: clamp(24px, 3vw, 36px); line-height: 1.18; }
.profile-summary p:not(.eyebrow) { max-width: 680px; margin: 0; color: var(--muted); }
.eyebrow, .aside-kicker, .section-heading span, .section-note { color: var(--accent); font-size: 11px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; }
.summary-state { align-self: flex-start; display: flex; gap: 8px; align-items: center; padding-top: 8px; color: var(--muted); white-space: nowrap; }
.state-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--quiet); }
.section-switch { display: flex; gap: 0; margin: 28px 0 6px; border-bottom: 1px solid var(--line); }
.section-switch button { padding: 11px 16px; border: 0; border-bottom: 2px solid transparent; background: transparent; color: var(--muted); cursor: pointer; }
.section-switch button.active { border-bottom-color: var(--accent); color: var(--text); }
.form-section { padding: 26px 0 10px; }
.section-heading { display: flex; justify-content: space-between; gap: 18px; margin-bottom: 22px; }
.section-heading h3 { margin: 3px 0 0; font-size: 20px; }
.section-note { color: var(--muted); letter-spacing: .03em; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px 22px; }
.field { display: flex; min-width: 0; flex-direction: column; gap: 7px; color: var(--text-soft); }
.field--wide { grid-column: 1 / -1; }
.field > span { font-size: 13px; font-weight: 600; }
.field em { color: var(--warning); font-style: normal; }
.field i { color: var(--muted); font-size: 11px; font-style: normal; font-weight: 400; }
.field small, .record-error { color: var(--danger); font-size: 12px; }
.field :deep(.el-select), .field :deep(.el-date-editor) { width: 100%; }
.field select { border: 0; background: transparent; color: var(--text-soft); }
.research-linker { margin: 0 0 26px; padding: 18px; border: 1px solid var(--line); background: color-mix(in srgb, var(--accent) 3%, var(--bg-input)); }
.form-grid + .research-linker { margin-top: 26px; }
.research-linker > header { display: flex; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
.research-linker > header span { color: var(--accent); font-size: 10px; font-weight: 700; letter-spacing: .1em; }
.research-linker h4 { margin: 2px 0 0; font-size: 17px; }
.research-linker > header small { color: var(--muted); }
.research-select { margin-bottom: 14px; }
.linked-research-list { display: flex; flex-direction: column; border-top: 1px solid var(--line); }
.linked-research-row { display: grid; grid-template-columns: 30px minmax(0, 1fr) auto; gap: 10px; align-items: center; padding: 12px 0; border-bottom: 1px solid var(--line); }
.research-monogram { display: grid; place-items: center; width: 28px; height: 28px; border: 1px solid var(--line-strong); border-radius: 50%; color: var(--accent); font-family: 'Songti SC', serif; font-size: 12px; }
.linked-research-copy { display: flex; min-width: 0; flex-direction: column; }
.linked-research-copy strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.linked-research-copy small, .research-empty { color: var(--muted); font-size: 12px; }
.relationship-badge { padding: 3px 7px; border: 1px solid var(--line-strong); border-radius: 999px; color: var(--muted); font-size: 11px; }
.research-empty { padding: 14px 0 2px; border-top: 1px solid var(--line); }
.plan-list-guidance { display: grid; grid-template-columns: 180px minmax(0, 1fr); gap: 20px; align-items: baseline; padding: 14px 0 22px; border-top: 2px solid var(--accent); border-bottom: 1px solid var(--line); }
.plan-list-guidance p, .plan-overview-empty p { margin: 0; color: var(--muted); font-size: 13px; }
.plan-list-head, .plan-overview-row { display: grid; grid-template-columns: minmax(220px, 1.15fr) minmax(220px, 1fr) 110px; gap: 20px; align-items: center; }
.plan-list-head { padding: 14px 12px 8px; color: var(--muted); font-size: 11px; letter-spacing: .08em; }
.plan-overview-list { border-top: 1px solid var(--line); }
.plan-overview-row { padding: 16px 12px; border-bottom: 1px solid var(--line); }
.plan-overview-identity, .plan-session-cell > span:last-child { display: flex; min-width: 0; flex-direction: column; }
.plan-overview-identity strong, .plan-session-cell strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.plan-overview-identity span, .plan-session-cell small { color: var(--muted); font-size: 12px; }
.plan-session-cell { display: flex; min-width: 0; align-items: center; gap: 10px; }
.plan-primary-label, .plan-draft-label { display: inline-flex; padding: 3px 7px; border: 1px solid var(--line-strong); border-radius: 999px; font-size: 11px; white-space: nowrap; }
.plan-primary-label { border-color: color-mix(in srgb, var(--accent) 60%, var(--line)); color: var(--accent); }
.plan-draft-label { color: var(--muted); }
.plan-overview-empty { padding: 36px 0; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
.plan-overview-empty strong { display: block; margin-bottom: 5px; }
.execution-status { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
.execution-status button { display: flex; flex-direction: column; gap: 4px; padding: 16px; border: 1px solid var(--line); border-radius: 5px; background: var(--bg-input); color: var(--text); text-align: left; cursor: pointer; }
.execution-status button.active { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 8%, var(--bg-input)); }
.execution-status small, .record-placeholder { color: var(--muted); }
.record-grid { margin-top: 18px; }
.record-placeholder { align-self: end; padding: 11px 12px; border-top: 1px solid var(--line); font-size: 12px; }
.profile-aside { padding: 28px 22px; border-left: 1px solid var(--line); background: #141711; overflow: auto; }
.aside-block { padding: 18px 0; border-bottom: 1px solid var(--line); }
.aside-block:first-child { padding-top: 0; }
.aside-block h3 { margin: 6px 0 8px; font-size: 16px; }
.aside-block p { margin: 0; color: var(--muted); font-size: 13px; }
.aside-block--accent { border-top: 2px solid var(--accent); padding-top: 14px !important; }
.aside-block--ok { border-bottom-color: color-mix(in srgb, var(--ok) 60%, var(--line)); }
.readiness-list { margin: 8px 0 0; }
.readiness-list div { display: grid; grid-template-columns: 92px 1fr; gap: 8px; padding: 7px 0; }
.readiness-list dt { color: var(--muted); }
.readiness-list dd { margin: 0; text-align: right; }
.aside-actions { display: flex; flex-direction: column; gap: 9px; padding-top: 20px; }
.aside-actions .el-button, .aside-actions > span { width: 100%; margin: 0; }
.aside-actions > span :deep(.el-button) { width: 100%; }

@media (max-width: 980px) {
  .profile-layout { grid-template-columns: 1fr; }
  .profile-aside { border-top: 1px solid var(--line); border-left: 0; }
}
@media (max-width: 640px) {
  .profile-main { padding: 20px 14px 36px; }
  .profile-summary { flex-direction: column; gap: 10px; }
  .form-grid, .execution-status { grid-template-columns: 1fr; }
  .field--wide { grid-column: auto; }
  .section-switch { overflow-x: auto; }
  .section-switch button { flex: none; padding-inline: 12px; }
  .research-linker { padding: 14px; }
  .research-linker > header { flex-direction: column; gap: 4px; }
  .linked-research-row { grid-template-columns: 30px minmax(0, 1fr); }
  .relationship-badge { grid-column: 2; justify-self: start; }
  .plan-list-guidance { grid-template-columns: 1fr; gap: 5px; }
  .plan-list-head { display: none; }
  .plan-overview-row { grid-template-columns: 1fr auto; gap: 10px; }
  .plan-session-cell { grid-column: 1 / -1; grid-row: 2; }
  .plan-status-cell { grid-column: 2; grid-row: 1; }
}
</style>
