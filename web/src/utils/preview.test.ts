import assert from 'node:assert/strict'
import { test } from 'node:test'

import { previewRenderMode } from './preview.ts'

test('image kind renders as image regardless of extension', () => {
  assert.equal(previewRenderMode('chart.png', 'image'), 'image')
  assert.equal(previewRenderMode('weird.xyz', 'image'), 'image')
})

test('markdown text renders via markdown', () => {
  assert.equal(previewRenderMode('report.md', 'text'), 'markdown')
  assert.equal(previewRenderMode('notes.markdown', 'text'), 'markdown')
})

test('non-markdown text renders as code', () => {
  assert.equal(previewRenderMode('main.py', 'text'), 'code')
  assert.equal(previewRenderMode('data.csv', 'text'), 'code')
  assert.equal(previewRenderMode('Makefile', 'text'), 'code')
})

test('binary, unsupported and unknown kinds render as download', () => {
  assert.equal(previewRenderMode('pack.zip', 'binary'), 'download')
  assert.equal(previewRenderMode('thing.swx', 'unsupported'), 'download')
  assert.equal(previewRenderMode('mystery', 'something-else'), 'download')
})
