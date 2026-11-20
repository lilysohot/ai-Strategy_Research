<script setup lang="ts">
import { computed } from 'vue'
import type { Space, LinkRun, Delivery } from '../api/superLink'
import { linkLabel } from '../utils/superLink'

const props = defineProps<{
  space?: Space | null
  runs?: LinkRun[]
  deliveries?: Delivery[]
  stale?: boolean
  history?: boolean
}>()

// The inspector visualizes the existing side-check, not a third participant/session.
const stations = computed(() => [
  { id: 'team', name: 'Team', title: '研究员', task: '拆解目标 · 深入研究', number: '01', screen: 'RESEARCH', color: 'green' },
  { id: 'inspector', name: 'Inspector', title: '核查员', task: '独立核查 · 反馈补正', number: '02', screen: 'REVIEW', color: 'amber' },
  { id: 'single', name: 'Single', title: '跟进员', task: '承接交付 · 持续跟进', number: '03', screen: 'FOLLOW UP', color: 'blue' },
].map(station => {
  let status = '等待任务'
  let working = false
  let attention = false
  if (props.space) {
    if (station.id === 'inspector') {
      const checks = props.deliveries ?? []
      const inspecting = checks.find(d => d.phase === 'inspecting')
      const blocked = checks.find(d => ['inspection_retry', 'inspection_exhausted', 'inspection_configuration_required', 'correction_required'].includes(d.phase))
      const waiting = checks.find(d => d.phase === 'awaiting_inspection')
      const checked = checks.find(d => d.inspection)
      working = !!inspecting
      attention = !!blocked && !working
      status = inspecting ? '正在核查' : blocked ? linkLabel(blocked.phase)
        : waiting ? '等待核查' : checked ? `核查：${linkLabel(checked.inspection!.verdict)}` : '等待交付'
    } else {
      const peer = props.space.participants?.find(p => p.role === station.id)
      const records = (props.runs ?? []).filter(r => r.session_id === peer?.session_id)
      const running = records.find(r => r.status === 'running')
      const queued = records.find(r => r.status === 'queued')
      const latest = running ?? queued ?? records[0]
      working = !!running
      attention = !!latest && (latest.status === 'failed' || !!latest.finalization?.error || !!latest.dispatch?.error)
      status = latest ? linkLabel(latest.finalization?.error ?? (latest.dispatch?.error ? 'admission_held' : latest.status)) : '等待任务'
    }
    if (props.space.control_state === 'stopped') { status = '已停止'; working = false }
    else if (props.space.control_state === 'stopping') { status = working ? '正在收尾' : '正在停止' }
    else if (props.space.paused && !working) { status = '协作已暂停' }
  } else status = '准备就绪'
  if (props.history) { status = `历史记录 · ${status}`; working = false }
  if (props.stale) { status = '状态待同步'; working = false; attention = true }
  return { ...station, status, working, attention }
}))

// A tiny code-native sprite keeps each outfit crisp and independently animatable.
const sprite = [
  '....hhhhhh....',
  '...hhhhhhhh...',
  '..hhhhhhhhhh..',
  '..hhhsssshhh..',
  '..hssssssssh..',
  '..hssessessh..',
  '...ssssssss...',
  '....ssssss....',
  '.....ssss.....',
  '...cccllccc...',
  '..ccccclcccc..',
  '..ccccclcccc..',
  '..ssccclccss..',
  '..sssccccsss..',
  '....cccccc....',
  '....pppppp....',
  '....pp..pp....',
  '...eee..eee...',
]
const pixels = sprite.flatMap((row, y) => [...row].flatMap((color, x) => color === '.' ? [] : [{ x, y, color }]))
</script>

