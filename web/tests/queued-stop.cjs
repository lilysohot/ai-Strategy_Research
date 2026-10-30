/* Real stream store + composer; stalled SSE, authoritative HTTP stop/status. */
const assert = require('node:assert/strict')
const { chromium } = require('playwright')
const origin = process.env.WEB_TEST_ORIGIN || 'http://127.0.0.1:5173'

async function main() {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) })
  try {
    const page = await browser.newPage()
    const errors = []
    page.on('pageerror', err => errors.push(err.message))
    const statuses = new Map()
    let stopStatus = 200
    let oldSummary
    let summaryRequested
    const oldRead = new Promise(resolve => { summaryRequested = resolve })
    await page.route(`${origin}/api/**`, async route => {
      const path = new URL(route.request().url()).pathname
      const id = path.split('/')[3]
      if (path.endsWith('/events')) return // SSE never delivers a terminal frame.
      if (path.endsWith('/controls')) return route.fulfill({ json: { controls: [] } })
      if (path.endsWith('/control')) {
        if (stopStatus !== 503) statuses.set(id, 'stopped')
        return route.fulfill({ status: stopStatus, json: stopStatus === 200
          ? { stopped: true } : { detail: 'stop unavailable' } })
      }
      if (id === 'slow-old') { oldSummary = route; summaryRequested(); return }
      return route.fulfill({ json: { run_id: id, status: statuses.get(id) || 'queued' } })
    })
    await page.route(`${origin}/__queued-stop-test`, route => route.fulfill({
      contentType: 'text/html',
      body: '<div id="app"></div><script type="module" src="/tests/fixtures/queued-stop.ts"></script>',
    }))
    await page.goto(`${origin}/__queued-stop-test`)
    await page.getByRole('button', { name: '停止', exact: true }).click()
    await page.getByRole('button', { name: '发送', exact: true }).waitFor({ timeout: 2000 })
    assert.equal(await page.locator('#status').innerText(), 'stopped')

    // Compatibility: an old server's 409 still reconciles an already-ended run.
    stopStatus = 409
    await page.evaluate(() => window.queuedStopTest.watch('already-done'))
    await page.getByRole('button', { name: '停止', exact: true }).click()
    await page.getByRole('button', { name: '发送', exact: true }).waitFor({ timeout: 2000 })

    // A failed stop must remain visible and must not pretend the run ended.
    stopStatus = 503
    await page.evaluate(() => window.queuedStopTest.watch('still-queued'))
    await page.getByRole('button', { name: '停止', exact: true }).click()
    await page.waitForFunction(() => document.querySelector('#error').textContent.includes('stop unavailable'))
    assert.equal(await page.locator('#status').innerText(), 'queued')

    // A terminal DB status recovers a silent stream without pressing stop.
    statuses.set('still-queued', 'completed')
    await page.getByRole('button', { name: '发送', exact: true }).waitFor({ timeout: 6000 })
    assert.equal(await page.locator('#status').innerText(), 'completed')

    // The old stop/status request may finish after the user switches research.
    stopStatus = 200
    await page.evaluate(() => {
      window.queuedStopTest.watch('slow-old')
      void window.queuedStopTest.stop()
    })
    await oldRead
    await page.evaluate(() => window.queuedStopTest.watch('current'))
    await oldSummary.fulfill({ json: { status: 'stopped' } })
    await page.waitForTimeout(100)
    assert.equal(await page.locator('#status').innerText(), 'queued')
    assert.equal(await page.evaluate(() => window.queuedStopTest.isStreaming), true)
    assert.deepEqual(errors, [])
    console.log('PASS: queued stop, 409 reconciliation, failed stop, silent SSE and cross-run races')
  } finally { await browser.close() }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
