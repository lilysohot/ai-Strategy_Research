const { chromium } = require('../web/node_modules/playwright')
const assert = require('node:assert/strict')
const fs = require('node:fs')

;(async () => {
  const browser = await chromium.launch({ headless: true, ...(process.platform === 'win32' ? { channel: 'msedge' } : {}) })
  const errors = []
  fs.mkdirSync('.scratch/login-entrance', { recursive: true })
  try {
    for (const variant of ['desktop', 'mobile', 'reduced']) {
      const context = await browser.newContext({
        viewport: variant === 'mobile' ? { width: 390, height: 844 } : { width: 1440, height: 960 },
        hasTouch: variant === 'mobile',
        reducedMotion: variant === 'reduced' ? 'reduce' : 'no-preference',
      })
      let loginRequests = 0
      await context.route('**/api/**', async (route) => {
        const url = route.request().url()
        if (!new URL(url).pathname.startsWith('/api/')) return route.continue()
        if (url.endsWith('/auth/registration-status')) return route.fulfill({ json: { enabled: true } })
        if (url.endsWith('/auth/login')) {
          loginRequests++
          return route.fulfill({ status: 401, json: { detail: '用户名或密码错误' } })
        }
        return route.fulfill({ json: {} })
      })
      const page = await context.newPage()
      page.on('pageerror', (err) => errors.push(err.message))
      await page.goto('http://127.0.0.1:55183/login?redirect=/models')
      const enter = page.getByTestId('enter-login')
      await enter.waitFor()
      assert.equal(await page.locator('input').count(), 0)
      await page.waitForTimeout(1100)
      assert.equal(await page.locator('input').count(), 0, 'never automatically reveal login')
      await page.screenshot({ path: `.scratch/login-entrance/${variant}-intro.png`, fullPage: true })
      if (variant === 'reduced') {
        assert.equal(await page.locator('.orbit-ring').first().evaluate(el => getComputedStyle(el).animationName), 'none')
        await page.keyboard.press('Tab')
        await page.keyboard.press('Enter')
      } else if (variant === 'mobile') await enter.tap()
      else await page.mouse.click(1000, 400)
      const username = page.getByTestId('username')
      const password = page.getByTestId('password')
      await username.waitFor()
      await page.waitForFunction(() => document.activeElement?.getAttribute('autocomplete') === 'username')
      assert.equal(await page.getByTestId('submit').isDisabled(), true)
      await page.screenshot({ path: `.scratch/login-entrance/${variant}-login.png`, fullPage: true })
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
      await username.fill('explorer')
      await password.fill('testpass123')
      await password.press('Enter')
      await page.getByText('用户名或密码错误', { exact: true }).waitFor()
      assert.equal(loginRequests, 1, 'Enter must submit once')
      assert.ok(page.url().endsWith('redirect=/models'))
      await page.getByTestId('switch').click()
      await page.getByTestId('confirm').waitFor()
      await page.getByRole('button', { name: '返回首页' }).click()
      await enter.waitFor()
      await page.waitForFunction(() => document.activeElement?.getAttribute('data-testid') === 'enter-login')
      await page.waitForTimeout(400)
      assert.equal(await page.locator('input').count(), 0)
      await enter.press('Space')
      await password.waitFor()
      assert.equal(await password.inputValue(), '')
      await context.close()
      console.log(`PASS ${variant}: intro, reveal, focus, single submit, registration, return, layout`)
    }
    assert.deepEqual(errors, [])
  } finally { await browser.close() }
})().catch(err => { console.error(err); process.exitCode = 1 })
