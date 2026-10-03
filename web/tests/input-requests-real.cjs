/* DATA-07 browser acceptance against a real FastAPI + isolated PostgreSQL. */
const assert = require('node:assert/strict')
const path = require('node:path')
const { spawn } = require('node:child_process')
const { chromium } = require('playwright')

const webRoot = path.resolve(__dirname, '..')
const apiOrigin = process.env.DATA07_API_ORIGIN || 'http://127.0.0.1:58081'
const port = 55174
const origin = `http://127.0.0.1:${port}`
const server = spawn(process.execPath, [path.join(webRoot, 'node_modules/vite/bin/vite.js'),
  '--host', '127.0.0.1', '--port', String(port), '--strictPort'], {
  cwd: webRoot,
  env: { ...process.env, VITE_API_PROXY: apiOrigin },
  stdio: 'pipe',
})
let serverOutput = ''
server.stdout.on('data', (data) => { serverOutput += data })
server.stderr.on('data', (data) => { serverOutput += data })

async function api(pathname, { token, body, key, method = 'GET' } = {}) {
  const headers = {}
  if (token) headers.Authorization = `Bearer ${token}`
  if (key) headers['Idempotency-Key'] = key
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const response = await fetch(`${apiOrigin}${pathname}`, {
    method, headers, body: body === undefined ? undefined : JSON.stringify(body),
  })
  const text = await response.text()
  const data = text ? JSON.parse(text) : null
  assert.ok(response.ok, `${method} ${pathname}: ${response.status} ${text}`)
  return data
}

async function seed() {
  const suffix = Date.now().toString(36)
  const username = `data07_${suffix}`
  const password = 'Data07_StrongPass_1'
  await api('/api/auth/register', { method: 'POST', body: { username, password } })
  const login = await api('/api/auth/login', { method: 'POST', body: { username, password } })
  const token = login.access_token
  const research = await api('/api/sessions', {
    token, method: 'POST', body: { title: '补数浏览器验收', first_message: null },
  })
  const account = await api('/api/business/accounts', {
    token, key: crypto.randomUUID(), method: 'POST',
    body: { name: '浏览器账户', base_currency: 'CNY', declared: {
      total_capital: '100000', capital_basis: 'total', currency: 'CNY',
      as_of: '2026-10-03T00:00:00Z',
    } },
  })
  const plan = await api(`/api/business/sessions/${research.id}/plans`, {
    token, key: crypto.randomUUID(), method: 'POST', body: { name: '浏览器计划', declared: {
      symbol: '600519.SH', market: 'CN', direction: 'buy', plan_price: '20',
      target_price: '25', currency: 'CNY',
    } },
  })
  const run = await api('/api/runs', { token, method: 'POST', body: {
    message: '按计划继续分析', session_id: research.id, investment_input: {
      use_case: 'plan_analysis', account: { id: account.account_id },
      plan: { id: plan.plan_id }, idempotency_key: crypto.randomUUID(),
    },
  } })
  const request = await api(`/api/business/sessions/${research.id}/input-requests`, {
    token, key: crypto.randomUUID(), method: 'POST', body: {
      use_case: 'plan_analysis', source_run_id: run.run_id,
      fields: [
        { name: 'account.total_capital', unit: 'CNY', reason: '确认可用于本次分析的资金' },
        { name: 'plan.target_price', unit: 'CNY', reason: '确认目标价' },
      ],
    },
  })
  const decoyResearch = await api('/api/sessions', {
    token, method: 'POST', body: { title: '另一项研究', first_message: null },
  })
  const decoyPlan = await api(`/api/business/sessions/${decoyResearch.id}/plans`, {
    token, key: crypto.randomUUID(), method: 'POST', body: { name: '另一计划', declared: {
      symbol: '000001.SZ', market: 'CN', direction: 'buy', plan_price: '10',
      target_price: '12', currency: 'CNY',
    } },
  })
  const decoyRun = await api('/api/runs', { token, method: 'POST', body: {
    message: '另一项分析', session_id: decoyResearch.id, investment_input: {
      use_case: 'plan_analysis', account: { id: account.account_id },
      plan: { id: decoyPlan.plan_id }, idempotency_key: crypto.randomUUID(),
    },
  } })
  const decoyRequest = await api(`/api/business/sessions/${decoyResearch.id}/input-requests`, {
    token, key: crypto.randomUUID(), method: 'POST', body: {
      use_case: 'plan_analysis', source_run_id: decoyRun.run_id,
      fields: [{ name: 'plan.plan_price', unit: 'CNY', reason: '另一请求' }],
    },
  })
  const continuation = {
    message: '批量事件续接',
    investment_input: {
      use_case: 'plan_analysis',
      account: { id: account.account_id, expected_revision: 1 },
      plan: { id: plan.plan_id, expected_revision: 1 },
      idempotency_key: crypto.randomUUID(),
    },
  }
  for (let index = 0; index < 100; index++) {
    await api(`/api/business/sessions/${research.id}/input-requests`, {
      token, key: crypto.randomUUID(), method: 'POST', body: {
        use_case: 'plan_analysis', watch_event_id: crypto.randomUUID(), continuation,
        fields: [{ name: 'account.available_capital', unit: 'CNY', reason: `分页请求 ${index}` }],
      },
    })
  }
  return {
    token, research, account, plan, run, request,
    decoy: { research: decoyResearch, plan: decoyPlan, run: decoyRun, request: decoyRequest },
  }
}

