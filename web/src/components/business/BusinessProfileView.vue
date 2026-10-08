<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { accounts as accountsApi, runs as runsApi } from '@/api'
import { ApiError } from '@/api/client'
import type { SessionPlanPreview } from '@/business-ui'
import { useBusinessStore } from '@/stores/business'
import { useSessionsStore } from '@/stores/sessions'
import type { Account } from '@/types'
import {
  countDraftErrors,
  type BusinessDraft,
  type BusinessDraftErrors,
  validateBusinessDraft,
} from '@/utils/business'

const props = defineProps<{ plans: readonly SessionPlanPreview[] }>()
const emit = defineEmits<{ dirtyChange: [dirty: boolean] }>()

const section = ref<'account' | 'plan' | 'records'>('account')
const errors = ref<BusinessDraftErrors>({})
const checked = ref(false)
const dirty = ref(false)
let trackingEnabled = true
const sessions = useSessionsStore()
const business = useBusinessStore()

const accountSessionIds = ref<string[]>(sessions.activeId ? [sessions.activeId] : [])

const accounts = computed(() => business.accounts)
const accountId = ref<string | null>(null)
const serverRevision = ref<number | null>(null)
const saving = ref(false)
const conflict = ref<{
  expected: number
  current: number
  fieldDiff: Array<{ field: string; theirs: string; mine: string }>
} | null>(null)

let accountKeys = new Map<string, string>()

function idempotencyKey(scope: string): string {
  const existing = accountKeys.get(scope)
  if (existing) return existing
  const key = crypto.randomUUID()
  accountKeys.set(scope, key)
  return key
}

function clearActionKey(scope: string): void {
  accountKeys.delete(scope)
}

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
  allocatedCapital: '',
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
const canSaveAccount = computed(() => section.value === 'account' || section.value === 'records')

const accountLinkedSessions = computed(() =>
  accountSessionIds.value.map((id) => ({
    id,
    title: sessions.list.find((item) => item.id === id)?.title || '未命名研究',
  })),
)

function hydrateFromAccount(account: Account): void {
  trackingEnabled = false
  const values = account.values
  draft.accountName = account.name
  draft.currency = account.base_currency || values.currency || ''
  draft.capitalBasis = values.capital_basis ?? ''
  draft.totalCapital = values.total_capital ?? ''
  draft.availableCapital = values.available_capital ?? ''
  draft.asOf = values.as_of ?? ''
  accountId.value = account.id
  serverRevision.value = account.revision
  errors.value = {}
  checked.value = false
  void nextTick(() => {
    trackingEnabled = true
    dirty.value = false
    emit('dirtyChange', false)
  })
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

watch(accountId, () => {
  if (!accountId.value) return
  const account = accounts.value.find((item) => item.id === accountId.value)
  if (account) hydrateFromAccount(account)
})

function loadAccount(id: string): void {
  accountId.value = id
}

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
    allocatedCapital: '',
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
  accountId.value = null
  serverRevision.value = null
  accountSessionIds.value = sessions.activeId ? [sessions.activeId] : []
  errors.value = {}
  checked.value = false
  void nextTick(() => {
    trackingEnabled = true
    dirty.value = false
    emit('dirtyChange', false)
  })
}

/** Build the account ``declared`` map — decimal strings, never JS Number. */
function buildAccountDeclared(capitalBasis: string, total: string, available: string, asOf: string): Record<string, string> {
  const declared: Record<string, string> = {}
  // Blank values are simply omitted: the server treats a missing/provided-empty
  // field as incomplete (pending), not as a fabricated user value.
  if (total.trim()) declared.total_capital = total.trim()
  if (available.trim()) declared.available_capital = available.trim()
  if (asOf.trim()) declared.as_of = asOf.trim()
  if (capitalBasis.trim()) declared.capital_basis = capitalBasis.trim()
  return declared
}

async function loadConflictDiff(): Promise<void> {
  if (!accountId.value) return
  try {
    const res = await accountsApi.revisions(accountId.value, { limit: 3 })
    const latest = res.revisions[0]
    if (!latest) return
    const fields = ['total_capital', 'available_capital', 'capital_basis', 'as_of'] as const
    const fieldDiff = fields
      .filter((field) => (latest.values[field] ?? '') !== draft[fieldMap[field]] && (draft[fieldMap[field]] ?? '').trim())
      .map((field) => ({ field, theirs: latest.values[field] ?? '', mine: draft[fieldMap[field]] }))
    conflict.value = {
      expected: serverRevision.value ?? 0,
      current: latest.revision,
      fieldDiff,
    }
  } catch {
    conflict.value = { expected: serverRevision.value ?? 0, current: serverRevision.value ?? 0, fieldDiff: [] }
  }
}