<template>
  <section class="studio" aria-label="三位 Agent 协作工作室">
    <header class="studio-top">
      <div class="studio-sign"><span class="pixel-mark" aria-hidden="true">▦</span> AGENT STUDIO <span class="studio-edition">/ 共同目标，独立思考</span></div>
      <span class="studio-live"><i :class="{ live: space && !stale && !history }" />{{ stale ? '等待同步' : history ? '历史记录' : space ? '协作现场' : '协作流程预览' }}</span>
    </header>
    <div class="studio-room">
      <div class="room-decor" aria-hidden="true"><span>RESEARCH TOGETHER.</span><div class="wall-window"><i /><i /><i /><i /></div><span class="wall-clock">◷</span></div>
      <div class="stations">
        <article v-for="station in stations" :key="station.id" class="station" :class="[station.color, { working: station.working }]" :data-agent="station.id">
          <div class="station-label"><span>{{ station.number }} / {{ station.name }}</span><span class="station-status" :class="{ attention: station.attention }"><i />{{ station.status }}</span></div>
          <svg class="workstation" viewBox="0 0 240 160" shape-rendering="crispEdges" aria-hidden="true">
            <!-- Floor shadows, chair and the rear edge of the shared desk. -->
            <path d="M22 139H218V146H22Z" fill="var(--floor-shadow)" />
            <path d="M142 102H174V136H142ZM152 136H164V143H152ZM137 143H179V147H137Z" fill="#363d3b" />
            <path d="M26 100H214V110H26ZM32 110H39V141H32ZM201 110H208V141H201Z" fill="#75604b" />
            <path d="M26 100H214V104H26Z" fill="#bba383" />
            <!-- CRT monitor with different content for each agent. -->
            <path d="M43 42H111V47H116V92H109V97H47V92H39V47H43Z" fill="#a7afa3" />
            <path d="M46 49H108V86H46Z" fill="#202e2c" />
            <path d="M67 97H88V102H67Z" fill="#7d877c" />
            <path d="M102 90H106V93H102Z" fill="var(--agent-bright)" />
            <g fill="var(--agent-bright)" class="screen-content">
              <template v-if="station.id === 'team'"><path d="M52 55H77V58H52ZM52 63H98V66H52ZM52 70H88V73H52ZM52 77H69V80H52Z" /><path class="screen-cursor" d="M74 77H79V80H74Z" /></template>
              <template v-else-if="station.id === 'inspector'"><path d="M52 57H56V61H52ZM60 57H98V60H60ZM52 68H56V72H52ZM60 68H89V71H60ZM52 78H56V81H52ZM60 78H96V81H60Z" /></template>
              <template v-else><path d="M52 74H57V80H52ZM61 66H66V80H61ZM70 69H75V80H70ZM79 58H84V80H79ZM88 62H93V80H88ZM97 54H102V80H97Z" /></template>
            </g>
            <!-- Individual characters: headphones, spectacles, and a blue cap. -->
            <g class="pixel-person">
              <rect v-for="pixel in pixels" :key="`${pixel.x}-${pixel.y}`" :x="126 + pixel.x * 3" :y="48 + pixel.y * 3" width="3" height="3" :class="`pixel-${pixel.color}`" />
              <path v-if="station.id === 'team'" d="M129 57H135V75H129ZM165 57H171V75H165ZM135 48H165V51H135Z" fill="#d9cfad" />
              <path v-if="station.id === 'inspector'" d="M135 61H147V70H135ZM153 61H165V70H153ZM147 64H153V67H147Z" fill="#514a3e" /><path v-if="station.id === 'inspector'" d="M138 64H144V67H138ZM156 64H162V67H156Z" fill="#d4e6d9" />
              <path v-if="station.id === 'single'" d="M135 48H165V54H135ZM132 54H174V60H132Z" fill="#7cb7ca" />
            </g>
            <!-- Foreground desktop, keyboard, typing hands and mug. -->
            <path d="M26 104H214V111H26Z" fill="#a38b6d" />
            <path d="M110 100H165V105H110Z" fill="#c8c9b7" />
            <path d="M115 101H121V103H115ZM125 101H131V103H125ZM135 101H141V103H135ZM145 101H160V103H145Z" fill="#6e7c76" />
            <g class="typing-hands" fill="#e7b992"><path d="M128 96H140V101H128ZM150 97H162V102H150Z" /></g>
            <path d="M185 90H197V101H185ZM197 92H202V98H197Z" fill="var(--agent-bright)" /><path d="M188 86H191V81H188Z" fill="#b7b7a1" opacity=".6" />
            <template v-if="station.id === 'team'"><path d="M14 111H27V135H14Z" fill="#b18a63" /><path d="M17 89H23V114H17ZM9 97H17V108H9ZM23 92H31V103H23Z" fill="#79966a" /></template>
            <template v-if="station.id === 'inspector'"><path d="M207 88H226V101H207Z" fill="#d8cba8" /><path d="M207 91H226V94H207ZM207 97H226V100H207Z" fill="#9a8666" /></template>
            <text x="76" y="125" text-anchor="middle" fill="var(--scene-ink)" font-size="6" font-family="monospace" letter-spacing="1">{{ station.screen }}</text>
          </svg>
          <footer class="station-caption"><h3>{{ station.title }}</h3><p>{{ station.task }}</p></footer>
        </article>
      </div>
    </div>
    <footer class="studio-bottom"><span><i class="route-dot" /> Team 研究 <b>→</b> 独立核查 <b>→</b> Single 跟进</span><span>交付连接记忆，反馈推动下一轮</span></footer>
  </section>
</template>

