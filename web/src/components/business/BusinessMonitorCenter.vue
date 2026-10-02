<script setup lang="ts">
import { computed, reactive, ref } from 'vue'

const view = ref<'rules' | 'create'>('create')

const form = reactive({
  symbol: '',
  market: '',
  quoteBasis: '',
  currency: 'CNY',
  direction: 'above',
  threshold: '',
  expiresAt: '',
  triggerMode: 'once',
  action: 'notify',
  task: '',
  budget: '',
  alreadyMet: 'wait_next',
})

const readiness = computed(() => {
  const missing: string[] = []
  if (!form.symbol.trim()) missing.push('标的')
  if (!form.market) missing.push('市场')
  if (!form.quoteBasis) missing.push('行情口径')
  if (!form.threshold.trim()) missing.push('阈值')
  if (!form.expiresAt) missing.push('有效期')
  if (form.action === 'auto_analysis' && !form.task.trim()) missing.push('分析任务')
  return missing
})
</script>

<template>
  <div class="monitor-layout">
    <main class="monitor-main">
      <header class="monitor-head">
        <div>
          <p class="eyebrow">后台监控 · UI-08 / 09</p>
          <h2>页面负责说明规则，后台负责持续执行</h2>
          <p>关闭页面不会停止已生效规则；报价时间、接收时间与质量状态分别展示。</p>
        </div>
        <div class="backend-state"><span />后台状态待接入</div>
      </header>

      <nav class="monitor-tabs" aria-label="监控页面">
        <button type="button" :class="{ active: view === 'rules' }" @click="view = 'rules'">规则管理</button>
        <button type="button" :class="{ active: view === 'create' }" @click="view = 'create'">新建规则</button>
      </nav>

      <section v-if="view === 'rules'" class="empty-rules">
        <span class="empty-index">00</span>
        <h3>尚无已连接的监控规则</h3>
        <p>接入 DATA-09 后，这里按规则版本展示启用、暂停、冷却、行情质量和最近检查时间。</p>
        <el-button type="primary" @click="view = 'create'">查看创建表单</el-button>
      </section>

      <section v-else class="monitor-form">
        <div class="form-chapter">
          <span>01 / 触发条件</span>
          <h3>标的、口径与阈值</h3>
        </div>
        <div class="form-grid">
          <label class="field">
            <span>标的 <em>必填</em></span>
            <el-input v-model="form.symbol" placeholder="代码或标准标识" />
          </label>
          <label class="field">
            <span>市场 <em>必填</em></span>
            <el-select v-model="form.market" placeholder="选择市场">
              <el-option label="中国内地" value="CN" />
              <el-option label="香港" value="HK" />
              <el-option label="美国" value="US" />
            </el-select>
          </label>
          <label class="field">
            <span>行情口径 <em>必填</em></span>
            <el-select v-model="form.quoteBasis" placeholder="不可由页面猜测">
              <el-option label="最新成交" value="last_trade" />
              <el-option label="买一价" value="best_bid" />
              <el-option label="卖一价" value="best_ask" />
            </el-select>
          </label>
          <label class="field">
            <span>币种</span>
            <el-select v-model="form.currency">
              <el-option label="人民币 CNY" value="CNY" />
              <el-option label="美元 USD" value="USD" />
              <el-option label="港币 HKD" value="HKD" />
            </el-select>
          </label>
          <label class="field">
            <span>触发方向</span>
            <el-segmented v-model="form.direction" :options="[{ label: '高于或等于', value: 'above' }, { label: '低于或等于', value: 'below' }]" />
          </label>
          <label class="field">
            <span>阈值 <em>必填</em></span>
            <el-input v-model="form.threshold" inputmode="decimal" placeholder="不提供默认数值">
              <template #append>{{ form.currency }}</template>
            </el-input>
          </label>
          <label class="field field--wide">
            <span>有效期 <em>必填</em></span>
            <el-date-picker v-model="form.expiresAt" type="datetime" placeholder="选择规则失效时间" />
          </label>
        </div>

        <div class="form-chapter form-chapter--spaced">
          <span>02 / 触发动作</span>
          <h3>提醒，还是自动分析</h3>
        </div>
        <div class="choice-grid">
          <button type="button" :class="{ active: form.action === 'notify' }" @click="form.action = 'notify'">
            <strong>仅提醒</strong>
            <small>记录触发并发送站内通知，不创建分析 Run</small>
          </button>
          <button type="button" :class="{ active: form.action === 'auto_analysis' }" @click="form.action = 'auto_analysis'">
            <strong>自动分析</strong>
            <small>明确保存自动执行意图，并受任务和预算约束</small>
          </button>
        </div>
        <div v-if="form.action === 'auto_analysis'" class="form-grid action-fields">
          <label class="field field--wide">
            <span>分析任务 <em>必填</em></span>
            <el-input v-model="form.task" type="textarea" :rows="3" placeholder="说明触发后需要分析什么" />
          </label>
          <label class="field">
            <span>预算上限</span>
            <el-input v-model="form.budget" inputmode="decimal" placeholder="由服务端契约定义单位" />
          </label>
        </div>

        <div class="form-chapter form-chapter--spaced">
          <span>03 / 生命周期</span>
          <h3>触发次数与创建时已达标</h3>
        </div>
        <div class="form-grid">
          <label class="field">
            <span>触发次数模式</span>
            <el-select v-model="form.triggerMode">
              <el-option label="单次触发（C 阶段）" value="once" />
              <el-option label="重复触发（D 阶段，暂不可用）" value="repeat" disabled />
            </el-select>
          </label>
          <label class="field">
            <span>创建时已经满足阈值</span>
            <el-select v-model="form.alreadyMet">
              <el-option label="等待下一次跨越阈值" value="wait_next" />
              <el-option label="创建后立即按当前观测判定" value="evaluate_now" />
            </el-select>
          </label>
        </div>
      </section>
    </main>

    <aside class="monitor-aside">
      <div class="quote-card">
        <span>行情可用性</span>
        <strong>等待 DATA-09 能力探测</strong>
        <dl>
          <div><dt>观测时间</dt><dd>—</dd></div>
          <div><dt>接收时间</dt><dd>—</dd></div>
          <div><dt>质量状态</dt><dd>未连接</dd></div>
          <div><dt>采样频率</dt><dd>由服务端返回</dd></div>
        </dl>
        <p>没有可靠观测时间时，页面不会把“刚收到报价”写成“最新成交”。</p>
      </div>

      <div class="rule-preview">
        <span>规则预检</span>
        <h3>{{ readiness.length ? `${readiness.length} 项尚未填写` : '前端字段已齐' }}</h3>
        <ul v-if="readiness.length">
          <li v-for="item in readiness" :key="item">{{ item }}</li>
        </ul>
        <p v-else>还需要服务端校验标的能力、报价来源、归属、预算与幂等结果。</p>
      </div>

      <div class="lifecycle-note">
        <span>版本边界</span>
        <p>编辑阈值会创建新规则版本；未启动事件按服务端回执处理，既有 Run 的输入不会被改写。</p>
      </div>

      <el-tooltip content="等待 DATA-09/10 规则接口" placement="top">
        <span class="full-action"><el-button type="primary" disabled>创建监控规则</el-button></span>
      </el-tooltip>
    </aside>
  </div>