const fieldMap = {
  total_capital: 'totalCapital',
  available_capital: 'availableCapital',
  capital_basis: 'capitalBasis',
  as_of: 'asOf',
} as const

async function saveAccount(analyze = false): Promise<string | null> {
  if (saving.value || !canSaveAccount.value) return null
  if (!canSubmit.value) {
    checkDraft()
    ElMessage.warning('请先通过提交检查')
    return null
  }
  saving.value = true
  try {
    const declared = buildAccountDeclared(draft.capitalBasis, draft.totalCapital, draft.availableCapital, draft.asOf)
    let result: { replayed: boolean; operation_id: string; [k: string]: unknown }
    if (accountId.value && serverRevision.value !== null) {
      result = (await accountsApi.update(accountId.value, {
        declared,
        expected_revision: serverRevision.value,
        allow_incomplete: true,
      }, idempotencyKey('account.update'))) as unknown as { replayed: boolean; operation_id: string }
      clearActionKey('account.update')
    } else {
      result = await accountsApi.create({
        name: draft.accountName.trim(),
        base_currency: draft.currency,
        declared,
        use_case: draft.useCase,
        allow_incomplete: false,
      }, idempotencyKey('account.create'))
      clearActionKey('account.create')
      accountId.value = String(result.account_id ?? '')
    }
    const nextRevision = Number(result.revision ?? serverRevision.value ?? 1)
    serverRevision.value = nextRevision
    business.prependOperation({
      operation_id: result.operation_id,
      scope: accountId.value ? 'account.create/update' : 'account.create',
      replayed: result.replayed,
      status: 'succeeded',
      created_at: new Date().toISOString(),
      result: { account_id: accountId.value, revision: nextRevision },
    })
    // Refresh the server-backed list so the account card reflects saved state.
    await business.loadAccounts()
    ElMessage.success(accountId.value ? '资料已保存' : '账户已创建')
    if (!analyze) return String(accountId.value ?? '')
    return String(result.account_id ?? accountId.value ?? '')
  } catch (error) {
    if (error instanceof ApiError && error.status === 409) {
      await loadConflictDiff()
    } else {
      ElMessage.error(error instanceof Error ? error.message : '保存资料失败')
    }
    accountKeys.clear()
    return null
  } finally {
    saving.value = false
  }
}

async function saveAndAnalyze(): Promise<void> {
  const savedAccountId = await saveAccount(true)
  if (!savedAccountId || !sessions.activeId) return
  try {
    const res = await runsApi.submit({
      message: `请基于已保存的账户资料（${draft.accountName.trim() || savedAccountId}）进行投资分析。`,
      session_id: sessions.activeId,
      investment_input: {
        use_case: draft.useCase,
        account: { id: savedAccountId, expected_revision: serverRevision.value },
        idempotency_key: idempotencyKey('run.analyze'),
      },
    })
    clearActionKey('run.analyze')
    ElMessage.success(`分析已派发（Run ${res.run_id.slice(0, 8)}）`)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '分析派发失败')
    accountKeys.delete('run.analyze')
  }
}

async function archiveAccount(): Promise<void> {
  if (!accountId.value) return
  try {
    await ElMessageBox.confirm('归档后账户不再被新的分析采用，关联监控会暂停。', '归档账户', {
      type: 'warning', confirmButtonText: '确认归档', cancelButtonText: '保留',
    })
  } catch {
    return
  }
  saving.value = true
  try {
    await accountsApi.archive(accountId.value, idempotencyKey('account.archive'))
    clearActionKey('account.archive')
    ElMessage.success('账户已归档')
    await business.loadAccounts()
    clearDraft()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '归档失败')
  } finally {
    saving.value = false
  }
}

function acceptNewRevision(): void {
  if (!conflict.value) return
  serverRevision.value = conflict.value.current
  conflict.value = null
  ElMessage.info('已沿用服务端当前版本，可重新提交')
}

