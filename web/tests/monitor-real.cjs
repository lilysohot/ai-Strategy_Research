/* Browser acceptance against an isolated real API/database. No model calls. */
const assert = require('node:assert/strict')
const path = require('node:path')
const { spawn } = require('node:child_process')
const { chromium } = require('playwright')

const apiOrigin = process.env.MONITOR_TEST_API || 'http://127.0.0.1:58082'
const origin = 'http://127.0.0.1:55175'
const root = path.resolve(__dirname, '..')
const server = spawn(process.execPath, [path.join(root, 'node_modules/vite/bin/vite.js'), '--host', '127.0.0.1', '--port', '55175', '--strictPort'],
  { cwd: root, env: { ...process.env, VITE_API_PROXY: apiOrigin }, stdio: 'pipe' })
let output = ''
server.stdout.on('data', data => { output += data })
server.stderr.on('data', data => { output += data })
let token
async function api(url, method = 'GET', body) {
  const response = await fetch(apiOrigin + url, { method, headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() }, body: body ? JSON.stringify(body) : undefined })
  const result = await response.json()
  assert.ok(response.ok, `${method} ${url}: ${response.status} ${JSON.stringify(result)}`)
  return result
}

async function main() {
  let browser
  try {
    const credentials = { username: `monitor_${Date.now()}`, password: 'Monitor_Test_Strong_1' }
    await api('/api/auth/register', 'POST', credentials)
    token = (await api('/api/auth/login', 'POST', credentials)).access_token
    const first = await api('/api/sessions', 'POST', { title: '监控浏览器验收', first_message: null })
    const second = await api('/api/sessions', 'POST', { title: '另一监控会话', first_message: null })
    for (let n = 0; ; n++) {
      try { if ((await fetch(origin)).ok) break } catch {}
      if (n > 100) throw new Error(output)
      await new Promise(resolve => setTimeout(resolve, 100))
    }
    browser = await chromium.launch({ headless: true })
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
    await context.addInitScript(value => localStorage.setItem('frontier-agent.token', value), token)
    const page = await context.newPage()
    const errors = []
    page.on('pageerror', e => errors.push(e.message))
    await page.goto(origin)
    await page.getByRole('button', { name: /监控浏览器验收/ }).first().click()
    await page.getByRole('button', { name: '设置监控', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '当前会话的价格监控' })
    await dialog.getByRole('button', { name: '添加价格监控', exact: true }).click()
    await dialog.getByPlaceholder('例如 601138.SH').fill('601138.SH')
    await dialog.locator('.el-form-item').filter({ hasText: '触发价格' }).locator('input').fill('50.66')
    const expires = new Date(Date.now() + 86400000)
    const stamp = `${expires.getFullYear()}-${String(expires.getMonth()+1).padStart(2,'0')}-${String(expires.getDate()).padStart(2,'0')} 15:00:00`
    await dialog.getByPlaceholder('选择日期和时间').fill(stamp)
    await dialog.getByPlaceholder('选择日期和时间').press('Tab')
    await dialog.getByRole('button', { name: '保存监控', exact: true }).click()
    await dialog.getByRole('button', { name: '暂停', exact: true }).waitFor()
    let state = await api(`/api/business/monitor/sessions/${first.id}`)
    assert.equal(state.rules.length, 1)
    assert.equal(state.rules[0].threshold, '50.66')
    assert.ok(state.online)
    assert.equal(state.rules[0].version, 1)
    await dialog.getByRole('button', { name: '暂停', exact: true }).click()
    await dialog.getByRole('button', { name: '恢复', exact: true }).waitFor()
    state = await api(`/api/business/monitor/sessions/${first.id}`)
    assert.equal(state.rules[0].status, 'paused')
    await dialog.getByRole('button', { name: '恢复', exact: true }).click()
    await dialog.getByRole('button', { name: '暂停', exact: true }).waitFor()
    await dialog.getByRole('button', { name: '编辑 / 重新设置', exact: true }).click()
    await dialog.locator('.el-form-item').filter({ hasText: '触发价格' }).locator('input').fill('51.23')
    await dialog.getByRole('button', { name: '保存监控', exact: true }).click()
    await dialog.getByText(/51.23 CNY/).waitFor()
    state = await api(`/api/business/monitor/sessions/${first.id}`)
    assert.equal(state.rules[0].threshold, '51.23')
    await page.screenshot({ path: path.join(root, '..', '.scratch/monitoring-v1/monitor-dialog.png'), fullPage: true })
    await dialog.locator('.el-dialog__headerbtn').click()
    await page.getByRole('button', { name: /另一监控会话/ }).first().click()
    await page.getByRole('button', { name: '设置监控', exact: true }).waitFor()
    assert.equal((await api(`/api/business/monitor/sessions/${second.id}`)).rules.length, 0)
    await page.getByRole('button', { name: /监控浏览器验收/ }).first().click()
    await page.getByRole('button', { name: '查看监控', exact: true }).click()
    await dialog.getByRole('button', { name: '取消监控', exact: true }).click()
    await page.locator('.el-message-box__btns button').last().click()
    await dialog.getByRole('button', { name: '添加价格监控', exact: true }).waitFor()
    assert.equal((await api(`/api/business/monitor/sessions/${first.id}`)).rules.length, 0)
    assert.deepEqual(errors, [])
    console.log('PASS real API: create, save, pause, resume, edit, session isolation, cancel, heartbeat; zero page errors')
  } finally {
    if (browser) await browser.close()
    server.kill('SIGTERM')
  }
}
main().catch(e => { console.error(e); process.exitCode = 1 })
