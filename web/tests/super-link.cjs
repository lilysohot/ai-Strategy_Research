/* Isolated Super-link browser acceptance. All API calls are intercepted. */
const assert = require('node:assert/strict')
const { chromium } = require('playwright')
const origin = process.env.WEB_TEST_ORIGIN || 'http://127.0.0.1:5187'

async function main() {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) })
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
    await context.addInitScript(() => localStorage.setItem('frontier-agent.token', 'isolated-super-link-test'))
    let enabled = true
    let failCreate = true
    let failControl = true
    let approvalPending = true
    const commands = []
    const approvals = []
    const recoveries = []
    const submissions = []
    const peers = [{ participant_id: 'team', session_id: 'ts', role: 'team' }, { participant_id: 'single', session_id: 'ss', role: 'single' }]
    const space = { space_id: 'space-a', goal: '研究最新研报中的潜在交易对象，保留证据与风险边界。', goal_version: 1, paused: false,
      control_state: 'active', control_version: 0, can_control: true,
      participants: peers, automatic_budget: { used: 2, limit: 20, remaining: 18 } }
    const approval = { control_id: 'control-a', external_id: 'worker-approval-a', run_id: 'run-team', kind: 'approval', status: 'pending', request: { tool_name: 'bash', risk: 'high', preview: 'rm /workspace/example', reason: '删除操作需要审批' } }
    const run = { run_id: 'run-team', session_id: 'ts', status: 'completed', pipeline_id: 'agent_team', created_at: '2026-11-19T10:00:00Z', finalization: { state: 'ready', error: null }, dispatch: null }
    const delivery = { message_id: 'delivery-a', phase: 'execution_queued', sender_id: 'team', recipient_id: 'single', request_id: 'delivery-a', revises_message_id: null,
      published_at: '2026-11-19T10:02:00Z', inspection: { verdict: 'caveat', explanation: '需继续验证成交量与宏观环境。', attempts: 1, limit: 3 },
      content: { body: '已有三份研报支持进一步观察。<img src=x onerror="window.injected=true">', requests_execution: true },
      source_run: run, recipient_run: null, feedback: null, revisions: [], attempts: [{ number: 1, verdict: 'caveat', explanation: '证据范围已说明。' }] }
    await context.route(`${origin}/api/**`, async route => {
      const req = route.request()
      const url = new URL(req.url())
      const p = url.pathname
      let body = {}; let status = 200
      if (p === '/api/auth/me') body = { id: 'user-a', username: 'researcher' }
      else if (p.startsWith('/api/super-link') && !enabled) { status = 404; body = { detail: 'super_link_disabled' } }
      else if (p === '/api/super-link/capabilities') body = { can_create: true, reason: null }
      else if (p === '/api/super-link/spaces' && req.method() === 'POST') {
        submissions.push(req.postDataJSON())
        if (failCreate) { status = 503; body = { detail: '临时不可用，请重试' } }
        else { status = 201; body = { space_id: 'space-a', initial_run_id: 'run-team' } }
      } else if (p === '/api/super-link/spaces') body = { items: [space], next_after: null }
      else if (p === '/api/super-link/spaces/space-a') body = space
      else if (p.endsWith('/space-a/runs')) body = { items: [run, { ...run, run_id: 'run-single', session_id: 'ss', status: 'queued' }], next_after: null }
      else if (p.endsWith('/space-a/deliveries')) body = { items: [delivery], next_after: null }
      else if (p.endsWith('/deliveries/delivery-a')) body = delivery
      else if (p.endsWith('/space-a/interventions')) body = { pending: approvalPending ? [approval] : [], recent: [{ ...approval, status: approvalPending ? 'pending' : 'adopted' }], active_runs: [{ ...run, status: 'running' }] }
      else if (p.endsWith('/space-a/recovery-actions')) body = { items: [], next_after: null }
      else if (p.endsWith('/space-a/control')) {
        const command = req.postDataJSON(); commands.push(command)
        if (failControl) { status = 503; body = { detail: '控制响应中断，请重试' } }
        else {
          space.control_state = { pause: 'paused', stop: 'stopping', resume: 'active', continue: space.control_state }[command.action]
          space.paused = space.control_state !== 'active'; space.control_version++
          body = { control_state: space.control_state, control_version: space.control_version }
        }
      }
      else if (p.endsWith('/runs/run-team/approve')) { approvals.push(req.postDataJSON()); body = { approved: true } }
      else if (p.endsWith('/runs/run-team/steer')) body = { queued: true }
      else if (p.endsWith('/space-a/recovery')) { recoveries.push(req.postDataJSON()); body = { outcome: 'scheduled' } }
      else if (p.startsWith('/api/super-link/spaces/')) { status = 404; body = { detail: 'not_found' } }
      else if (p === '/api/runs/run-team') body = { ...run, final_answer: '研究完成，等待进一步核验。' }
      else if (p.endsWith('/trace')) body = { run_id: 'run-team', records: [], completeness: { state: 'complete', sources: [] } }
      else if (p.endsWith('/artifacts')) body = { artifacts: [] }
      else if (p === '/api/sessions') body = { sessions: [], total: 0, has_more: false }
      else if (p === '/api/runs/modes') body = { single: { available: true }, team: { available: true } }
      else if (p === '/api/models') body = []
      else if (p === '/api/runs') body = { runs: [] }
      else if (p.endsWith('/presence')) body = { ok: true }
      else if (p.startsWith('/api/business')) body = { accounts: [], plans: [], settings: {}, items: [] }
      else { status = 404; body = { detail: 'mock endpoint not provided' } }
      await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    })
    const page = await context.newPage()
    const pageErrors = []
    page.on('pageerror', e => pageErrors.push(e.message))
    await page.goto(origin)
    await page.getByRole('link', { name: /Super-link/ }).click()
    await page.waitForURL('**/super-link')
    assert.equal(new URL(page.url()).pathname, '/super-link')
    assert.equal(await page.locator('.station').count(), 3, 'three visual roles use the existing two-session workflow')
    await page.waitForFunction(() => ![...document.querySelectorAll('button')].find(el => el.textContent.trim() === '新建协作')?.disabled)
    await page.screenshot({ path: require('node:path').join(require('node:os').tmpdir(), 'super-link-studio-dark.png'), fullPage: true })
    await page.evaluate(() => document.documentElement.dataset.theme = 'light')
    assert.equal(await page.locator('.studio').evaluate(el => getComputedStyle(el).getPropertyValue('--scene-bg').trim()), '#eee7d7', 'studio follows light theme')
    await page.screenshot({ path: require('node:path').join(require('node:os').tmpdir(), 'super-link-studio-light.png'), fullPage: true })
    await page.evaluate(() => document.documentElement.dataset.theme = 'dark')
    await page.getByRole('button', { name: '新建协作' }).click()
    await page.getByLabel('共同研究目标', { exact: true }).fill('检索最新研报并跟进潜在对象')
    await page.getByRole('button', { name: '创建并开始研究' }).click()
    await page.getByText('临时不可用，请重试', { exact: true }).waitFor()
    assert.equal(await page.getByLabel('共同研究目标', { exact: true }).inputValue(), '检索最新研报并跟进潜在对象')
    await page.reload()
    await page.getByRole('button', { name: '新建协作' }).click()
    assert.equal(await page.getByLabel('共同研究目标', { exact: true }).inputValue(), '检索最新研报并跟进潜在对象')
    failCreate = false
    await page.getByRole('button', { name: '创建并开始研究' }).click()
    await page.waitForURL('**/super-link/space-a')
    await page.getByRole('heading', { name: '交付链路', exact: true }).waitFor()
    assert.match(await page.locator('[data-agent="inspector"] .station-status').innerText(), /附带说明通过/)
    assert.match(await page.locator('[data-agent="single"] .station-status').innerText(), /排队中/)
    run.status = 'running'; delivery.phase = 'inspecting'
    await page.getByRole('button', { name: '刷新状态', exact: true }).click()
    await page.locator('[data-agent="team"].working').waitFor()
    await page.locator('[data-agent="inspector"].working').waitFor()
    await page.locator('.shell__main').evaluate(el => el.scrollTop = 0)
    await page.screenshot({ path: require('node:path').join(require('node:os').tmpdir(), 'super-link-studio-active.png'), fullPage: true })
    await page.emulateMedia({ reducedMotion: 'reduce' })
    assert.equal(await page.locator('[data-agent="team"] .typing-hands').evaluate(el => getComputedStyle(el).animationName), 'none')
    await page.emulateMedia({ reducedMotion: 'no-preference' })
    run.status = 'completed'; delivery.phase = 'execution_queued'
    await page.getByRole('button', { name: '刷新状态', exact: true }).click()
    assert.equal(submissions.length, 2)
    assert.deepEqual(submissions[0], submissions[1], 'lost-response retry keeps creation key')
    assert.equal(await page.getByTestId('mode-select').count(), 0, 'independent mode has no legacy mode selector')
    await page.getByRole('button', { name: /Team → Single/ }).click()
    await page.getByText('需继续验证成交量与宏观环境。', { exact: true }).waitFor()
    assert.equal(await page.evaluate(() => !!window.injected), false)
    await page.keyboard.press('Escape')
    await page.locator('.sl-run').first().click()
    await page.getByText('研究完成，等待进一步核验。', { exact: true }).waitFor()
    await page.keyboard.press('Escape')
    await page.reload()
    await page.getByRole('heading', { name: '交付链路', exact: true }).waitFor()
    const approveButton = page.getByRole('button', { name: '批准操作', exact: true })
    await page.getByTestId('sl-approval').waitFor()
    assert.equal(await approveButton.isDisabled(), true)
    await page.getByPlaceholder('输入 yes 以启用批准按钮').fill('yes')
    await approveButton.click()
    await page.getByText('已提交，等待运行确认。实际结果以审批记录为准。').waitFor()
    assert.equal(approvals[0].approval_id, 'worker-approval-a')
    assert.equal(approvals[0].decision, 'once')
    assert.equal(await page.getByTestId('sl-approval').count(), 1, 'HTTP response is not worker adoption')
    approvalPending = false
    await page.reload()
    await page.getByRole('button', { name: '暂停协作', exact: true }).click()
    await page.getByRole('textbox', { name: '操作原因', exact: true }).fill('先核验研究方向')
    await page.getByRole('button', { name: '确认操作', exact: true }).click()
    await page.getByRole('dialog').getByText('控制响应中断，请重试').waitFor()
    await page.reload()
    failControl = false
    await page.getByRole('button', { name: '重试原请求', exact: true }).click()
    await page.getByRole('heading', { name: '协作控制 · 已暂停' }).waitFor()
    assert.deepEqual(commands[0], commands[1], 'reload retains lifecycle command key and version')
    await page.getByRole('button', { name: '恢复协作', exact: true }).click()
    await page.getByRole('textbox', { name: '操作原因', exact: true }).fill('继续研究')
    await page.getByRole('button', { name: '确认操作', exact: true }).click()
    await page.getByRole('heading', { name: '协作控制 · 协作中' }).waitFor()
    await page.getByRole('button', { name: '补充任务', exact: true }).click()
    await page.getByRole('textbox', { name: '补充任务内容', exact: true }).fill('补充宏观环境分析')
    await page.getByRole('textbox', { name: '操作原因', exact: true }).fill('新增资料')
    await page.getByRole('button', { name: '确认操作', exact: true }).click()
    await page.getByText('补充任务请求已记录，请以最新运行状态为准。').waitFor()
    assert.equal(commands.at(-1).message, '补充宏观环境分析')
    await page.getByRole('button', { name: '故障恢复', exact: true }).click()
    await page.getByRole('button', { name: '增加自动跟进额度', exact: true }).click()
    await page.getByRole('textbox', { name: '操作原因', exact: true }).fill('继续验证')
    await page.getByRole('button', { name: '确认操作', exact: true }).click()
    await page.getByText('增加自动跟进额度请求已记录，请以最新运行状态为准。').waitFor()
    assert.equal(recoveries[0].additional_runs, 3)
    await page.getByRole('button', { name: '停止协作', exact: true }).click()
    await page.getByRole('textbox', { name: '操作原因', exact: true }).fill('结束本阶段研究')
    await page.getByRole('button', { name: '确认操作', exact: true }).click()
    await page.getByRole('heading', { name: '协作控制 · 正在停止' }).waitFor()
    assert.equal(await page.getByRole('button', { name: '恢复协作', exact: true }).count(), 0)
    space.control_state = 'stopped'; space.control_version++
    await page.getByRole('button', { name: '刷新状态', exact: true }).click()
    await page.getByRole('heading', { name: '协作控制 · 已停止' }).waitFor()
    assert.equal(await page.locator('.station.working').count(), 0, 'stopped agents do not appear to keep working')
    await page.screenshot({ path: require('node:path').join(require('node:os').tmpdir(), 'super-link-desktop.png'), fullPage: true })
    await page.setViewportSize({ width: 390, height: 844 })
    await page.locator('.shell__main').evaluate(el => el.scrollTop = 0)
    await page.screenshot({ path: require('node:path').join(require('node:os').tmpdir(), 'super-link-mobile.png'), fullPage: true })
    await page.locator('.studio').screenshot({ path: require('node:path').join(require('node:os').tmpdir(), 'super-link-studio-mobile.png') })
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, 'mobile has no horizontal overflow')
    await page.goto(`${origin}/super-link/not-owned`)
    await page.getByText('未找到这个协作空间，或你没有访问权限。').waitFor()
    assert.equal(await page.locator('.sl-peer').count(), 0, 'old space content is cleared')
    enabled = false
    await page.goto(`${origin}/super-link`)
    await page.getByText('Super-link 尚未启用。原有研究工作台仍可正常使用。').waitFor()
    assert.equal(await page.getByRole('button', { name: '新建协作' }).isDisabled(), true)
    assert.deepEqual(pageErrors, [])
    console.log('Super-link browser acceptance passed: independent entry, approval receipt, pause/stop/resume, durable retry, continuation, recovery, detail, sanitization, mobile and ownership states')
  } finally { await browser.close() }
}
main().catch(e => { console.error(e); process.exitCode = 1 })
