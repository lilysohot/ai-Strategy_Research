/* Browser regression: node tests/unread-replies.cjs (isolated API fixtures). */
const assert = require('node:assert/strict')
const path = require('node:path')
const { spawn } = require('node:child_process')
const { chromium } = require('playwright')

const webRoot = path.resolve(__dirname, '..')
const origin = 'http://127.0.0.1:55179'
const server = spawn(process.execPath, [path.join(webRoot, 'node_modules/vite/bin/vite.js'),
  '--host', '127.0.0.1', '--port', '55179', '--strictPort'], { cwd: webRoot, stdio: 'pipe' })
let output = ''
server.stdout.on('data', (data) => { output += data })
server.stderr.on('data', (data) => { output += data })
const sessions = ['a', 'b'].map((id) => ({
  id, title: `研究 ${id.toUpperCase()}`, created_at: null, updated_at: null,
  turn_count: 2, last_completed_turn_seq: 2,
}))
let failTurns = false
let holdTurns = false
let releaseTurns
let listReads = 0

async function main() {
  let browser
  let page
  try {
    for (let attempt = 0; ; attempt++) {
      if (server.exitCode !== null) throw new Error(output)
      try { if ((await fetch(origin)).ok) break } catch {}
      if (attempt === 120) throw new Error(`Vite did not start: ${output}`)
      await new Promise((resolve) => setTimeout(resolve, 250))
    }
    browser = await chromium.launch({ headless: true })
    const context = await browser.newContext({ viewport: { width: 1440, height: 960 } })
    await context.addInitScript(() => localStorage.setItem('frontier-agent.token', 'isolated-test'))
    await context.route(`${origin}/api/**`, async (route) => {
      const pathname = new URL(route.request().url()).pathname
      let body = {}
      if (pathname === '/api/auth/me') body = { id: 'test-user', username: 'unread-test' }
      else if (pathname === '/api/sessions') {
        listReads++
        body = { sessions, total: sessions.length, has_more: false }
      } else if (pathname.endsWith('/turns')) {
        if (failTurns) return route.fulfill({ status: 503, body: '{}' })
        const session = sessions.find((item) => pathname === `/api/sessions/${item.id}/turns`)
        const seq = session.last_completed_turn_seq
        if (holdTurns) await new Promise((resolve) => { releaseTurns = resolve })
        body = { turns: [{ seq, role: 'assistant', content: `回答 ${session.id}-${seq}`,
          run_id: null, created_at: null }], has_more: false }
      } else if (pathname.endsWith('/runs')) body = { runs: [] }
      else if (pathname.endsWith('/plans')) body = { plans: [] }
      else if (pathname.endsWith('/accounts')) body = { accounts: [] }
      else if (pathname.endsWith('/capital-plan')) body = { capital_plan: null }
      else if (pathname.endsWith('/input-requests')) body = { requests: [] }
      else if (pathname.endsWith('/operations')) body = { operations: [] }
      else if (pathname.endsWith('/events')) body = { events: [] }
      else if (pathname.startsWith('/api/business/monitor/sessions/')) body = { events: [], rules: [] }
      else if (pathname === '/api/models') body = []
      else body = sessions.find((item) => pathname === `/api/sessions/${item.id}`) || {}
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
    })
    page = await context.newPage()
    page.setDefaultTimeout(15000)
    const errors = []
    page.on('pageerror', (err) => { errors.push(err.message); console.error(err.message) })
    const item = (id) => page.getByTestId('session-item').filter({ hasText: `研究 ${id}` })
    const badge = (id) => item(id).getByTestId('session-unread')
    const waitForPoll = async () => {
      const previous = listReads
      await assertEventually(() => listReads > previous)
    }
    await page.goto(origin)
    console.log('Loaded workbench')
    await page.getByTestId('messages').getByText('回答 a-2', { exact: true }).waitFor()
    assert.equal(await page.getByTestId('session-unread').count(), 0, 'old history starts read')

    sessions[1].turn_count = 3 // Sending a user message must not notify.
    await waitForPoll()
    assert.equal(await badge('B').count(), 0)
    sessions[1].turn_count = 4
    sessions[1].last_completed_turn_seq = 4
    await badge('B').waitFor({ timeout: 15000 })
    assert.equal(await page.getByTestId('unread-count').innerText(), '1 个未读')
    if (process.env.UNREAD_SCREENSHOT) await page.screenshot({ path: process.env.UNREAD_SCREENSHOT })

    await page.reload()
    await badge('B').waitFor()
    await page.getByTestId('messages').getByText('回答 a-2', { exact: true }).waitFor()
    failTurns = true
    await item('B').click()
    await page.getByRole('alert').first().waitFor()
    assert.equal(await badge('B').count(), 1, 'failed history load must preserve unread')
    failTurns = false
    await item('B').click()
    await page.getByTestId('messages').getByText('回答 b-4', { exact: true }).waitFor()
    await badge('B').waitFor({ state: 'detached' })

    sessions[1].last_completed_turn_seq = 6
    await page.getByTestId('messages').getByText('回答 b-6', { exact: true }).waitFor({ timeout: 15000 })
    await badge('B').waitFor({ state: 'detached' })

    await page.getByRole('button', { name: /交易账户资料/ }).click()
    sessions[1].last_completed_turn_seq = 8
    await badge('B').waitFor({ timeout: 15000 })
    assert.equal(await badge('B').count(), 1, 'business page is not reading the selected chat')
    await item('B').click()
    await page.getByTestId('messages').getByText('回答 b-8', { exact: true }).waitFor()
    await badge('B').waitFor({ state: 'detached' })

    // A tab hidden at completion must retain unread until the answer is displayed.
    await page.evaluate(() => {
      Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' })
      document.dispatchEvent(new Event('visibilitychange'))
    })
    sessions[1].last_completed_turn_seq = 10
    await badge('B').waitFor({ timeout: 15000 })
    await page.evaluate(() => {
      Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
      document.dispatchEvent(new Event('visibilitychange'))
    })
    await page.getByTestId('messages').getByText('回答 b-10', { exact: true }).waitFor()
    await badge('B').waitFor({ state: 'detached' })

    // Switching while a history request is in flight cannot acknowledge the old chat.
    await item('A').click()
    sessions[1].last_completed_turn_seq = 12
    await badge('B').waitFor({ timeout: 15000 })
    holdTurns = true
    await item('B').click()
    await assertEventually(() => Boolean(releaseTurns))
    holdTurns = false
    await item('A').click()
    releaseTurns()
    await page.getByTestId('messages').getByText('回答 a-2', { exact: true }).waitFor()
    assert.equal(await badge('B').count(), 1)
    await page.reload()
    await badge('B').waitFor()
    assert.deepEqual(errors, [])
    console.log('PASS: background completion, refresh persistence, failed load, visible/hidden chat, business page, switching race')
  } catch (err) {
    if (page) {
      console.error(await page.locator('body').innerText())
      await page.screenshot({ path: path.join(require('node:os').tmpdir(), 'frontier-unread-failure.png') })
    }
    throw err
  } finally {
    if (browser) await browser.close()
    server.kill()
  }
}

async function assertEventually(predicate) {
  const deadline = Date.now() + 15000
  while (!predicate()) {
    if (Date.now() > deadline) throw new Error('condition did not become true')
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
}

main().catch((err) => { console.error(err); process.exitCode = 1 })
