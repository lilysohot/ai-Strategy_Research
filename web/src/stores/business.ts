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
  link as linkApi,
  operations as operationsApi,
  plans as plansApi,
} from '../api'
import type { Account, OperationRecord, Plan, ResearchLink } from '../types'
import type { SessionPlanPreview } from '../business-ui'

function marketOf(plan: Plan): SessionPlanPreview['market'] {
  const market = plan.values?.market
  return market === 'HK' || market === 'US' ? market : 'CN'
}

function text(value: string | null | undefined): string {
  return value ?? ''
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
    planPrice: text(plan.values?.plan_price),
    targetPrice: text(plan.values?.target_price),
    isPrimary: plan.research_id === researchId && plan.id === primaryPlanId,
    status: plan.archived ? 'draft' : 'draft',
  }
}

export const useBusinessStore = defineStore('business', () => {
  const accounts = ref<Account[]>([])
  const plans = ref<Plan[]>([])
  const link = ref<ResearchLink | null>(null)
  const operations = ref<OperationRecord[]>([])
  const loadingAccounts = ref(false)
  const loadingPlans = ref(false)
  const error = ref<string | null>(null)

  let plansForResearchId: string | null = null

  /** Display shape consumed by SessionPlanManager / profile plan overview. */
  const planPreviews = computed<SessionPlanPreview[]>(() =>
    plans.value.map((plan) => planToPreview(plan, plansForResearchId, link.value?.primary_plan_id ?? null)),
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
      await loadLink(researchId)
      return
    }
    plansForResearchId = researchId
    await Promise.all([loadPlans(researchId), loadLink(researchId)])
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
    operations.value = []
    plansForResearchId = null
    error.value = null
  }

  return {
    accounts,
    plans,
    planPreviews,
    link,
    operations,
    loadingAccounts,
    loadingPlans,
    error,
    loadAccounts,
    loadPlans,
    loadResearch,
    loadLink,
    loadRecentOperations,
    upsertPlan,
    upsertAccount,
    prependOperation,
    reset,
  }
})