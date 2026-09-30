// F05 contract checks: historical trajectory view (visible reasoning + complete
// tool results). Executes the real web/src/utils/traceView.ts — no browser, no
// network, no model calls, no production data.
//
// Separate from frontend-audit.mjs on purpose: that file is the frozen F09/F10/
// F11 baseline and its result count is compared across runs.
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
const dir = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(dir, '../../..');
const req = createRequire(path.join(root, 'web/package.json'));
const ts = req('typescript');
const results = [];
async function check(name, fn) {
  try { await fn(); results.push({ test: name, outcome: 'passed' }); }
  catch (e) { results.push({ test: name, outcome: 'failed', evidence: e.message }); }
}
const source = ts.transpileModule(
  fs.readFileSync(path.join(root, 'web/src/utils/traceView.ts'), 'utf8'),
  { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } },
).outputText;
const module = { exports: {} };
vm.runInNewContext('(function(require,module,exports){' + source + '\n})',
  { Math, Array, Object, JSON, Number, String })(
  () => { throw Error('traceView.ts must stay dependency-free so it is auditable'); },
  module, module.exports);
const tv = module.exports;

// — reasoning: shown when prose, named when not, never invented ——————————
await check('F05_visible_thinking_is_returned_verbatim', () => {
  const v = tv.thinkingView({ thinking: '先核对口径，再计算增长率' });
  assert.equal(v.state, 'visible');
  assert.equal(v.text, '先核对口径，再计算增长率');
});
await check('F05_absent_thinking_is_stated_not_invented', () => {
  const v = tv.thinkingView({ content: 'answer only' });
  assert.equal(v.state, 'absent');
  assert.equal(v.text, undefined);
  assert.ok(tv.thinkingLabel(v).length > 0, 'absent reasoning needs a visible note');
});
await check('F05_empty_thinking_is_not_rendered_as_reasoning', () => {
  const v = tv.thinkingView({ thinking: '' });
  assert.equal(v.state, 'empty');
  assert.equal(v.text, undefined);
  assert.ok(tv.thinkingLabel(v).length > 0);
});
await check('F05_encrypted_blocks_are_never_shown_as_prose', () => {
  // The observer keeps signature/encrypted_content blocks for protocol replay.
  // Rendering them as "the model's reasoning" would be showing a blob.
  const v = tv.thinkingView({
    thinking_blocks: [{ type: 'thinking', signature: 'ErUBCkYICxgCIkDf...' }],
  });
  assert.equal(v.state, 'restricted');
  assert.equal(v.text, undefined);
  assert.ok(/加密|受限|签名/.test(tv.thinkingLabel(v)));
});
await check('F05_non_text_thinking_is_restricted', () => {
  const v = tv.thinkingView({ thinking: { type: 'reasoning', encrypted_content: 'abc' } });
  assert.equal(v.state, 'restricted');
  assert.equal(v.text, undefined);
});

// — tool results: the tail stays reachable and slicing is code-point safe ————
await check('F05_error_past_the_preview_stays_reachable', () => {
  const text = 'x'.repeat(400) + 'FATAL: disk full';
  const first = tv.resultView(text, tv.initialResultChars());
  assert.equal(first.hasMore, true);
  assert.ok(!first.visible.includes('FATAL'), 'preview alone cannot show it');
  const more = tv.resultView(text, tv.nextResultChars(tv.initialResultChars()));
  assert.ok(more.visible.includes('FATAL'), 'read-more must reach the tail');
});
await check('F05_hidden_count_and_total_are_reported', () => {
  const v = tv.resultView('y'.repeat(1000), 300);
  assert.equal(v.total, 1000);
  assert.equal(v.hidden, 700);
  assert.equal(v.hasMore, true);
});
await check('F05_short_result_has_no_read_more', () => {
  const v = tv.resultView('ok', 300);
  assert.equal(v.hasMore, false);
  assert.equal(v.hidden, 0);
  assert.equal(v.visible, 'ok');
});
await check('F05_slice_never_splits_a_code_point', () => {
  const text = 'a'.repeat(299) + '\u{1F600}';
  const v = tv.resultView(text, 300);
  assert.equal(Array.from(v.visible).length, 300);
  assert.ok(v.visible.endsWith('\u{1F600}'), 'surrogate pair must stay intact');
});
await check('F05_read_more_grows_monotonically', () => {
  let shown = tv.initialResultChars();
  const first = shown;
  shown = tv.nextResultChars(shown);
  assert.ok(shown > first);
  shown = tv.nextResultChars(shown);
  assert.ok(shown > tv.RESULT_PAGE_CHARS + first);
});

fs.writeFileSync(path.join(dir, 'frontend-f05-results.json'),
  JSON.stringify({ mode: 'actual source; no browser; synthetic records', records: results }, null, 2));
for (const r of results) console.log(r.outcome + ' ' + r.test + (r.evidence ? ' ' + r.evidence.replaceAll('\n', ' ') : ''));
process.exitCode = results.some(r => r.outcome === 'failed') ? 1 : 0;
