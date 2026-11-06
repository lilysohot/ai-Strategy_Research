<script setup lang="ts">
import OrbitGlobe from './OrbitGlobe.vue'

defineProps<{ entered: boolean }>()
</script>

<template>
  <div class="orbit-scene" :class="{ 'orbit-scene--entered': entered }" aria-hidden="true">
    <div class="orbit-halo"></div>
    <div class="orbit-system">
      <div class="orbit-axis axis-one"></div>
      <div class="orbit-axis axis-two"></div>
      <div class="orbit-axis axis-three"></div>
      <div class="orbit-ring ring-one"><span></span></div>
      <div class="orbit-ring ring-two"><span></span></div>
      <div class="orbit-ring ring-three"><span></span></div>
      <div class="orbit-core">
        <OrbitGlobe />
      </div>
      <span class="orbit-cross cross-one">+</span>
      <span class="orbit-cross cross-two">+</span>
      <span class="orbit-caption">THE UNKNOWN IS AN INVITATION</span>
      <span class="orbit-coordinate">∞ POSSIBILITIES</span>
    </div>
  </div>
</template>

<style scoped>
.orbit-scene {
  position: absolute;
  width: min(58vw, 790px);
  aspect-ratio: 1;
  right: -4%;
  top: 50%;
  transform: translateY(-50%);
  pointer-events: none;
  transition: right 1.1s cubic-bezier(.22, 1, .36, 1), opacity .8s, transform 1.1s;
}

.orbit-scene--entered {
  right: 49%;
  transform: translateY(-55%) scale(.87);
  opacity: .75;
}

.orbit-halo {
  position: absolute;
  inset: -12%;
  background: radial-gradient(ellipse, #b8ae4520, #a7a45108 40%, transparent 68%);
}

.orbit-system {
  position: absolute;
  inset: 9%;
  transform: rotate(-24deg);
}

.orbit-axis {
  position: absolute;
  border: 1px solid #d2c57a1a;
  border-radius: 50%;
  inset: 0;
}

.axis-two {
  inset: -7%;
  border-style: dashed;
  opacity: .55;
}

.axis-three {
  inset: 9%;
}

.orbit-ring {
  position: absolute;
  inset: 0;
  border: 1px solid #d6cb855c;
  border-radius: 50%;
  animation: revolve 42s linear infinite;
}

.ring-two {
  inset: 13%;
  border-color: #d6cb853d;
  animation-duration: 32s;
  animation-direction: reverse;
}

.ring-three {
  inset: 26%;
  border-color: #d6cb8570;
  animation-duration: 24s;
}

.orbit-ring > span {
  position: absolute;
  top: 50%;
  left: -4px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #e0d391;
  box-shadow: 0 0 18px #d2c06399;
}

.ring-two > span {
  width: 5px;
  height: 5px;
  left: -2px;
}

.ring-three > span {
  width: 6px;
  height: 6px;
  left: -3px;
}

.orbit-core {
  position: absolute;
  inset: 32%;
  border-radius: 50%;
  border: 1px solid #dfcf8177;
  overflow: hidden;
  background: radial-gradient(circle at 28% 24%, #d3c57466, #78763040 42%, #0a100c 83%);
  box-shadow: inset -18px -12px 35px #050a0899, 0 0 65px #d5c26a10;
  animation: breathe 8s ease-in-out infinite alternate;
}

.orbit-core::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: 50%;
  pointer-events: none;
  background: radial-gradient(circle at 28% 24%, #f3e5a00a 12%, transparent 40%, #050a0870 78%, #050a08b3);
  box-shadow: inset 2px 2px 8px #e7d99018;
}

.orbit-cross {
  position: absolute;
  color: #d5c9898c;
  font: 20px monospace;
}

.cross-one {
  top: 9%;
  left: 12%;
}

.cross-two {
  bottom: 9%;
  right: 12%;
}

.orbit-caption, .orbit-coordinate {
  position: absolute;
  font: 9px monospace;
  letter-spacing: 2px;
  color: #a5a58a;
}

.orbit-caption {
  top: 51%;
  right: -24%;
  transform: rotate(90deg);
}

.orbit-coordinate {
  bottom: 10%;
  left: 28%;
  transform: rotate(24deg);
}

@keyframes revolve {
  to {
    transform: rotate(360deg);
  }
}

@keyframes breathe {
  to {
    box-shadow: inset -18px -12px 35px #050a0899, 0 0 80px #d5c26a26;
  }
}

@media (max-width: 760px) {
  .orbit-scene {
    width: 440px;
    right: -210px;
    top: 40%;
    opacity: .52;
  }
  .orbit-scene--entered {
    right: -250px;
    transform: translateY(-50%) scale(.8);
    opacity: .2;
  }
}

@media (prefers-reduced-motion: reduce) {
  .orbit-scene {
    transition: none;
  }
  .orbit-ring, .orbit-core {
    animation: none;
  }
}
</style>
