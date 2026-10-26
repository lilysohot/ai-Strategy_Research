/* Real Vue component, intercepted API; no account, worker or model calls.
 * Start Vite, then: PLAYWRIGHT_CHANNEL=chrome node tests/trace-lifecycle.cjs
 */
const assert = require('node:assert/strict')
const { chromium } = require('playwright')
const origin = process.env.WEB_TEST_ORIGIN || 'http://127.0.0.1:5173'
const snapshot = (id, complete) => ({
  run_id: id,
  records: [{ t: 'start', max_turns: 200 }, ...(complete ? [
    { t: 'llm', turn: 1, content: `${id} saved answer`, tool_calls: [] },
    { t: 'end' },
  ] : [])],
  completeness: { state: complete ? 'complete' : 'partial', valid_lines: complete ? 3 : 1,
    reason: complete ? '' : '运行未正常结束，已保存的记录可读，但可能缺少最后一部分内容' },
})

async function main() {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) })
  try {
    const page = await browser.newPage()
    const errors = []
    page.on('pageerror', err => errors.push(err.message))
    let complete = false
    let pendingOld
    let oldRequested
    const oldRequest = new Promise(resolve => { oldRequested = resolve })
    await page.route(`${origin}/api/**`, async route => {
      const id = new URL(route.request().url()).pathname.split('/')[3]
      if (id === 'trace-slow') {
        pendingOld = route
        oldRequested()
        return
      }
      await route.fulfill({ json: snapshot(id, complete) })
    })
    await page.route(`${origin}/__trace-test`, route => route.fulfill({
      contentType: 'text/html', body: '<div id="app"></div><script type="module" src="/tests/fixtures/trace-lifecycle.ts"></script>',
    }))
    await page.goto(`${origin}/__trace-test`)
    await page.getByText('运行开始', { exact: true }).waitFor()
    complete = true
    await page.evaluate(() => window.traceTest.finish())
    await page.getByText('trace-first saved answer', { exact: true }).waitFor({ timeout: 6000 })
    assert.equal(await page.getByText(/运行未正常结束/).count(), 0)

    // A slow previous run must not replace the next run's records or warning.
    await page.evaluate(() => window.traceTest.switchRun('trace-slow'))
    await oldRequest
    await page.evaluate(() => window.traceTest.switchRun('trace-current'))
    await page.getByText('trace-current saved answer', { exact: true }).waitFor()
    await pendingOld.fulfill({ json: snapshot('trace-slow', false) })
    await page.waitForTimeout(200)
    assert.equal(await page.getByText('trace-current saved answer', { exact: true }).count(), 1)
    assert.equal(await page.getByText(/运行未正常结束/).count(), 0)

    // Running snapshots refresh even without a terminal event.
    complete = false
    await page.evaluate(() => window.traceTest.switchRun('trace-live'))
    await page.getByText('运行开始', { exact: true }).waitFor()
    assert.equal(await page.getByText(/运行未正常结束/).count(), 0)
    complete = true
    await page.getByText('trace-live saved answer', { exact: true }).waitFor({ timeout: 6000 })
    assert.deepEqual(errors, [])
    console.log('PASS: terminal refresh, cross-run race, live refresh and active completeness notice')
  } finally {
    await browser.close()
  }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
