/* Saves a trade without a legacy investment plan and expects a conversation Run.
 * All API calls are intercepted; this test never writes live business data.
 * Run: node tests/trade-auto-analysis.cjs
 */
const assert = require('node:assert/strict')
const path = require('node:path')
const { spawn } = require('node:child_process')
const { chromium } = require('playwright')
const root = path.resolve(__dirname, '..')
const origin = 'http://127.0.0.1:55175'
const server = spawn(process.execPath, [path.join(root, 'node_modules/vite/bin/vite.js'),
  '--host', '127.0.0.1', '--port', '55175', '--strictPort'], { cwd: root, stdio: 'pipe' })
let output = ''
server.stdout.on('data', data => { output += data })
server.stderr.on('data', data => { output += data })
const research = { id: '11111111-1111-4111-8111-111111111111', title: '成交自动分析验收' }
const account = { id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', name: '资金账户', base_currency: 'CNY',
  archived: false, is_default: true, values: { available_capital: '10000', currency: 'CNY' },
  funding: { reserved_capital: '6000', allocatable_capital: '4000' } }
const capital = { capital_plan_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', research_id: research.id,
  account_id: account.id, revision: 1, record_state: 'submitted', account_binding_locked: false,
  values: { allocated_capital: '6000', currency: 'CNY' },
  funding: { remaining_capital: '6000', net_cash_flow: '0', unbooked_count: 0 } }
const runId = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd'
const fills = []
const submissions = []
const unexpected = []

async function main() {
  let browser
  try {
    for (let attempt = 0; ; attempt++) {
      if (server.exitCode !== null) throw new Error(output)
      try { if ((await fetch(origin)).ok) break } catch {}
      if (attempt > 120) throw new Error(output)
      await new Promise(resolve => setTimeout(resolve, 250))
    }
    browser = await chromium.launch({ headless: true })
    const context = await browser.newContext({ viewport: { width: 1440, height: 960 } })
    await context.addInitScript(() => localStorage.setItem('frontier-agent.token', 'isolated-trade-test'))
    await context.route(`${origin}/api/**`, async route => {
      const req = route.request()
      const url = new URL(req.url()).pathname
      let body = {}
      if (url.endsWith('/events')) {
        await route.fulfill({ contentType: 'text/event-stream', body: 'data: {"type":"run_status","status":"running"}\n\n' })
        return
      }
      if (req.method() === 'POST' && url.endsWith('/buy-sell-plans')) {
        const values = Object.fromEntries(Object.entries(req.postDataJSON().declared).map(([k, v]) => [k, v.value ?? v]))
        fills.push({ buy_sell_plan_id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc', revision: 1,
          capital_plan_id: capital.capital_plan_id, archived: false, cash_effect: '-1000', values })
        capital.account_binding_locked = true
        body = fills[0]
      } else if (req.method() === 'POST' && url === '/api/runs') {
        submissions.push(req.postDataJSON())
        body = { run_id: runId, session_id: research.id, status: 'queued' }
      } else if (req.method() === 'POST' && url.endsWith('/monitor/heartbeat')) body = {}
      else if (req.method() !== 'GET') unexpected.push(url)
      else if (url === '/api/auth/me') body = { id: 'test-user', username: 'trade-test' }
      else if (url === '/api/sessions') body = { sessions: [research], total: 1 }
      else if (url.endsWith('/capital-plan')) body = { capital_plan: capital }
      else if (url.endsWith('/buy-sell-plans')) body = { buy_sell_plans: fills }
      else if (url.endsWith('/accounts')) body = { accounts: [account], total: 1 }
      else if (url.endsWith('/link')) body = { research_id: research.id, account_id: account.id, primary_plan_id: null }
      else if (url.endsWith('/plans')) body = { plans: [] }
      else if (url.endsWith('/operations')) body = { operations: [] }
      else if (url.endsWith('/turns')) body = { turns: [], has_more: false }
      else if (url.endsWith('/runs')) body = { runs: [] }
      else if (url === '/api/models') body = []
      else if (url.endsWith(runId)) body = { id: runId, status: 'running', session_id: research.id }
      else if (url.endsWith(research.id)) body = research
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
    })
    const page = await context.newPage()
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    await page.goto(origin)
    await page.getByRole('button', { name: /成交自动分析验收/ }).first().click()
    await page.getByRole('button', { name: '会话资金', exact: true }).click()
    const panel = page.locator('.session-plan-dialog')
    await panel.getByText('当前绑定：资金账户', { exact: true }).waitFor()
    await page.getByPlaceholder('代码或标准标识').fill('600000.SH')
    await page.getByPlaceholder('实际成交价，不得用现价代替').fill('10')
    await page.getByPlaceholder('股数/份数').fill('100')
    const date = page.getByPlaceholder('选择实际成交时间')
    await date.fill('2026-11-02 10:00:00')
    await date.press('Tab')
    await panel.locator('.buy-sell-submit button').click()
    for (let attempt = 0; attempt < 40 && submissions.length === 0; attempt++) {
      await new Promise(resolve => setTimeout(resolve, 100))
    }
    assert.equal(fills.length, 1, 'trade must be saved exactly once')
    assert.equal(submissions.length, 1, 'saving a trade must submit automatic analysis without a legacy primary plan')
    assert.equal(submissions[0].session_id, research.id)
    assert.equal(submissions[0].investment_input.account.id, account.id)
    assert.equal(submissions[0].investment_input.use_case, 'holding_cost')
    assert.equal(submissions[0].investment_input.plan, undefined)
    await panel.waitFor({ state: 'hidden' })
    await page.getByText(submissions[0].message, { exact: true }).waitFor()
    assert.deepEqual(errors, [])
    assert.deepEqual(unexpected, [])
    console.log('PASS: one saved trade -> one analysis Run -> visible conversation, without legacy plan')
  } finally {
    if (browser) await browser.close()
    server.kill()
  }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
