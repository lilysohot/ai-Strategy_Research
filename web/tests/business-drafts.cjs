/* Browser regression for the preview UI only. API responses are isolated fixtures.
 * Run with Playwright available locally or on NODE_PATH:
 *   node tests/business-drafts.cjs
 */
const assert = require('node:assert/strict')
const path = require('node:path')
const { spawn } = require('node:child_process')
const { chromium } = require('playwright')

const webRoot = path.resolve(__dirname, '..')
const port = 55173
const origin = `http://127.0.0.1:${port}`
const server = spawn(process.execPath, [path.join(webRoot, 'node_modules/vite/bin/vite.js'),
  '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: webRoot, stdio: 'pipe' })
let serverOutput = ''
server.stdout.on('data', (data) => { serverOutput += data })
server.stderr.on('data', (data) => { serverOutput += data })
const sessions = ['11111111-1111-4111-8111-111111111111', '22222222-2222-4222-8222-222222222222']
  .map((id, index) => ({ id, title: `研究${index === 0 ? 'A' : 'B'}`, created_at: null, updated_at: null }))

async function main() {
  let browser
  try {
    for (let attempt = 0; ; attempt++) {
      if (server.exitCode !== null) throw new Error(serverOutput)
      try { if ((await fetch(origin)).ok) break } catch {}
      if (attempt === 120) throw new Error(`Vite did not start: ${serverOutput}`)
      await new Promise((resolve) => setTimeout(resolve, 250))
    }
    browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHANNEL
      ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) })
    const context = await browser.newContext({ viewport: { width: 1440, height: 960 } })
    await context.addInitScript(() => localStorage.setItem('frontier-agent.token', 'isolated-test'))
    await context.route(`${origin}/api/**`, async (route) => {
      const pathname = new URL(route.request().url()).pathname
      let body = {}
      if (pathname === '/api/auth/me') body = { id: 'test-user', username: 'draft-test' }
      else if (pathname === '/api/sessions') body = { sessions, total: sessions.length }
      else if (pathname.endsWith('/turns')) body = { turns: [], has_more: false }
      else if (pathname.endsWith('/runs')) body = { runs: [] }
      else if (pathname === '/api/models') body = []
      else body = sessions.find((session) => pathname.endsWith(session.id)) || {}
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
    })
    const page = await context.newPage()
    const errors = []
    page.on('pageerror', (error) => { errors.push(error.message); console.error('PAGE ERROR:', error.message) })
    page.on('response', (response) => { if (response.status() >= 400) console.error('HTTP:', response.status(), response.url()) })
    await page.goto(origin)
    const profiles = () => page.getByRole('button', { name: /交易账户资料/ })
    const accountName = () => page.getByPlaceholder('例如：长期投资主账户')
    await profiles().click()
    await accountName().fill('未保存账户')
    page.once('dialog', (dialog) => dialog.dismiss())
    await page.getByRole('button', { name: '返回研究', exact: true }).click()
    assert.equal(await accountName().inputValue(), '未保存账户', 'cancel must preserve draft')
    page.once('dialog', (dialog) => dialog.accept())
    await page.getByRole('button', { name: '返回研究', exact: true }).click()
    await profiles().click()
    assert.equal(await accountName().inputValue(), '', 'confirmed leave must discard draft')

    await accountName().fill('留在原会话')
    page.once('dialog', (dialog) => dialog.dismiss())
    await page.getByRole('button', { name: /研究A/ }).first().click()
    assert.equal(await accountName().inputValue(), '留在原会话', 'active research navigation must guard too')
    page.once('dialog', (dialog) => dialog.dismiss())
    await page.getByRole('button', { name: /研究B/ }).first().click()
    assert.equal(await accountName().inputValue(), '留在原会话', 'session selection must guard before mutation')
    page.once('dialog', (dialog) => dialog.accept())
    await page.getByRole('button', { name: /研究B/ }).first().click()
    await page.getByRole('button', { name: /会话计划/ }).click()
    const planName = page.getByPlaceholder('例如：回调分批买入')
    await planName.fill('B 的草稿')
    assert.equal(await page.evaluate(() => {
      const event = new Event('beforeunload', { cancelable: true })
      window.dispatchEvent(event)
      return event.defaultPrevented
    }), true, 'plan draft must protect reload/tab close')
    page.once('dialog', (dialog) => dialog.dismiss())
    await page.locator('.session-plan-dialog .el-dialog__headerbtn').click()
    assert.equal(await planName.isVisible(), true, 'cancel must keep the dialog open')
    assert.equal(await planName.inputValue(), 'B 的草稿')
    page.once('dialog', (dialog) => dialog.accept())
    await page.locator('.session-plan-dialog .el-dialog__headerbtn').click()
    await page.getByRole('button', { name: /研究A/ }).first().click()
    await page.getByRole('button', { name: /会话计划/ }).click()
    assert.equal(await planName.inputValue(), '', 'another research must not inherit a draft')
    await page.locator('.session-plan-dialog .el-dialog__headerbtn').click()

    await profiles().click()
    await page.setViewportSize({ width: 375, height: 812 })
    await accountName().fill('窄屏草稿')
    page.once('dialog', (dialog) => dialog.dismiss())
    await page.getByRole('button', { name: '返回研究', exact: true }).click()
    assert.equal(await accountName().inputValue(), '窄屏草稿')
    assert.deepEqual(errors, [], 'browser must not raise uncaught errors')
    console.log('PASS: cancel/confirm navigation, guarded session switch, plan isolation, 375px draft protection')
    await context.close()
  } finally {
    if (browser) await browser.close()
    server.kill()
  }
}
main().catch((error) => { console.error(error); process.exitCode = 1 })