<style scoped>
.studio{--scene-bg:#202b26;--scene-wall:#29362e;--scene-line:#435047;--scene-ink:#c0c9ba;--floor-shadow:#17231e;--agent-bright:#b0cca0;overflow:hidden;border:1px solid var(--line);border-radius:16px;background:var(--scene-bg);margin:24px 0;color:#eeeade}
.studio-top,.studio-bottom{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:17px 24px;font-size:11px}
.studio-top{border-bottom:1px solid var(--scene-line)}.studio-sign{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;letter-spacing:2px;display:flex;align-items:center;gap:12px}.pixel-mark{font-size:21px;color:#d5c17a}.studio-edition{font-family:inherit;letter-spacing:1px;color:var(--scene-ink)}
.studio-live{display:flex;align-items:center;gap:7px;white-space:nowrap;color:var(--scene-ink)}.studio-live i,.station-status i{width:5px;height:5px;display:inline-block;background:#a5ad9c}.studio-live i.live{background:#c5ce90}
.studio-room{position:relative;padding:0 24px;background:linear-gradient(0deg,transparent 64px,var(--scene-wall) 64px);isolation:isolate}.studio-room:after{content:'';position:absolute;inset:auto 0 0;height:64px;background:repeating-linear-gradient(90deg,transparent 0,transparent 79px,var(--scene-line) 80px),repeating-linear-gradient(0deg,transparent 0,transparent 31px,var(--scene-line) 32px);opacity:.35;z-index:-1}
.room-decor{height:69px;display:flex;align-items:center;justify-content:space-between;padding:0 12px;color:#9eae9c;font:10px ui-monospace,monospace;letter-spacing:3px}.wall-window{display:grid;grid-template-columns:repeat(4,24px);gap:4px;padding:4px;background:#152520;border:3px solid #5b6c5e}.wall-window i{height:25px;background:#819888}.wall-window i:nth-child(even){background:#aab9a0}.wall-clock{font-size:28px;line-height:1;letter-spacing:0}
.stations{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:28px}.station{min-width:0;--agent-bright:#b3c998;--agent-shirt:#8eab78;--agent-hair:#5d493d}.station.amber{--agent-bright:#dfc289;--agent-shirt:#c6a96b;--agent-hair:#b89870}.station.blue{--agent-bright:#9ec9d6;--agent-shirt:#6d9dae;--agent-hair:#3f443f}
.station-label{display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;border-top:1px solid var(--scene-line);padding-top:13px;font:11px ui-monospace,monospace;color:var(--agent-bright)}.station-status{display:flex;align-items:center;gap:6px;font:11px inherit;color:var(--scene-ink)}.station-status.attention{color:#edbc86}.working .station-status i{background:var(--agent-bright)}
.workstation{display:block;width:100%;max-width:340px;margin:0 auto;image-rendering:pixelated;overflow:visible}.pixel-h{fill:var(--agent-hair)}.pixel-s{fill:#e7b992}.pixel-e{fill:#343b38}.pixel-c{fill:var(--agent-shirt)}.pixel-l{fill:#e0d8bc}.pixel-p{fill:#4e5b52}.station-caption{text-align:center;padding:0 0 24px}.station-caption h3{font-size:16px;letter-spacing:2px;margin:0 0 8px;font-weight:500}.station-caption p{font-size:12px;color:var(--scene-ink);margin:0}
.studio-bottom{border-top:1px solid var(--scene-line);color:var(--scene-ink);font-size:12px;flex-wrap:wrap}.studio-bottom b{font-weight:400;margin:0 14px;color:#8c9d8e}.route-dot{display:inline-block;width:6px;height:6px;background:#d6be77;margin-right:9px}.working .typing-hands{animation:typing .4s steps(2,end) infinite}.working .screen-cursor{animation:blink 1s steps(2,end) infinite}.working .pixel-person{animation:working 1.6s steps(2,end) infinite}
@keyframes typing{50%{transform:translateY(-2px)}}@keyframes blink{50%{opacity:0}}@keyframes working{50%{transform:translateY(1px)}}
:global([data-theme='light'] .studio){--scene-bg:#eee7d7;--scene-wall:#e6e1d1;--scene-line:#c4c5b1;--scene-ink:#616c5d;--floor-shadow:#d1cebc;color:#343e34}
:global([data-theme='light'] .studio .station){--agent-bright:#64804f}:global([data-theme='light'] .studio .station.amber){--agent-bright:#8a682e}:global([data-theme='light'] .studio .station.blue){--agent-bright:#45788b}:global([data-theme='light'] .studio .screen-content){fill:#bdd5af}:global([data-theme='light'] .studio .station-status.attention){color:#925a23}:global([data-theme='light'] .studio .pixel-mark){color:#8a7033}:global([data-theme='light'] .studio .room-decor){color:#77826a}
@media(max-width:900px){.studio-edition{display:none}.stations{gap:16px}.studio-room{padding:0 16px}.studio-top,.studio-bottom{padding:16px}.station-status{width:100%}.studio-bottom>span:last-child{display:none}}
@media(max-width:560px){.stations{grid-template-columns:1fr;gap:0}.room-decor{height:54px}.station{display:grid;grid-template-columns:minmax(0,1fr) 100px;align-items:center}.station-label{grid-column:1/-1;flex-wrap:nowrap;padding-top:14px}.station-status{width:auto}.station-caption{text-align:left;padding:0}.station-caption h3{font-size:15px}.station-caption p{font-size:11px;line-height:1.8;max-width:80px}.workstation{max-width:240px}.studio-bottom{font-size:10px}.studio-bottom b{margin:0 6px}.studio-sign{font-size:10px;letter-spacing:1px}.studio-live{font-size:10px}.studio-room{background:var(--scene-wall)}.wall-window{grid-template-columns:repeat(4,16px)}.wall-window i{height:16px}.room-decor>span:first-child{font-size:8px;letter-spacing:1px}}
@media(prefers-reduced-motion:reduce){.working .typing-hands,.working .screen-cursor,.working .pixel-person{animation:none}}
</style>
