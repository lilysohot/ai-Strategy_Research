<script setup lang="ts">
defineProps<{ motif: 'orbit' | 'grid' | 'ripple' }>()
</script>

<template>
  <div class="blog-art" :class="`blog-art--${motif}`" aria-hidden="true">
    <div class="art-field"><i v-for="n in 7" :key="n" :style="{ '--n': n }"></i></div>
    <span class="art-dot"></span>
    <span class="art-index">{{ motif === 'grid' ? '01 / STRUCTURE' : motif === 'orbit' ? '02 / CURIOSITY' : '03 / EVERYDAY' }}</span>
    <span class="art-plus">+</span>
  </div>
</template>

<style scoped>
.blog-art {
  position: relative;
  height: 100%;
  min-height: 160px;
  overflow: hidden;
  background: #19251c;
  color: #d6c989;
}
.art-field { position: absolute; inset: 0; }
.art-index { position: absolute; bottom: 18px; left: 20px; font: 8px monospace; letter-spacing: 2px; color: #afb49a; }
.art-plus { position: absolute; top: 12px; right: 18px; font: 18px monospace; color: #b9bf9c; }
.blog-art--orbit { background: radial-gradient(ellipse at 50% 50%, #5f643c50, transparent 65%), #172119; }
.blog-art--orbit i { position: absolute; top: 50%; left: 50%; width: calc(32px + var(--n) * 28px); aspect-ratio: 1; border: 1px solid #d6c98955; border-radius: 50%; transform: translate(-50%, -50%) rotateX(48deg) rotate(-30deg); }
.blog-art--orbit .art-dot { position: absolute; width: 9px; height: 9px; border-radius: 50%; background: #d6c989; top: 40%; left: 60%; box-shadow: 0 0 24px #d6c98977; }
.blog-art--grid { background: #18231e; }
.blog-art--grid .art-field { inset: -30%; transform: perspective(400px) rotateX(50deg) rotateZ(-30deg); background-image: linear-gradient(#b8c1a220 1px, transparent 1px), linear-gradient(90deg, #b8c1a220 1px, transparent 1px); background-size: 32px 32px; }
.blog-art--grid i { position: absolute; left: calc(20% + var(--n) * 5%); top: calc(20% + var(--n) * 4%); width: 22%; height: 24%; border: 1px solid #d6c98980; background: #a5b08308; }
.blog-art--ripple { background: #242a20; }
.blog-art--ripple i { position: absolute; width: calc(30px + var(--n) * 38px); height: calc(18px + var(--n) * 22px); left: 50%; top: 50%; border: 1px solid #c6b98970; border-radius: 50%; transform: translate(-50%, -50%) rotate(-32deg); }
.blog-art--ripple .art-dot { position: absolute; width: 28px; height: 28px; border-radius: 50%; left: calc(50% - 14px); top: calc(50% - 14px); background: #c4b77d; box-shadow: 0 0 38px #c4b77d30; }
</style>
