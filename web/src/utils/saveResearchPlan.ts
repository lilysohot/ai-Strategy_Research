import { link, plans } from '../api'
import type { SessionPlanInput } from '../business-ui'

/** Retain one write identity across retries, including a failed link step. */
export function createPlanWriter() {
  let attempt: { fingerprint: string; key: string } | null = null

  async function save(researchId: string, input: SessionPlanInput): Promise<void> {
    const declared: Record<string, unknown> = {
      symbol: { value: input.symbol },
      market: { value: input.market },
      direction: { value: input.direction },
    }
    if (input.allocatedCapital.trim()) {
      declared.allocated_capital = { value: input.allocatedCapital.trim() }
    }
    const body = { name: input.name, declared, allow_incomplete: true }
    const fingerprint = JSON.stringify([researchId, body, input.isPrimary])
    if (attempt?.fingerprint !== fingerprint) {
      attempt = { fingerprint, key: `plan.create:${crypto.randomUUID()}` }
    }
    const key = attempt.key
    const result = await plans.create(researchId, body, key)
    if (typeof result.plan_id !== 'string' || !result.plan_id) {
      throw new Error('服务端未返回计划编号，请重试')
    }
    if (input.isPrimary) {
      await link.set(researchId, { account_id: null, primary_plan_id: result.plan_id }, `${key}:link`)
    }
  }

  return { save, reset: () => { attempt = null } }
}
