// Session-switch / live-stream re-attach audit.
//
// Executes the repository's ACTUAL TypeScript (`web/src/stores/runs.ts` and
// `web/src/utils/chat.ts`) with reactive + HTTP/stream doubles: no browser,
// network, model calls or production data.
//
// Scope: after a run is submitted from research A, switching to research B and
// back to A must not leave A's thread empty. The assistant turn is only written
// when the run ends (server/orchestrator.py), so a dropped stream cannot be
// rebuilt from the turns API while the run is still in flight.
//
// Not covered here: the ChatView wiring (an SFC cannot be executed by this
// harness) and real-browser behaviour. See README.md for the verification
// boundary.
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';

const dir = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(dir, '../../..');
const req = createRequire(path.join(root, 'web/package.json'));
const ts = req('typescript');
const results = [];
async function check(name, fn) {
  try { await fn(); results.push({test: name, outcome: 'passed'}); }
  catch (e) { results.push({test: name, outcome: 'failed', evidence: e.message}); }
}

// Browser localStorage double: the remembered newest run per research is what a
// switch-back resumes from.
const localStorage = (() => {
  const backing = new Map();
  return {
    getItem: k => backing.has(k) ? backing.get(k) : null,
    setItem: (k, v) => { backing.set(k, String(v)); },
    removeItem: k => { backing.delete(k); },
  };
})();

function storeHarness() {
  let callbacks;
  let getSummary = async () => ({status: 'completed'});
  const cache = new Map();
  function load(file) {
    file = path.resolve(file);
    if (!path.extname(file)) file = fs.existsSync(file + '.ts') ? file + '.ts' : path.join(file, 'index.ts');
    if (cache.has(file)) return cache.get(file).exports;
    const module = {exports: {}};
    cache.set(file, module);
    const source = ts.transpileModule(fs.readFileSync(file, 'utf8'),
      {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022}}).outputText;
    function localRequire(spec) {
      if (spec === 'pinia') return {defineStore: (_, setup) => setup};
      if (spec === 'vue') return {ref: value => ({value}), computed: fn => ({get value() { return fn(); }})};
      if (spec === './auth') return {useAuthStore: () => ({token: 'synthetic-token'})};
      if (spec === '../api') return {runs: {eventsUrl: id => '/runs/' + id, get: id => getSummary(id),
        controls: () => Promise.resolve({controls: []})}};
      if (spec === '../sse') return {openRunStream: opts => { callbacks = opts; return {stop() {}}; }};
      if (spec.startsWith('.')) return load(path.resolve(path.dirname(file), spec));
      throw Error('Unexpected dependency ' + spec);
    }
    vm.runInNewContext('(function(require,module,exports){' + source + '\n})',
      {console, Date, Set, Map, Promise, localStorage})(localRequire, module, module.exports);
    return module.exports;
  }
  const store = load(path.join(root, 'web/src/stores/runs.ts')).useRunStreamStore();
  const chat = load(path.join(root, 'web/src/utils/chat.ts'));
  return {store, chat, setGet: fn => { getSummary = fn; }};
}

const tick = () => new Promise(resolve => setImmediate(resolve));

// The rule ChatView applies on every selection (the actual fix): a stream bound
// to the research being re-opened survives, a stream bound elsewhere is dropped.
await check('switch_drops_only_a_foreign_stream', async () => {
  const h = storeHarness();
  h.store.rememberRun('A', 'run-a');
  h.setGet(() => Promise.resolve({status: 'running'}));
  await h.store.resumeForSession('A', () => true);
  await tick();
  assert.equal(h.store.runId.value, 'run-a');
  // A -> B: the stream belongs to a research the user has left.
  assert.equal(h.chat.streamBelongsToSession(h.store.sessionId.value, 'B'), false);
  // B -> A: the same stream belongs to the research coming back on screen, so it
  // must survive; resetting here was what blanked the thread.
  assert.equal(h.chat.streamBelongsToSession(h.store.sessionId.value, 'A'), true);
});

