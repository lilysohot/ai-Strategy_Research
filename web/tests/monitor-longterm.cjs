/* Component/browser contract with isolated HTTP fixtures; never calls the live API. */
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { spawn } = require('node:child_process')
const { chromium } = require('playwright')

const root = path.resolve(__dirname, '..')
const entry = path.join(root, '.monitor-longterm-acceptance.html')
const origin = 'http://127.0.0.1:55176'
fs.writeFileSync(entry, `<html lang="zh-CN"><meta charset="UTF-8"><div id="app"></div><script type="module">
import {createApp,h} from 'vue';
import ElementPlus from 'element-plus';
import 'element-plus/dist/index.css';
import SessionMonitor from '/src/components/business/SessionMonitor.vue';
createApp({render:()=>h(SessionMonitor,{researchId:'research-test'})}).use(ElementPlus).mount('#app');
</script></html>`, { flag: 'wx' })
const server = spawn(process.execPath, [path.join(root, 'node_modules/vite/bin/vite.js'), '--host', '127.0.0.1', '--port', '55176', '--strictPort'], { cwd: root, stdio: 'pipe' })
let logs = ''
server.stdout.on('data', b => { logs += b })
server.stderr.on('data', b => { logs += b })

async function main() {
  let browser
  const state = { rules: [], events: [], event_total: 0, session_limit: 3, auto_manage: false,
    queued_signals: 2, oldest_queued_at_ms: Date.now(), online: true, enabled: true,
    source_verified: true, poll_seconds: 900,
    workers: ['collector', 'delivery', 'scheduler'].map(role => ({ role, healthy: true })) }
  const requests = []
  const updates = []
  try {
    for (let i = 0; i < 80; i++) {
      try { if ((await fetch(origin)).ok) break } catch {}
      await new Promise(resolve => setTimeout(resolve, 100))
    }
    browser = await chromium.launch({ headless: true })
    const page = await browser.newPage({ viewport: { width: 1100, height: 1000 } })
    const errors = []
    page.on('pageerror', error => { errors.push(String(error)); console.error('Browser:', error.message) })
    await page.route('**/api/**', async route => {
      const req = route.request(), url = new URL(req.url())
      if (!url.pathname.startsWith('/api/')) return route.continue()
      let result = {}
      if (url.pathname.endsWith('/settings')) {
        state.auto_manage = req.postDataJSON().auto_manage
        result = { auto_manage: state.auto_manage }
      } else if (url.pathname.endsWith('/watch-rules') && req.method() === 'POST') {
        const body = req.postDataJSON()
        requests.push(body)
        state.rules.push({ ...body.spec, id: `rule-${state.rules.length}`, name: body.name,
          version: 1, status: 'active', armed: true })
        result = { rule_id: state.rules.at(-1).id, version: 1 }
      } else if (url.pathname.includes('/watch-rules/') && req.method() === 'PATCH') {
        const body = req.postDataJSON()
        updates.push(body)
        result = { rule_id: 'rule-1', version: 2 }
      } else if (url.pathname.endsWith('/research-test')) result = state
      else throw new Error(`Unexpected API call: ${url.pathname}`)
      await route.fulfill({ json: result })
    })
    await page.goto(`${origin}/.monitor-longterm-acceptance.html`)
    await page.getByRole('button', { name: '设置监控', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '当前会话的价格监控' })
    await dialog.locator('.el-switch').click()
    await page.waitForFunction(() => document.querySelector('[role=switch]')?.getAttribute('aria-checked') === 'true')
    for (const [i, threshold] of ['20', '21', '22'].entries()) {
      await dialog.getByRole('button', { name: '添加价格监控', exact: true }).click()
      await dialog.getByPlaceholder('例如 601138.SH').fill('601138.SH')
      await dialog.locator('input[inputmode=decimal]').first().fill(threshold)
      if (i === 1) {
        await dialog.locator('.el-select').first().click()
        await page.getByRole('option', { name: '穿越时触发', exact: true }).click()
      }
      await dialog.getByText('在当前会话自动分析', { exact: true }).click()
      await dialog.locator('textarea').fill('核验价格，结合已有持仓和行情复核全部目标。')
      await dialog.getByRole('button', { name: '保存监控', exact: true }).click()
      await page.waitForFunction(count => document.querySelectorAll('.monitor-rule').length === count, i + 1)
    }
    assert.equal(await dialog.getByRole('button', { name: '添加价格监控', exact: true }).count(), 0)
    assert.equal(requests.length, 3)
    for (const [i, { spec }] of requests.entries()) {
      assert.equal(spec.trigger_mode, i === 1 ? 'crossing' : 'continuous')
      assert.equal(spec.expires_at, null)
      assert.equal(spec.on_create_already_met, 'trigger_now')
      assert.deepEqual(spec.budget, {})
    }
    assert.match(await dialog.locator('.monitor-rule').nth(0).innerText(), /大于等于.*每轮达标触发/)
    assert.match(await dialog.locator('.monitor-rule').nth(1).innerText(), /上穿.*穿越时触发/)
    await dialog.locator('.monitor-rule').nth(1).getByRole('button', { name: '编辑 / 重新设置' }).click()
    await dialog.getByRole('button', { name: '保存监控', exact: true }).click()
    await page.waitForFunction(() => !document.querySelector('.el-form'))
    assert.equal(updates.length, 1)
    assert.equal(updates[0].trigger_mode, 'crossing')
    assert.equal(state.auto_manage, true)
    assert.equal(errors.length, 0, errors.join('\n'))
    await page.screenshot({ path: path.join(root, '../tmp/monitor-longterm.png'), fullPage: true })
    console.log('Browser acceptance passed: three targets, no expiry/account requirement, actual settings writes, single-signal queue UI.')
  } finally {
    await browser?.close()
    server.kill('SIGTERM')
    fs.unlinkSync(entry)
  }
}
main().catch(error => { console.error(error, logs); process.exitCode = 1 })