async function main() {
  let browser
  try {
    for (let attempt = 0; ; attempt++) {
      if (server.exitCode !== null) throw new Error(serverOutput)
      try { if ((await fetch(origin)).ok) break } catch {}
      if (attempt === 120) throw new Error(`Vite did not start: ${serverOutput}`)
      await new Promise((resolve) => setTimeout(resolve, 250))
    }
    const seeded = await seed()
    browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHANNEL
      ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) })
    const context = await browser.newContext({ viewport: { width: 375, height: 812 } })
    await context.addInitScript((token) => localStorage.setItem('frontier-agent.token', token), seeded.token)
    const page = await context.newPage()
    const errors = []
    page.on('pageerror', (error) => errors.push(error.message))
    await page.goto(origin)
    await page.getByRole('button', { name: '研究', exact: true }).click()
    await page.getByRole('button', { name: /待补资料与处理结果/ }).click()

    let delayOriginal = true
    await page.route(`**/api/business/input-requests/${seeded.request.request_id}`, async (route) => {
      if (delayOriginal) {
        delayOriginal = false
        await new Promise((resolve) => setTimeout(resolve, 400))
      }
      await route.continue()
    })
    await page.locator('.request-row').filter({ hasText: 'account.total_capital、plan.target_price' }).click()
    await page.locator('.request-row').filter({ hasText: 'plan.plan_price' }).click()
    await page.locator('.request-detail').getByText(seeded.decoy.run.run_id, { exact: true }).waitFor()
    await new Promise((resolve) => setTimeout(resolve, 500))
    await page.locator('.request-detail').getByText(seeded.decoy.run.run_id, { exact: true }).waitFor()
    await page.unroute(`**/api/business/input-requests/${seeded.request.request_id}`)

    await page.locator('.request-row').filter({ hasText: 'account.total_capital、plan.target_price' }).click()
    await page.getByRole('textbox', { name: /account.total_capital/ }).fill('80000')
    await page.getByPlaceholder('说明事实来源或仍有歧义的地方').fill('均为本人明确提供')
    await page.getByRole('button', { name: '提交回答', exact: true }).click()
    await page.getByText('剩余待补：plan.target_price', { exact: true }).waitFor()
    await page.getByText('已保存', { exact: true }).waitFor()
    await page.getByRole('textbox', { name: /plan.target_price/ }).fill('28')
    await page.getByRole('button', { name: '提交回答', exact: true }).click()
    await page.getByRole('button', { name: '返回研究查看后续 Run' }).waitFor()

    const detail = await api(`/api/business/input-requests/${seeded.request.request_id}`, { token: seeded.token })
    assert.equal(detail.status, 'answered')
    assert.ok(detail.follow_up_run_id)
    assert.equal(detail.answers.length, 2)
    const original = await api(`/api/runs/${seeded.run.run_id}/investment-snapshot`, { token: seeded.token })
    assert.equal(original.account.revision, 1, 'original snapshot must remain immutable')
    assert.equal(original.plan.revision, 1, 'original snapshot must remain immutable')

    await page.reload()
    await page.getByRole('button', { name: '研究', exact: true }).click()
    await page.getByRole('button', { name: /待补资料与处理结果/ }).click()
    await page.getByText('已回答', { exact: true }).first().waitFor()

    await page.getByRole('button', { name: '导航', exact: true }).click()
    await page.getByRole('button', { name: /通知/ }).click()
    await page.getByText('补充资料已采用', { exact: true }).waitFor()
    const recoveredCursor = Number((await page.locator('.sync-state').textContent())?.replace(/\D/g, ''))
    assert.ok(recoveredCursor > 100, 'notification UI must drain more than one page')

    const answeredNotice = page.locator('.notice-row').filter({ hasText: '补充资料已采用' })
    await answeredNotice.getByRole('button', { name: '打开研究', exact: true }).click()
    await page.getByText('补数浏览器验收', { exact: true }).first().waitFor()

    await page.getByRole('button', { name: '研究', exact: true }).click()
    await page.getByRole('button', { name: /通知/ }).click()
    const originalInputNotice = page.locator('.notice-row').filter({ hasText: '有资料需要补充' }).first()
    await originalInputNotice.getByRole('button', { name: '去补充', exact: true }).click()
    await page.locator('.request-detail').getByText(seeded.run.run_id, { exact: true }).waitFor()

    await page.getByRole('button', { name: '导航', exact: true }).click()
    await page.getByRole('button', { name: /通知/ }).click()
    await page.getByRole('button', { name: '全部已读', exact: true }).click()
    await page.getByText('未读 0', { exact: true }).waitFor()
    const firstEvents = await api('/api/business/events?after=0&limit=100', { token: seeded.token })
    const secondEvents = await api(
      `/api/business/events?after=${firstEvents.cursor}&limit=100`, { token: seeded.token },
    )
    const events = [...firstEvents.items, ...secondEvents.items]
    assert.ok(events.length > 100)
    assert.ok(events.every((item) => item.read), 'read state must persist on the server')

    await page.reload()
    await page.getByRole('button', { name: '研究', exact: true }).click()
    await page.getByRole('button', { name: /通知/ }).click()
    await page.getByText('未读 0', { exact: true }).waitFor()
    assert.deepEqual(errors, [])
    console.log('PASS: partial recovery, late-response guard, targeted navigation, one continuation, notification recovery')
    await context.close()
  } finally {
    if (browser) await browser.close()
    server.kill()
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1 })