await check('resume_attaches_and_binds_the_stream_to_its_research', async () => {
  const h = storeHarness();
  h.store.rememberRun('A', 'run-a');
  h.setGet(() => Promise.resolve({status: 'running'}));
  const result = await h.store.resumeForSession('A', () => true);
  await tick();
  assert.equal(result.outcome, 'attached');
  assert.equal(result.runId, 'run-a');
  assert.equal(h.store.runId.value, 'run-a');
  // Without the owner binding, a switch back into A cannot tell its own stream
  // from one belonging to another research, so it would drop it a second time.
  assert.equal(h.store.sessionId.value, 'A');
});

await check('a_reconnect_keeps_the_research_binding', async () => {
  const h = storeHarness();
  h.store.watch('run-a', undefined, 'A');
  assert.equal(h.store.sessionId.value, 'A');
  h.store.retry();
  assert.equal(h.store.runId.value, 'run-a');
  assert.equal(h.store.sessionId.value, 'A');
});

await check('reset_releases_the_binding_with_the_stream', async () => {
  const h = storeHarness();
  h.store.watch('run-a', undefined, 'A');
  h.store.reset();
  assert.equal(h.store.runId.value, null);
  assert.equal(h.store.sessionId.value, null);
  // A released stream cannot keep a later switch from re-attaching.
  assert.equal(h.chat.streamBelongsToSession(h.store.sessionId.value, 'A'), false);
});

await check('a_run_that_ended_off_screen_reports_finished', async () => {
  const h = storeHarness();
  h.store.rememberRun('A', 'run-a');
  h.setGet(() => Promise.resolve({status: 'completed'}));
  const result = await h.store.resumeForSession('A', () => true);
  await tick();
  // No stream to attach: the persisted answer is the only copy. The caller keys
  // its re-read on this outcome, and only when the transcript lacks that run.
  assert.equal(result.outcome, 'finished');
  assert.equal(result.runId, 'run-a');
  assert.equal(h.store.runId.value, null);
  assert.equal(h.chat.hasRunAnswer([{seq: 1, role: 'user', content: 'q', run_id: 'run-a',
    created_at: null}], result.runId), false);
  assert.equal(h.chat.hasRunAnswer([{seq: 1, role: 'assistant', content: 'a', run_id: 'run-a',
    created_at: null}], result.runId), true);
});

await check('a_switch_before_the_reply_lands_stays_unattached', async () => {
  const h = storeHarness();
  h.store.rememberRun('A', 'run-a');
  h.setGet(() => Promise.resolve({status: 'running'}));
  // The user is already back on another research when the summary read resolves.
  const result = await h.store.resumeForSession('A', () => false);
  await tick();
  assert.equal(result.outcome, 'none');
  assert.equal(h.store.runId.value, null);
  assert.equal(h.store.sessionId.value, null);
});

// Negative control: the pre-fix call shape (`watch(id)` with no owner) leaves the
// stream unbound, which is precisely what made a switch A -> B -> A drop it and
// show an empty thread. The assertions above distinguish bound from unbound, so
// they are not vacuous.
await check('negative_control_unbound_stream_looks_foreign_to_its_own_research', async () => {
  const h = storeHarness();
  h.store.watch('run-a');
  assert.equal(h.store.runId.value, 'run-a');
  assert.equal(h.store.sessionId.value, null);
  assert.equal(h.chat.streamBelongsToSession(h.store.sessionId.value, 'A'), false);
});

fs.writeFileSync(path.join(dir, 'results.json'),
  JSON.stringify({mode: 'actual source; reactive/HTTP doubles; no browser', records: results}, null, 2));
for (const r of results) console.log(r.outcome + ' ' + r.test + (r.evidence ? ' ' + r.evidence.replaceAll('\n', ' ') : ''));
process.exitCode = results.some(r => r.outcome === 'failed') ? 1 : 0;
