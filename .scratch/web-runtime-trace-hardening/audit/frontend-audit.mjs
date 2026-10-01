// Executes actual TypeScript store/SSE code with reactive and IO test doubles.
// No browser, network, model calls, or production data.
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
const dir=path.dirname(fileURLToPath(import.meta.url));
const root=path.resolve(dir,'../../..');
const req=createRequire(path.join(root,'web/package.json'));
const ts=req('typescript');
const results=[];
async function check(name,fn) {
  try { await fn(); results.push({test:name,outcome:'passed'}); }
  catch(e) { results.push({test:name,outcome:'failed',evidence:e.message}); }
}
function storeHarness() {
  let callbacks;
  let getSummary=async()=>({status:'completed',usage:{total_tokens:10,prompt_tokens:8,completion_tokens:2}});
  let getControls=async()=>({controls:[]});
  const cache=new Map();
  function load(file) {
    file=path.resolve(file);
    if(!path.extname(file)) file=fs.existsSync(file+'.ts')?file+'.ts':path.join(file,'index.ts');
    if(cache.has(file)) return cache.get(file).exports;
    const module={exports:{}};
    cache.set(file,module);
    const source=ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
    function localRequire(spec) {
      if(spec==='pinia') return {defineStore:(_,setup)=>setup};
      if(spec==='vue') return {ref:value=>({value}),computed:fn=>({get value(){return fn()}})};
      if(spec==='./auth') return {useAuthStore:()=>({token:'synthetic-token'})};
      if(spec==='../api') return {runs:{eventsUrl:id=>'/runs/'+id,get:id=>getSummary(id),
        controls:(id,params)=>getControls(id,params)}};
      if(spec==='../sse') return {openRunStream:opts=>{callbacks=opts; return {stop(){}}}};
      if(spec.startsWith('.')) return load(path.resolve(path.dirname(file),spec));
      throw Error('Unexpected dependency '+spec);
    }
    vm.runInNewContext('(function(require,module,exports){'+source+'\n})',{console,Date,Set,Promise})(localRequire,module,module.exports);
    return module.exports;
  }
  const store=load(path.join(root,'web/src/stores/runs.ts')).useRunStreamStore();
  return {store,setGet:fn=>{getSummary=fn},setControls:fn=>{getControls=fn},
    done:()=>callbacks.onDone('completed')};
}
const replay={type:'assistant_delta',turn:1,full:true,content:'complete text',thinking:'',usage:{total_tokens:10,prompt_tokens:8,completion_tokens:2}};
await check('F10_full_replay_repairs_missing_live_text',async()=>{
  const {store}=storeHarness();
  store.applyEvent({type:'assistant_delta',turn:1,text:'com'});
  store.applyEvent(replay);
  assert.equal(store.answer.value,'complete text');
});
await check('F10_live_turn_still_counts_replay_usage',async()=>{
  const {store}=storeHarness();
  store.applyEvent({type:'assistant_delta',turn:1,text:'com'});
  store.applyEvent(replay);
  assert.equal(store.usage.value.total,10);
});
const tick=()=>new Promise(resolve=>setImmediate(resolve));
await check('F10_final_usage_reconciliation_is_not_additive',async()=>{
  const h=storeHarness(); h.store.watch('A'); h.store.applyEvent(replay); h.done(); await tick();
  assert.equal(h.store.usage.value.total,10);
});
await check('F11_old_run_summary_cannot_overwrite_current_run',async()=>{
  const h=storeHarness(); let resolveA;
  h.setGet(()=>new Promise(resolve=>{resolveA=resolve}));
  h.store.watch('A'); h.done(); h.store.watch('B');
  resolveA({status:'completed',final_answer:'answer from A'}); await tick();
  assert.equal(h.store.finalAnswer.value,null);
});
await check('F09_steer_sequence_is_not_trajectory_cursor',async()=>{
  const source=ts.transpileModule(fs.readFileSync(path.join(root,'web/src/sse.ts'),'utf8'),
      {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
  const module={exports:{}};
  const payload='data: '+JSON.stringify({type:'steer_queued',seq:10})+'\n\n' +
                'data: '+JSON.stringify({type:'run_completed'})+'\n\n';
  vm.runInNewContext('(function(require,module,exports){'+source+'\n})',
    {AbortController,DOMException,TextDecoder,Math,Number,JSON,Set,Promise,setTimeout,clearTimeout,
     fetch:async()=>new Response(payload,{headers:{'Content-Type':'text/event-stream'}})})
    (()=>({TERMINAL_EVENT_TYPES:['run_completed','run_failed','run_stopped']}),module,module.exports);
  let cursor=0;
  await new Promise(resolve=>module.exports.openRunStream({url:'/synthetic',token:'synthetic',
    onEvent(){},onCursor:value=>{cursor=value},onDone:resolve,baseDelayMs:0,maxRetries:0}));
  assert.equal(cursor,0);
});
await check('F21_steer_applied_is_not_a_trajectory_cursor',async()=>{
  const source=ts.transpileModule(fs.readFileSync(path.join(root,'web/src/sse.ts'),'utf8'),
      {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
  const module={exports:{}};
  const payload='data: '+JSON.stringify({type:'steer_applied',seq:10,control_id:'c1'})+'\n\n' +
                'data: '+JSON.stringify({type:'run_completed'})+'\n\n';
  vm.runInNewContext('(function(require,module,exports){'+source+'\n})',
    {AbortController,DOMException,TextDecoder,Math,Number,JSON,Set,Promise,setTimeout,clearTimeout,
     fetch:async()=>new Response(payload,{headers:{'Content-Type':'text/event-stream'}})})
    (()=>({TERMINAL_EVENT_TYPES:['run_completed','run_failed','run_stopped']}),module,module.exports);
  let cursor=0;
  await new Promise(resolve=>module.exports.openRunStream({url:'/synthetic',token:'synthetic',
    onEvent(){},onCursor:value=>{cursor=value},onDone:resolve,baseDelayMs:0,maxRetries:0}));
  assert.equal(cursor,0);
});
const pendingControl={controls:[{control_id:'c-1',run_id:'A',kind:'approval',status:'pending',
  request:{tool_name:'bash',target:'rm -rf build/',reason:'需要确认',preview:'rm -rf build/',risk:'high'}}]};
await check('F21_pending_approval_is_rebuilt_after_a_refresh',async()=>{
  const h=storeHarness();
  let asked;
  h.setControls((id,params)=>{asked={id,params}; return Promise.resolve(pendingControl)});
  h.store.watch('A'); await tick();
  assert.equal(h.store.pendingApproval.value?.approvalId,'c-1');
  assert.equal(h.store.pendingApproval.value?.risk,'high');
  assert.equal(asked.id,'A');
  assert.equal(asked.params.status,'pending');
});
await check('F21_stale_control_recovery_cannot_overwrite_another_run',async()=>{
  const h=storeHarness(); const pending=[];
  h.setControls(id=>new Promise(resolve=>pending.push({id,resolve})));
  h.store.watch('A'); h.store.watch('B');
  pending.find(p=>p.id==='A').resolve(pendingControl); await tick();
  assert.equal(h.store.pendingApproval.value,null);
});
await check('F21_a_decided_approval_does_not_reopen_after_a_refresh',async()=>{
  const h=storeHarness();
  h.setControls(()=>Promise.resolve({controls:[{control_id:'c-1',run_id:'A',kind:'approval',
    status:'rejected',request:{tool_name:'bash'}}]}));
  h.store.watch('A'); await tick();
  assert.equal(h.store.pendingApproval.value,null);
});
await check('F21_steer_applied_is_counted_apart_from_queued',async()=>{
  const {store}=storeHarness();
  store.applyEvent({type:'steer_queued',steer_seq:1,message:'m'});
  assert.equal(store.steerApplied.value,0);
  store.applyEvent({type:'steer_applied',control_id:'c-1',steer_seq:1,turn_index:3});
  assert.equal(store.steerQueued.value,1);
  assert.equal(store.steerApplied.value,1);
});
fs.writeFileSync(path.join(dir,'frontend-results.json'),JSON.stringify({mode:'actual source; reactive/HTTP doubles; no browser',records:results},null,2));
for(const r of results) console.log(r.outcome+' '+r.test+(r.evidence?' '+r.evidence.replaceAll('\n',' '):''));
process.exitCode=results.some(r=>r.outcome==='failed')?1:0;
