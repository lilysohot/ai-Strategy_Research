import assert from 'node:assert/strict'
import test from 'node:test'

import { resolveStoredTheme } from '../theme.ts'

test('theme defaults to the existing dark appearance', () => {
  assert.equal(resolveStoredTheme(null), 'dark')
  assert.equal(resolveStoredTheme('unexpected'), 'dark')
})

test('theme restores an explicitly selected light appearance', () => {
  assert.equal(resolveStoredTheme('light'), 'light')
})
