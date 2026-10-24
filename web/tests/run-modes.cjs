/* Isolated browser regression. Start Vite first; no live API/model calls are made.
 * WEB_TEST_ORIGIN=http://127.0.0.1:5173 PLAYWRIGHT_CHANNEL=chrome node tests/run-modes.cjs
 */
const assert = require('node:assert/strict')
const { chromium } = require('playwright')

const origin = process.env.WEB_TEST_ORIGIN || 'http://127.0.0.1:5173'
const session = { id: 'mode-research', title: '模式切换验收', created_at: null, updated_at: null }

async function main() {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) })
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
    await context.addInitScript(() => localStorage.setItem('frontier-agent.token', 'isolated-mode-test'))
    let available = false
    let rejectSubmit = true
    let disconnected = false
    let status = 'running'
    const submitted = []
    await context.route(`${origin}/api/**`, async (route) => {
      const request = route.request()
      const pathname = new URL(request.url()).pathname
      let body = {}
      if (pathname === '/api/auth/me') body = { id: 'test-user', username: 'mode-test' }
      else if (pathname === '/api/runs/modes') body = {
        single: { available: true, reason: null },
        team: { available, reason: available ? null : '团队研究暂未开放，请使用单 Agent' },
      }
      else if (pathname === '/api/runs' && request.method() === 'POST') {
        submitted.push({ type: request.headers()['content-type'], body: request.postData() })
        if (rejectSubmit) return route.fulfill({ status: 503, json: { detail: '测试：暂不可用' } })
        body = { run_id: 'mode-run', session_id: session.id, mode: 'team', status: 'queued' }
      }
      else if (pathname === '/api/runs/mode-run/events') {
        if (disconnected) return route.fulfill({ status: 401, json: { detail: '测试：流连接断开' } })
        return route.fulfill({ contentType: 'text/event-stream', body:
          'data: {"type":"run_started","pipeline_id":"agent_team"}\n\n'
          + 'data: {"type":"run_completed"}\n\n' })
      }
      else if (pathname === '/api/runs/mode-run') body = {
        run_id: 'mode-run', status, pipeline_id: 'agent_team', mode: 'team',
      }
      else if (pathname.endsWith('/controls')) body = { controls: [] }
      else if (pathname === '/api/sessions') body = { sessions: [session], has_more: false }
      else if (pathname === `/api/sessions/${session.id}`) body = session
      else if (pathname.endsWith('/turns')) body = { turns: [], has_more: false }
      else if (pathname === '/api/models') body = []
      else body = { accounts: [], plans: [], operations: [], artifacts: [], files: [],
        rules: [], events: [], requests: [], has_more: false }
      await route.fulfill({ json: body })
    })
    const page = await context.newPage()
    const errors = []
    page.on('pageerror', error => { errors.push(error.message); console.error(error.message) })
    page.on('console', message => { if (message.type() === 'error') console.error(message.text()) })
    await page.goto(origin)
    const mode = page.getByTestId('mode-select')
    const draft = page.getByPlaceholder('描述研究主题、时间范围、约束或继续追问...')
    const send = page.getByTestId('send-btn')
    await mode.waitFor()
    await page.waitForFunction(() => !document.querySelector('[data-testid="mode-select"]').disabled)
    assert.equal(await mode.inputValue(), 'single')
    await draft.fill('请继承当前研究的约束')
    await mode.selectOption('team')
    assert.equal(await send.isDisabled(), true, 'closed gate prevents team submission')
    assert.match(await page.getByTestId('mode-description').innerText(), /暂未开放/)
    await draft.press('Enter')
    assert.equal(submitted.length, 0, 'Enter must respect the gate too')
    available = true
    await page.getByRole('button', { name: '刷新状态' }).click()
    await page.waitForFunction(() => !document.querySelector('[data-testid="send-btn"]').disabled)
    await send.click()
    await page.waitForFunction(() => !document.querySelector('[data-testid="mode-select"]').disabled)
    assert.deepEqual(JSON.parse(submitted[0].body), {
      message: '请继承当前研究的约束', session_id: session.id, mode: 'team',
    })
    assert.equal(await draft.inputValue(), '请继承当前研究的约束', 'failed submit preserves text')
    await page.locator('input[type=file]').setInputFiles({ name: 'evidence.txt',
      mimeType: 'text/plain', buffer: Buffer.from('retained evidence') })
    await send.click()
    await page.waitForFunction(() => !document.querySelector('[data-testid="mode-select"]').disabled)
    assert.match(submitted[1].type, /multipart\/form-data/)
    assert.match(submitted[1].body, /name="mode"\r\n\r\nteam/)
    assert.equal(await page.locator('.file-chip').count(), 1, 'failed submit preserves attachment')
    await mode.selectOption('single')
    await send.click()
    await page.waitForFunction(() => !document.querySelector('[data-testid="mode-select"]').disabled)
    assert.match(submitted[2].body, /name="mode"\r\n\r\nsingle/)

    // Successful team turn finishes, then the same research can send a single turn.
    await page.getByRole('button', { name: '移除附件' }).click()
    await mode.selectOption('team')
    rejectSubmit = false
    status = 'completed'
    await send.click()
    await page.waitForFunction(() => !document.querySelector('[data-testid="mode-select"]').disabled)
    assert.equal(await draft.inputValue(), '', 'accepted draft clears')
    await mode.selectOption('single')
    await draft.fill('继续快速追问')
    rejectSubmit = true
    await send.click()
    await page.waitForFunction(() => !document.querySelector('[data-testid="mode-select"]').disabled)
    assert.equal(JSON.parse(submitted.at(-1).body).mode, 'single')
    assert.equal(JSON.parse(submitted.at(-1).body).session_id, session.id)

    // Restoring a team run must show the server's mode and remain locked after SSE failure.
    status = 'running'
    disconnected = true
    await page.reload()
    await page.getByTestId('composer-stop').waitFor()
    await page.waitForFunction(() => document.querySelector('[data-testid="mode-select"]')
      ?.value === 'team')
    assert.equal(await mode.isDisabled(), true)
    if (process.env.MODE_SCREENSHOT) await page.screenshot({ path: process.env.MODE_SCREENSHOT.replace('.png', '-desktop.png'), fullPage: true })
    await page.setViewportSize({ width: 390, height: 844 })
    await page.locator('.composer-toolbar').scrollIntoViewIfNeeded()
    await page.waitForFunction(() => document.querySelector('.workbench-rail').getBoundingClientRect().right <= 1)
    assert.equal(await mode.isVisible(), true)
    const box = await page.locator('.composer-toolbar').boundingBox()
    assert.ok(box && box.x >= 0 && box.x + box.width <= 391, 'mode row fits narrow viewport')
    assert.deepEqual(errors, [], 'no uncaught browser errors')
    if (process.env.MODE_SCREENSHOT) await page.screenshot({ path: process.env.MODE_SCREENSHOT, fullPage: true, animations: 'disabled' })
    console.log('PASS: closed/open gate, JSON/multipart, draft retention, team→single, restored/disconnected run lock, 390px layout')
    await context.close()
  } finally { await browser.close() }
}

main().catch(error => { console.error(error); process.exitCode = 1 })