function marketLabel(market: SessionPlanPreview['market']): string {
  return { CN: '中国内地', HK: '香港', US: '美国' }[market]
}

function beforeUnload(event: BeforeUnloadEvent): void {
  if (!dirty.value) return
  event.preventDefault()
  event.returnValue = ''
}

async function loadInitialData(): Promise<void> {
  try {
    await business.loadAccounts()
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '加载账户资料失败')
  }
  if (sessions.activeId) {
    try {
      await business.loadResearch(sessions.activeId)
    } catch {
      // Plans load is optional for the account card view.
    }
  }
}

onMounted(async () => {
  window.addEventListener('beforeunload', beforeUnload)
  await loadInitialData()
  if (accounts.value.length) hydrateFromAccount(accounts.value[0])
})
onBeforeUnmount(() => window.removeEventListener('beforeunload', beforeUnload))
defineExpose({ clearDraft })
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
          <span>{{ accountId ? `服务端 v${serverRevision}` : '尚未绑定服务端资料' }}</span>
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

      <section v-if="section === 'account'" class="form-section" v-loading="business.loadingAccounts">
        <label class="field field--wide">
          <span>读取已有账户</span>
          <el-select v-model="accountId" placeholder="选择要查看的账户" clearable @change="loadAccount">
            <el-option v-for="account in accounts" :key="account.id" :label="`${account.name} · v${account.revision}${account.archived ? '（已归档）' : ''}`" :value="account.id" />
          </el-select>
        </label>
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
      </section>

      <section v-else-if="section === 'plan'" class="form-section">
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
                <strong>{{ plan.sessionTitle || '服务端计划' }}</strong>
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

      <section v-else class="form-section">
        <header class="section-heading">
          <div>
            <span>实际记录</span>
            <h3>计划、成交与持仓互不冒充</h3>
          </div>
        </header>
        <p class="record-placeholder">成交登记与更正将在后续按同一版本契约接入；本页不根据持仓反推成交。</p>
      </section>
    </main>

    <aside class="profile-aside" aria-label="资料提交状态">
      <div class="aside-block aside-block--accent">
        <span class="aside-kicker">服务端契约</span>
        <h3>{{ accountId ? `已绑定资料 v${serverRevision}` : '尚未绑定资料' }}</h3>
        <p>业务正文不写入 localStorage；“前端已校验”不会显示为“资料已保存”，以服务端回执为准。</p>
      </div>

      <div class="aside-block">
        <span class="aside-kicker">提交前检查</span>
        <dl class="readiness-list">
          <div><dt>当前视图</dt><dd>{{ section === 'plan' ? '计划关系总览' : section === 'account' ? '账户资料' : '实际记录' }}</dd></div>
          <div><dt>账户引用</dt><dd>{{ accountLinkedSessions.length }} 个研究</dd></div>
          <div><dt>计划数量</dt><dd>{{ props.plans.length }} 项</dd></div>
          <div><dt>草稿</dt><dd>{{ dirty ? '仅本页内存' : '尚未填写' }}</dd></div>
          <div><dt>校验</dt><dd>{{ checked ? (errorCount ? `${errorCount} 项待处理` : '前端检查通过') : '尚未检查' }}</dd></div>
          <div><dt>服务端版本</dt><dd>{{ serverRevision ?? '—' }}</dd></div>
        </dl>
      </div>

      <div v-if="checked" class="aside-block" :class="{ 'aside-block--ok': canSubmit }" aria-live="polite">
        <span class="aside-kicker">检查结果</span>
        <h3>{{ canSubmit ? '可以进入服务端校验' : '请先处理定位到的字段' }}</h3>
        <p v-if="canSubmit">前端只检查格式与用途必填项；真实性、归属和版本仍由服务端强制校验。</p>
        <p v-else>页面已在字段下方标出问题。</p>
      </div>

      <template v-if="section !== 'plan'">
        <div v-if="conflict" class="aside-block version-conflict">
          <span class="aside-kicker">版本冲突</span>
          <h3>服务端资料已更新</h3>
          <p>你的版本 v{{ conflict.expected }}，服务端当前 v{{ conflict.current }}。</p>
          <ul v-if="conflict.fieldDiff.length">
            <li v-for="item in conflict.fieldDiff" :key="item.field">{{ item.field }}：服务端={{ item.theirs }}，你={{ item.mine }}</li>
          </ul>
          <el-button type="primary" size="small" @click="acceptNewRevision">沿用服务端当前版本</el-button>
          <el-button size="small" @click="conflict = null">返回修改</el-button>
        </div>

        <div class="aside-actions">
          <el-button type="primary" @click="checkDraft">检查可提交性</el-button>
          <el-button type="primary" :disabled="!canSaveAccount || !canSubmit" :loading="saving" @click="saveAccount(false)">保存资料</el-button>
          <el-tooltip content="先保存业务资料，再派发分析 Run" placement="top">
            <span><el-button type="primary" :disabled="!canSaveAccount || !canSubmit" :loading="saving" @click="saveAndAnalyze">保存并分析</el-button></span>
          </el-tooltip>
          <el-button v-if="accountId" text type="danger" :disabled="saving" @click="archiveAccount">归档本账户</el-button>
          <el-button text :disabled="!dirty" @click="clearDraft">清除本页草稿</el-button>
        </div>
      </template>
      <p v-else class="aside-note">计划通过研究会话的“会话计划”入口创建。</p>
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
.field :deep(.el-select), .field :deep(.el-date-editor) { width: 100%; }
.field select { border: 0; background: transparent; color: var(--text-soft); }
.field { display: flex; min-width: 0; flex-direction: column; gap: 7px; color: var(--text-soft); }
.field--wide { grid-column: 1 / -1; }
.field > span { font-size: 13px; font-weight: 600; }
.field em { color: var(--warning); font-style: normal; }
.field i { color: var(--muted); font-size: 11px; font-style: normal; font-weight: 400; }
.field small { color: var(--danger); font-size: 12px; }
.form-section { padding: 26px 0 10px; }
.section-heading { display: flex; justify-content: space-between; gap: 18px; margin-bottom: 22px; }
.section-heading h3 { margin: 3px 0 0; font-size: 20px; }
.section-note { color: var(--muted); letter-spacing: .03em; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px 22px; }
.research-linker { margin: 0 0 26px; padding: 18px; border: 1px solid var(--line); background: color-mix(in srgb, var(--accent) 3%, var(--bg-input)); }
.research-linker > header { display: flex; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
.research-linker > header span { color: var(--accent); font-size: 10px; font-weight: 700; letter-spacing: .1em; }
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
.research-monogram { display: grid; place-items: center; width: 28px; height: 28px; border: 1px solid var(--line-strong); border-radius: 50%; color: var(--accent); font-family: 'Songti SC', serif; font-size: 12px; }
.plan-primary-label, .plan-draft-label { display: inline-flex; padding: 3px 7px; border: 1px solid var(--line-strong); border-radius: 999px; font-size: 11px; white-space: nowrap; }
.plan-primary-label { border-color: color-mix(in srgb, var(--accent) 60%, var(--line)); color: var(--accent); }
.plan-draft-label { color: var(--muted); }
.plan-overview-empty { padding: 36px 0; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
.plan-overview-empty strong { display: block; margin-bottom: 5px; }
.record-placeholder, .aside-note { color: var(--muted); font-size: 13px; }
.profile-aside { padding: 28px 22px; border-left: 1px solid var(--line); background: #141711; overflow: auto; }
.aside-block { padding: 18px 0; border-bottom: 1px solid var(--line); }
.aside-block:first-child { padding-top: 0; }
.aside-block h3 { margin: 6px 0 8px; font-size: 16px; }
.aside-block p { margin: 0; color: var(--muted); font-size: 13px; }
.aside-block ul { margin: 8px 0 12px; padding-left: 18px; color: var(--text-soft); font-size: 12px; }
.aside-block--accent { border-top: 2px solid var(--accent); padding-top: 14px !important; }
.aside-block--ok { border-bottom-color: color-mix(in srgb, var(--ok) 60%, var(--line)); }
.version-conflict { border-bottom-color: var(--warning); }
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
  .plan-list-guidance { grid-template-columns: 1fr; gap: 5px; }
  .plan-list-head { display: none; }
  .plan-overview-row { grid-template-columns: 1fr auto; gap: 10px; }
  .plan-session-cell { grid-column: 1 / -1; grid-row: 2; }
  .plan-status-cell { grid-column: 2; grid-row: 1; }
}
</style>