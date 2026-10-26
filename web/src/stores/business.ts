/**
 * Business data store (UI-01…04 / DATA-01…04).
 *
 * Owns the server-backed facts the account/plan workspace reads and writes:
 * the authenticated user's accounts and — for the active research — its plans
 * and the research↔account/plan link. Writes carry an Idempotency-Key and return
 * an operation receipt; this store records receipts so a refreshed page can
 * surface them instead of guessing.
 *
 * Setup-store syntax: only the refs are tracked by components; the plain API
 * calls stay outside the reactivity proxy.
 */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import {
  accounts as accountsApi,
  buySellPlans as buySellPlansApi,
  capitalPlans as capitalPlansApi,
  link as linkApi,
  operations as operationsApi,
  plans as plansApi,
} from '../api'
import type {
  Account,
  BuySellPlan,
  CapitalPlan,
  OperationRecord,
  Plan,
  ResearchLink,
} from '../types'
import type {
  SessionBuySellPlan,
  SessionBuySellPlanInput,
  SessionCapitalPlan,
  SessionPlanPreview,
} from '../business-ui'

function marketOf(plan: Plan): SessionPlanPreview['market'] {
  const market = plan.values?.market
  return market === 'HK' || market === 'US' ? market : 'CN'
}

function text(value: string | null | undefined): string {
  return value ?? ''
}

function marketValue(value: string | null | undefined): 'CN' | 'HK' | 'US' {
  return value === 'HK' || value === 'US' ? value : 'CN'
}

function capitalPlanToPreview(plan: CapitalPlan): SessionCapitalPlan {
  return {
    id: plan.capital_plan_id,
    revision: plan.revision,
    allocatedCapital: text(plan.values?.allocated_capital),
    currency: text(plan.values?.currency),
    accountId: plan.account_id,
    recordState: plan.record_state,
  }
}

function buySellPlanToPreview(plan: BuySellPlan): SessionBuySellPlan {
  const values = plan.values
  return {
    id: plan.buy_sell_plan_id,
    revision: plan.revision,
    symbol: text(values?.symbol),
    market: marketValue(values?.market),
    side: values?.side === 'sell' ? 'sell' : 'buy',
    price: text(values?.price),
    quantity: text(values?.quantity),
    tradedAt: text(values?.traded_at),
    currency: text(values?.currency),
    archived: plan.archived,
  }
}

function writeKey(scope: string): string {
  return `${scope}:${crypto.randomUUID()}`
}

function planToPreview(plan: Plan, researchId: string | null, primaryPlanId: string | null): SessionPlanPreview {
  return {
    id: plan.id,
    sessionId: plan.research_id,
    sessionTitle: '',
    name: plan.name,
    symbol: text(plan.values?.symbol),
    market: marketOf(plan),
    direction: plan.values?.direction === 'sell' ? 'sell' : 'buy',
    allocatedCapital: text(plan.values?.allocated_capital),
    isPrimary: plan.research_id === researchId && plan.id === primaryPlanId,
    status: plan.archived ? 'draft' : 'draft',
  }
}

