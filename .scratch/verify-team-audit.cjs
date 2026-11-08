// Isolated browser acceptance: real Vue component and API client, fixed HTTP responses.
const assert = require('node:assert/strict')
const path = require('node:path')
const { spawn } = require('node:child_process')
const root = path.resolve(__dirname, '../web')
const { chromium } = require(path.join(root, 'node_modules/playwright'))
const origin = 'http://127.0.0.1:55184'
const server = process.platform === 'win32'
  ? spawn('wsl.exe', ['-d', 'Ubuntu', '--cd', '/home/administrator/FrontierAgent/web', '/home/administrator/.nvm/versions/node/v24.21.0/bin/node', '/home/administrator/FrontierAgent/web/node_modules/vite/bin/vite.js', '--host', '0.0.0.0', '--port', '55184', '--strictPort'], { stdio: 'pipe', windowsHide: true })
  : spawn(process.execPath, [path.join(root, 'node_modules/vite/bin/vite.js'), '--host', '127.0.0.1', '--port', '55184', '--strictPort'], { cwd: root, stdio: 'pipe' })
let logs = ''
server.stdout.on('data', data => { logs += data })
server.stderr.on('data', data => { logs += data })
;(async () => {
  let browser
  try {
    for (let i = 0; ; i++) {
      if (server.exitCode !== null) throw new Error(logs)
      try { if ((await fetch(origin)).ok) break } catch {}
      if (i > 100) throw new Error(logs)
      await new Promise(resolve => setTimeout(resolve, 100))
    }
    browser = await chromium.launch({ headless: true, ...(process.platform === 'win32' ? { executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' } : {}) })
    const page = await browser.newPage()
    page.on('pageerror', error => console.error('PAGE', error.message))
    await page.route('**/api/runs/*/audit', async route => {
      const empty = route.request().url().includes('/empty/')
      await route.fulfill({ json: { available: !empty, audit: empty ? null : { answer_status: 'partial', verification_checks: [{ criterion: '核对费用', verdict: 'unchecked', binding_id: 'audit-binding-01' }], acquisition_limits: [{ source: 'https://source.test/fee', status: 'unavailable' }] } } })
    })
    await page.route('**/__audit_test', route => route.fulfill({ contentType: 'text/html', body: `<div id="app"></div><script type="module">import {createApp,ref,h} from '/node_modules/.vite/deps/vue.js';import Audit from '/src/components/RunAudit.vue';const app=createApp({setup(){const id=ref('sample');window.changeRun=()=>id.value='empty';return()=>h(Audit,{runId:id.value,status:'completed'})}});app.directive('loading',{});app.mount('#app');</script>` }))
    await page.goto(origin + '/__audit_test')
    await page.getByText('audit-binding-01', { exact: false }).waitFor()
    assert((await page.locator('pre').textContent()).includes('unchecked'))
    await page.screenshot({ path: path.join(__dirname, 'team-efficiency-audit.png'), fullPage: true })
    await page.locator('summary').click()
    assert.equal(await page.locator('details').getAttribute('open'), null)
    await page.evaluate(() => window.changeRun())
    await page.getByText('尚无最终核验记录。', { exact: false }).waitFor()
    assert.equal(await page.locator('pre').count(), 0)
    console.log('PASS: audit detail, collapse, run switch and unavailable state')
  } finally {
    if (browser) await browser.close()
    server.kill()
  }
})().catch(error => { console.error(error); process.exitCode = 1 })