</template>

<style scoped>
.monitor-layout { display: grid; grid-template-columns: minmax(0, 1fr) 330px; min-height: 100%; }
.monitor-main { min-width: 0; padding: 28px clamp(20px, 3vw, 44px) 52px; overflow: auto; }
.monitor-head { display: flex; justify-content: space-between; gap: 24px; padding-bottom: 24px; border-bottom: 1px solid var(--line); }
.monitor-head h2 { margin: 4px 0 8px; font-family: 'Songti SC', 'Source Han Serif SC', serif; font-size: clamp(24px, 3vw, 34px); line-height: 1.2; }
.monitor-head p:not(.eyebrow) { max-width: 680px; margin: 0; color: var(--muted); }
.eyebrow { margin: 0; color: var(--accent); font-size: 11px; font-weight: 700; letter-spacing: .12em; }
.backend-state { display: flex; align-self: flex-start; align-items: center; gap: 8px; padding-top: 8px; color: var(--muted); white-space: nowrap; }
.backend-state span { width: 8px; height: 8px; border-radius: 50%; background: var(--quiet); }
.monitor-tabs { display: flex; gap: 0; margin: 26px 0; border-bottom: 1px solid var(--line); }
.monitor-tabs button { padding: 10px 16px; border: 0; border-bottom: 2px solid transparent; background: transparent; color: var(--muted); cursor: pointer; }
.monitor-tabs button.active { border-color: var(--accent); color: var(--text); }
.empty-rules { min-height: 420px; display: grid; place-items: center; align-content: center; text-align: center; }
.empty-rules h3 { margin: 10px 0 5px; font-size: 20px; }
.empty-rules p { max-width: 520px; margin: 0 0 18px; color: var(--muted); }
.empty-index { color: var(--line-strong); font-family: 'Songti SC', serif; font-size: 72px; line-height: 1; }
.form-chapter { display: flex; align-items: baseline; justify-content: space-between; gap: 20px; }
.form-chapter span { color: var(--accent); font-size: 11px; font-weight: 700; letter-spacing: .1em; }
.form-chapter h3 { margin: 0 0 18px; font-size: 20px; }
.form-chapter--spaced { margin-top: 34px; padding-top: 24px; border-top: 1px solid var(--line); }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px 22px; }
.field { display: flex; min-width: 0; flex-direction: column; gap: 7px; color: var(--text-soft); }
.field--wide { grid-column: 1 / -1; }
.field > span { font-size: 13px; font-weight: 600; }
.field em { color: var(--warning); font-style: normal; }
.field :deep(.el-select), .field :deep(.el-date-editor) { width: 100%; }
.choice-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
.choice-grid button { display: flex; flex-direction: column; gap: 5px; padding: 16px; border: 1px solid var(--line); border-radius: 5px; background: var(--bg-input); color: var(--text); text-align: left; cursor: pointer; }
.choice-grid button.active { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 8%, var(--bg-input)); }
.choice-grid small { color: var(--muted); }
.action-fields { margin-top: 18px; }
.monitor-aside { padding: 28px 22px; border-left: 1px solid var(--line); background: #141711; overflow: auto; }
.quote-card, .rule-preview, .lifecycle-note { padding: 18px 0; border-bottom: 1px solid var(--line); }
.quote-card:first-child { padding-top: 0; border-top: 2px solid var(--accent); padding-top: 14px; }
.quote-card > span, .rule-preview > span, .lifecycle-note > span { color: var(--accent); font-size: 11px; font-weight: 700; letter-spacing: .09em; }
.quote-card strong { display: block; margin: 7px 0 10px; }
.quote-card dl { margin: 0; }
.quote-card dl div { display: grid; grid-template-columns: 90px 1fr; gap: 10px; padding: 6px 0; }
.quote-card dt { color: var(--muted); }
.quote-card dd { margin: 0; text-align: right; }
.quote-card p, .rule-preview p, .lifecycle-note p { color: var(--muted); font-size: 12px; }
.rule-preview h3 { margin: 7px 0; }
.rule-preview ul { margin: 8px 0 0; padding-left: 18px; color: var(--text-soft); }
.full-action, .full-action :deep(.el-button) { width: 100%; margin-top: 20px; }
@media (max-width: 980px) { .monitor-layout { grid-template-columns: 1fr; } .monitor-aside { border-top: 1px solid var(--line); border-left: 0; } }
@media (max-width: 640px) {
  .monitor-main { padding: 20px 14px 36px; }
  .monitor-head { flex-direction: column; gap: 10px; }
  .form-grid, .choice-grid { grid-template-columns: 1fr; }
  .field--wide { grid-column: auto; }
}
</style>