export const useBusinessStore = defineStore('business', () => {
  const accounts = ref<Account[]>([])
  const plans = ref<Plan[]>([])
  const link = ref<ResearchLink | null>(null)
  const capitalPlan = ref<CapitalPlan | null>(null)
  const buySellPlans = ref<BuySellPlan[]>([])
  const operations = ref<OperationRecord[]>([])
  const loadingAccounts = ref(false)
  const loadingPlans = ref(false)
  const error = ref<string | null>(null)

  let plansForResearchId: string | null = null

  /** Display shape consumed by SessionPlanManager / profile plan overview. */
  const planPreviews = computed<SessionPlanPreview[]>(() =>
    plans.value.map((plan) => planToPreview(plan, plansForResearchId, link.value?.primary_plan_id ?? null)),
  )

  /** 会话规划资金（1:1）；null 表示尚不存在，需要创建。 */
  const capitalPlanPreview = computed<SessionCapitalPlan | null>(() =>
    capitalPlan.value ? capitalPlanToPreview(capitalPlan.value) : null,
  )

  /** 实际买卖价格（规划资金 1:N），归档项排在最后。 */
  const buySellPlanPreviews = computed<SessionBuySellPlan[]>(() =>
    buySellPlans.value
      .map(buySellPlanToPreview)
      .sort((a, b) => Number(a.archived) - Number(b.archived)),
  )

  async function loadAccounts(): Promise<void> {
    loadingAccounts.value = true
    error.value = null
    try {
      const res = await accountsApi.list({ limit: 100 })
      accounts.value = res.accounts
    } catch (err) {
      error.value = err instanceof Error ? err.message : '加载账户资料失败'
      throw err
    } finally {
      loadingAccounts.value = false
    }
  }

  async function loadLink(researchId: string): Promise<void> {
    try {
      link.value = await linkApi.get(researchId)
    } catch {
      link.value = null
    }
  }

  async function loadPlans(researchId: string): Promise<void> {
    loadingPlans.value = true
    error.value = null
    plansForResearchId = researchId
    try {
      const res = await plansApi.list(researchId)
      plans.value = res.plans
    } catch (err) {
      error.value = err instanceof Error ? err.message : '加载计划失败'
      throw err
    } finally {
      loadingPlans.value = false
    }
  }

  async function loadResearch(researchId: string): Promise<void> {
    if (plansForResearchId === researchId && plans.value.length) {
      await Promise.all([loadLink(researchId), loadCapitalPlan(researchId)])
      return
    }
    plansForResearchId = researchId
    await Promise.all([
      loadPlans(researchId),
      loadLink(researchId),
      loadCapitalPlan(researchId),
    ])
  }

  /** 读取会话规划资金（1:1）；存在时顺带读取其下的实际买卖价格（1:N）。 */
  async function loadCapitalPlan(researchId: string): Promise<void> {
    try {
      const res = await capitalPlansApi.get(researchId)
      capitalPlan.value = res.capital_plan
      if (res.capital_plan) {
        await loadBuySellPlans(res.capital_plan.capital_plan_id)
      } else {
        buySellPlans.value = []
      }
    } catch (err) {
      capitalPlan.value = null
      buySellPlans.value = []
      error.value = err instanceof Error ? err.message : '加载规划资金失败'
      throw err
    }
  }

  async function loadBuySellPlans(capitalPlanId: string): Promise<void> {
    const res = await buySellPlansApi.list(capitalPlanId, { limit: 100 })
    buySellPlans.value = res.buy_sell_plans
  }

  /** 创建会话唯一的规划资金；已存在时服务端返回版本冲突，不覆盖原值。 */
  async function createCapitalPlan(
    researchId: string,
    input: { allocatedCapital: string; currency: string },
  ): Promise<void> {
    const declared: Record<string, unknown> = {
      allocated_capital: { value: input.allocatedCapital.trim() },
    }
    if (input.currency.trim()) declared.currency = { value: input.currency.trim() }
    await capitalPlansApi.create(researchId, { declared }, writeKey('capital.create'))
    await loadCapitalPlan(researchId)
  }

  /** 累加分配资金：服务端在现值上加 delta，多次写入不会互相覆盖。 */
  async function allocateCapital(delta: string): Promise<void> {
    const current = capitalPlan.value
    if (!current) throw new Error('请先创建本会话的规划资金')
    await capitalPlansApi.allocate(
      current.capital_plan_id,
      { allocation_delta: delta.trim(), expected_revision: current.revision },
      writeKey('capital.allocate'),
    )
    await loadCapitalPlan(current.research_id)
  }

  /** 重置规划资金为指定值；与累加共用版本流，重置也可追溯。 */
  async function resetCapital(amount: string): Promise<void> {
    const current = capitalPlan.value
    if (!current) throw new Error('请先创建本会话的规划资金')
    await capitalPlansApi.reset(
      current.capital_plan_id,
      { allocated_capital: amount.trim(), expected_revision: current.revision },
      writeKey('capital.reset'),
    )
    await loadCapitalPlan(current.research_id)
  }

  /** 登记一笔实际买卖价格（规划资金 1:N）。 */
  async function createBuySellPlan(input: SessionBuySellPlanInput): Promise<void> {
    const current = capitalPlan.value
    if (!current) throw new Error('请先创建本会话的规划资金')
    const declared: Record<string, unknown> = {
      symbol: { value: input.symbol.trim().toUpperCase() },
      market: { value: input.market },
      side: { value: input.side },
      price: { value: input.price.trim() },
      currency: { value: input.currency.trim() },
    }
    if (input.quantity.trim()) declared.quantity = { value: input.quantity.trim() }
    if (input.tradedAt.trim()) declared.traded_at = { value: input.tradedAt.trim() }
    await buySellPlansApi.create(
      current.capital_plan_id,
      { declared },
      writeKey('buy_sell.create'),
    )
    await loadBuySellPlans(current.capital_plan_id)
  }

  async function archiveBuySellPlan(buySellPlanId: string): Promise<void> {
    const current = capitalPlan.value
    if (!current) throw new Error('请先创建本会话的规划资金')
    await buySellPlansApi.archive(buySellPlanId, writeKey('buy_sell.archive'))
    await loadBuySellPlans(current.capital_plan_id)
  }

  /** Load the most recent write receipts so a refreshed page can restore them. */
  async function loadRecentOperations(scope?: string): Promise<void> {
    try {
      const res = await operationsApi.list({ scope, limit: 30 })
      operations.value = res.operations
    } catch {
      // Receipt recovery is best-effort; a failure must not block the workspace.
    }
  }

  function upsertPlan(plan: Plan): void {
    const index = plans.value.findIndex((item) => item.id === plan.id)
    if (index >= 0) plans.value[index] = plan
    else plans.value = [...plans.value, plan]
  }

  function upsertAccount(account: Account): void {
    const index = accounts.value.findIndex((item) => item.id === account.id)
    if (index >= 0) accounts.value[index] = account
    else accounts.value = [...accounts.value, account]
  }

  function prependOperation(record: OperationRecord): void {
    operations.value = [record, ...operations.value].slice(0, 50)
  }

  function reset(): void {
    accounts.value = []
    plans.value = []
    link.value = null
    capitalPlan.value = null
    buySellPlans.value = []
    operations.value = []
    plansForResearchId = null
    error.value = null
  }

  return {
    accounts,
    plans,
    planPreviews,
    link,
    capitalPlan,
    capitalPlanPreview,
    buySellPlans,
    buySellPlanPreviews,
    operations,
    loadingAccounts,
    loadingPlans,
    error,
    loadAccounts,
    loadPlans,
    loadResearch,
    loadLink,
    loadCapitalPlan,
    loadBuySellPlans,
    loadRecentOperations,
    createCapitalPlan,
    allocateCapital,
    resetCapital,
    createBuySellPlan,
    archiveBuySellPlan,
    upsertPlan,
    upsertAccount,
    prependOperation,
    reset,
  }
})