/* Isolated UI regression: every API request is mocked; never writes live funds.
 * Run: node tests/capital-account-binding.cjs
 */
const assert = require('node:assert/strict')
const path = require('node:path')
const { spawn } = require('node:child_process')
const { chromium } = require('playwright')

const root = path.resolve(__dirname, '..')
const origin = 'http://127.0.0.1:55174'
const server = spawn(process.execPath, [path.join(root, 'node_modules/vite/bin/vite.js'),
  '--host', '127.0.0.1', '--port', '55174', '--strictPort'], { cwd: root, stdio: 'pipe' })
let output = ''
server.stdout.on('data', data => { output += data })
server.stderr.on('data', data => { output += data })
const research = { id: '11111111-1111-4111-8111-111111111111', title: '账户绑定验收', created_at: null, updated_at: null }
const accounts = [
  { id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', name: '默认主账户', base_currency: 'CNY', is_default: true },
  { id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', name: '第二资金账户', base_currency: 'CNY', is_default: false },
  { id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc', name: '美元账户', base_currency: 'USD', is_default: false },
].map(account => ({ ...account, archived: false, current_revision: 1,
  values: { available_capital: '20000', currency: account.base_currency },
  funding: { reserved_capital: '0', allocatable_capital: '20000' } }))
let capital = null
let linked = accounts[0].id
const writes = []

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
    await context.addInitScript(() => localStorage.setItem('frontier-agent.token', 'isolated-binding-test'))
    await context.route(`${origin}/api/**`, async route => {
      const request = route.request()
      const pathname = new URL(request.url()).pathname
      let body = {}
      if (pathname === '/api/business/monitor/heartbeat') {
        await route.fulfill({ contentType: 'application/json', body: '{}' })
        return
      }
      if (request.method() === 'POST') {
        const data = request.postDataJSON()
        writes.push({ pathname, data, key: request.headers()['idempotency-key'] })
        if (pathname.endsWith('/capital-plan')) {
          linked = data.account_id
          capital = { capital_plan_id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd', research_id: research.id,
            account_id: linked, revision: 1, record_state: 'submitted', account_binding_locked: false,
            values: { allocated_capital: data.declared.allocated_capital.value, currency: data.declared.currency.value },
            funding: { remaining_capital: '6000', net_cash_flow: '0', unbooked_count: 0 } }
          body = capital
        } else if (pathname.endsWith('/account')) {
          linked = data.account_id
          capital.account_id = linked
          capital.revision++
          body = { capital_plan_id: capital.capital_plan_id, account_id: linked, revision: capital.revision }
        } else throw new Error(`Unexpected write: ${pathname}`)
      } else if (pathname === '/api/auth/me') body = { id: 'test-user', username: 'binding-test' }
      else if (pathname === '/api/sessions') body = { sessions: [research], total: 1 }
      else if (pathname.endsWith('/capital-plan')) body = { capital_plan: capital }
      else if (pathname.endsWith('/buy-sell-plans')) body = { buy_sell_plans: [] }
      else if (pathname.endsWith('/accounts')) body = { accounts, total: accounts.length }
      else if (pathname.endsWith('/link')) body = { research_id: research.id, account_id: linked, primary_plan_id: null }
      else if (pathname.endsWith('/plans')) body = { plans: [] }
      else if (pathname.endsWith('/operations')) body = { operations: [] }
      else if (pathname.endsWith('/turns')) body = { turns: [], has_more: false }
      else if (pathname.endsWith('/runs')) body = { runs: [] }
      else if (pathname === '/api/models') body = []
      else if (pathname.endsWith(research.id)) body = research
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
    })
    const page = await context.newPage()
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    await page.goto(origin)
    await page.getByRole('button', { name: /账户绑定验收/ }).first().click()
    await page.getByRole('button', { name: '会话资金', exact: true }).click()
    const panel = page.locator('.session-plan-dialog')
    const picker = panel.locator('.capital-plan .el-select').first()
    await picker.click()
    await page.getByRole('option', { name: /美元账户/ }).click()
    await page.waitForFunction(() => document.querySelector('.capital-create')?.textContent.includes('美元 USD'))
    await picker.click()
    await page.getByRole('option', { name: /第二资金账户/ }).click()
    await page.getByPlaceholder('本会话从账户可用资金中划出的金额').fill('6000')
    await page.getByRole('button', { name: '创建并绑定规划资金', exact: true }).click()
    await panel.getByText('当前绑定：第二资金账户', { exact: true }).waitFor()
    assert.equal(writes[0].data.account_id, accounts[1].id)
    assert.equal(writes[0].data.declared.currency.value, 'CNY')
    assert.ok(writes[0].key)
    await picker.click()
    await page.getByRole('option', { name: /默认主账户/ }).click()
    assert.equal(await panel.locator('.buy-sell-submit button').isDisabled(), true)
    await page.getByRole('button', { name: '绑定资金账户', exact: true }).click()
    await panel.getByText('当前绑定：默认主账户', { exact: true }).waitFor()
    assert.equal(writes[1].data.account_id, accounts[0].id)
    assert.equal(writes[1].data.expected_revision, 1)
    assert.ok(writes[1].key)
    capital.account_binding_locked = true
    await panel.getByRole('button', { name: '关闭', exact: true }).click()
    await page.getByRole('button', { name: '会话资金', exact: true }).click()
    await panel.getByText('· 已有资金入账，账户归属已固定').waitFor()
    assert.equal(await picker.locator('.el-select__wrapper.is-disabled').count(), 1)
    assert.equal(await page.getByRole('button', { name: '绑定资金账户', exact: true }).count(), 0)
    assert.equal(writes.length, 2)
    assert.deepEqual(errors, [])
    console.log('PASS: explicit account selection, currency, creation, rebinding, unsaved binding guard, booked account lock')
  } finally {
    if (browser) await browser.close()
    server.kill()
  }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
