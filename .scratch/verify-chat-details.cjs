// Throwaway browser acceptance for the conversation disclosure change.
const assert = require('node:assert/strict')
const path = require('node:path')
const { spawn } = require('node:child_process')
const root = path.resolve(__dirname, '../web')
const { chromium } = require(path.join(root, 'node_modules/playwright'))
const origin = 'http://127.0.0.1:55183'
const server = spawn(process.execPath, [path.join(root, 'node_modules/vite/bin/vite.js'),
  '--host', '127.0.0.1', '--port', '55183', '--strictPort'], { cwd: root, stdio: 'pipe' })
let logs = ''
server.stdout.on('data', data => { logs += data })
server.stderr.on('data', data => { logs += data })
const session = { id: 'disclosure-test', title: '回答展示验收', created_at: null, updated_at: null }
const answer = `**部分完成：以下结论仅基于已取得的证据，尚有任务或证据缺口。**

## 研究结论

本次研究正文保持可见。

### 核验范围

以下结论仅针对列明版本与检查项，不代表整份报告或其他版本已通过核验：

- 版本检查明细，保留完整内容。
  - 未解决问题：证据仍待补充。

#### 检查子项

子项明细也需要收起。

### 内容读取边界

以下工具尝试未取得完整内容；是否影响具体结论须按证据判断。

- read_file: example.pdf (incomplete)

### 后续建议

后续正文仍然可见。`

async function main() {
  let browser
  try {
    for (let i = 0; ; i++) {
      if (server.exitCode !== null) throw new Error(logs)
      try { if ((await fetch(origin)).ok) break } catch {}
      if (i > 120) throw new Error(logs)
      await new Promise(resolve => setTimeout(resolve, 100))
    }
    browser = await chromium.launch({ headless: true })
    const context = await browser.newContext({ viewport: { width: 1440, height: 960 } })
    await context.addInitScript(() => localStorage.setItem('frontier-agent.token', 'isolated-test'))
    await context.route(`${origin}/api/**`, async route => {
      const pathname = new URL(route.request().url()).pathname
      let body = {}
      if (pathname === '/api/auth/me') body = { id: 'test-user', username: 'disclosure-test' }
      else if (pathname === '/api/sessions') body = { sessions: [session], total: 1, has_more: false }
      else if (pathname.endsWith('/turns')) body = { turns: [
        { seq: 1, role: 'user', content: '请展示研究结果', run_id: null, created_at: null },
        { seq: 2, role: 'assistant', content: answer, run_id: null, created_at: null },
      ], has_more: false }
      else if (pathname.endsWith('/runs')) body = { runs: [] }
      else if (pathname.endsWith('/plans')) body = { plans: [] }
      else if (pathname.endsWith('/accounts')) body = { accounts: [] }
      else if (pathname.endsWith('/capital-plan')) body = { capital_plan: null }
      else if (pathname.endsWith('/input-requests')) body = { requests: [] }
      else if (pathname.endsWith('/operations')) body = { operations: [] }
      else if (pathname.endsWith('/events')) body = { events: [] }
      else if (pathname.startsWith('/api/business/monitor/sessions/')) body = { events: [], rules: [] }
      else if (pathname === '/api/models') body = []
      else if (pathname === `/api/sessions/${session.id}`) body = session
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
    })
    const page = await context.newPage()
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    await page.goto(origin)
    const message = page.locator('.turn-card.assistant .turn-body')
    await message.locator('.report-details').first().waitFor()
    assert.equal(await message.locator('details').count(), 2)
    assert.equal(await message.locator('details[open]').count(), 0)
    assert.equal(await message.getByText('本次研究正文保持可见。').isVisible(), true)
    assert.equal(await message.getByText('后续正文仍然可见。').isVisible(), true)
    assert.equal(await message.getByText('子项明细也需要收起。').isVisible(), false)
    const limit = message.getByText('以下工具尝试未取得完整内容', { exact: false })
    assert.equal(await limit.isVisible(), false)
    await page.screenshot({ path: path.join(__dirname, 'chat-details-collapsed.png') })
    await message.locator('summary').filter({ hasText: '内容读取边界' }).click()
    assert.equal(await limit.isVisible(), true)
    await page.keyboard.press('Enter')
    assert.equal(await limit.isVisible(), false)
    await message.locator('summary').filter({ hasText: '核验范围' }).click()
    assert.equal(await message.getByText('子项明细也需要收起。').isVisible(), true)
    await page.reload()
    await message.locator('.report-details').first().waitFor()
    assert.equal(await message.locator('details[open]').count(), 0)
    await page.setViewportSize({ width: 592, height: 885 })
    await page.screenshot({ path: path.join(__dirname, 'chat-details-mobile.png') })
    const rendered = await page.evaluate(async () => {
      const { renderMarkdown, renderChatMarkdown } = await import('/src/utils/markdown.ts')
      const src = '### Verification scope\n\nDetails\n\n### Content access limits\n\nUnread\n\n## Conclusion\n\nVisible'
      const container = document.createElement('div')
      container.innerHTML = renderChatMarkdown(src)
      const literal = '> ### 核验范围\n> Quoted\n\n```markdown\n### 内容读取边界\n```'
      return {
        englishDetails: container.querySelectorAll('details').length,
        conclusionOutside: !!container.querySelector(':scope > h2'),
        previewUnchanged: !renderMarkdown(src).includes('<details'),
        examplesUnchanged: !renderChatMarkdown(literal).includes('<details'),
        unsafe: renderChatMarkdown('### 内容读取边界\n\n<script>alert(1)</script>\n\n[x](javascript:alert(1))'),
      }
    })
    assert.equal(rendered.englishDetails, 2)
    assert.equal(rendered.conclusionOutside, true)
    assert.equal(rendered.previewUnchanged, true)
    assert.equal(rendered.examplesUnchanged, true)
    assert.ok(!rendered.unsafe.includes('<script>'))
    assert.ok(!rendered.unsafe.includes('href="javascript:'))
    assert.deepEqual(errors, [])
    console.log('PASS: saved answers collapse both appendices; click/keyboard expand, reload, mobile, section boundaries, quoted/code examples, previews, and HTML safety verified.')
  } finally {
    if (browser) await browser.close()
    server.kill('SIGTERM')
  }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
