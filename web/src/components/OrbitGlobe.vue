<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'

type Point3D = readonly [number, number, number]

const canvas = ref<HTMLCanvasElement>()
const lines: Point3D[][] = []
const segments = 96
const tilt = -Math.PI / 9

// Sample a unit sphere, then rotate and project its surface onto the canvas.
// Separate front/back strokes make the moving grid read as a volume.
for (let meridian = 0; meridian < 12; meridian++) {
  const longitude = meridian * Math.PI / 6
  lines.push(Array.from({ length: segments + 1 }, (_, index): Point3D => {
    const latitude = -Math.PI / 2 + index / segments * Math.PI
    return [Math.cos(latitude) * Math.sin(longitude), Math.sin(latitude),
      Math.cos(latitude) * Math.cos(longitude)]
  }))
}
for (const degrees of [-60, -30, 0, 30, 60]) {
  const latitude = degrees * Math.PI / 180
  lines.push(Array.from({ length: segments + 1 }, (_, index): Point3D => {
    const longitude = index / segments * Math.PI * 2
    return [Math.cos(latitude) * Math.sin(longitude), Math.sin(latitude),
      Math.cos(latitude) * Math.cos(longitude)]
  }))
}

let dispose = () => {}

onMounted(() => {
  const element = canvas.value
  const context = element?.getContext('2d')
  if (!element || !context) return

  const motion = window.matchMedia('(prefers-reduced-motion: reduce)')
  let width = 0
  let height = 0
  let angle = .35
  let visible = true
  let frame = 0
  let lastTime = 0

  function project([x, y, z]: Point3D): Point3D {
    const rotatedX = x * Math.cos(angle) + z * Math.sin(angle)
    const rotatedZ = z * Math.cos(angle) - x * Math.sin(angle)
    return [rotatedX, y * Math.cos(tilt) - rotatedZ * Math.sin(tilt),
      y * Math.sin(tilt) + rotatedZ * Math.cos(tilt)]
  }

  function draw() {
    if (!context || !width || !height) return
    context.clearRect(0, 0, width, height)
    const radius = Math.min(width, height) * .49
    const projected = lines.map(line => line.map(project))

    for (const front of [false, true]) {
      context.beginPath()
      for (const line of projected) {
        for (let index = 1; index < line.length; index++) {
          const from = line[index - 1]!
          const to = line[index]!
          if ((from[2] + to[2] >= 0) !== front) continue
          context.moveTo(width / 2 + from[0] * radius, height / 2 + from[1] * radius)
          context.lineTo(width / 2 + to[0] * radius, height / 2 + to[1] * radius)
        }
      }
      context.strokeStyle = front ? 'rgba(224, 211, 145, .58)' : 'rgba(183, 181, 124, .12)'
      context.lineWidth = front ? .85 : .65
      context.stroke()
    }

    // Surface markers follow the same 3D rotation and disappear behind the globe.
    for (const index of [2, 5, 8]) {
      const point = project(lines[index]![32 + index * 2]!)
      if (point[2] <= 0) continue
      context.beginPath()
      context.arc(width / 2 + point[0] * radius, height / 2 + point[1] * radius,
        1.4 + point[2] * .5, 0, Math.PI * 2)
      context.fillStyle = `rgba(241, 224, 156, ${point[2] * .8})`
      context.fill()
    }
  }

  function tick(time: number) {
    frame = requestAnimationFrame(tick)
    if (!lastTime) lastTime = time
    const elapsed = time - lastTime
    if (elapsed < 1000 / 30) return
    // One revolution every 32 seconds; avoid jumps after a background pause.
    angle += Math.min(elapsed, 100) / 32000 * Math.PI * 2
    lastTime = time
    draw()
  }

  function syncAnimation() {
    cancelAnimationFrame(frame)
    frame = 0
    lastTime = 0
    draw()
    if (visible && !motion.matches && !document.hidden) frame = requestAnimationFrame(tick)
  }

  function resize() {
    if (!element || !context) return
    width = element.clientWidth
    height = element.clientHeight
    const ratio = Math.min(window.devicePixelRatio || 1, 2)
    element.width = Math.round(width * ratio)
    element.height = Math.round(height * ratio)
    context.setTransform(ratio, 0, 0, ratio, 0, 0)
    draw()
  }

  const resizeObserver = new ResizeObserver(resize)
  const visibilityObserver = new IntersectionObserver(([entry]) => {
    visible = entry?.isIntersecting ?? false
    syncAnimation()
  })
  resizeObserver.observe(element)
  visibilityObserver.observe(element)
  motion.addEventListener('change', syncAnimation)
  document.addEventListener('visibilitychange', syncAnimation)
  resize()
  syncAnimation()

  dispose = () => {
    cancelAnimationFrame(frame)
    resizeObserver.disconnect()
    visibilityObserver.disconnect()
    motion.removeEventListener('change', syncAnimation)
    document.removeEventListener('visibilitychange', syncAnimation)
  }
})

onUnmounted(() => dispose())
</script>

<template>
  <canvas ref="canvas" class="globe-surface" aria-hidden="true"></canvas>
</template>

<style scoped>
.globe-surface {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  display: block;
}
</style>
