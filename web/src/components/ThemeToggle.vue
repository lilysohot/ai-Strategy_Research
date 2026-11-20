<script setup lang="ts">
import { computed } from 'vue'

import { useTheme, type ColorTheme } from '@/theme'

const props = withDefaults(defineProps<{ compact?: boolean; iconOnly?: boolean }>(), {
  compact: false,
  iconOnly: false,
})

const { theme, setTheme } = useTheme()

const targetTheme = computed<ColorTheme>(() => (theme.value === 'dark' ? 'light' : 'dark'))
const targetLabel = computed(() => (targetTheme.value === 'light' ? '切换到白天模式' : '切换到晚上模式'))

function selectTheme(next: ColorTheme): void {
  if (theme.value !== next) setTheme(next)
}
</script>

<template>
  <button
    v-if="props.iconOnly"
    type="button"
    class="theme-toggle-icon"
    :aria-label="targetLabel"
    :title="targetLabel"
    @click="selectTheme(targetTheme)"
  >
    <svg v-if="targetTheme === 'light'" viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="3.5" />
      <path d="M12 2.5V5M12 19v2.5M4.6 4.6l1.8 1.8M17.6 17.6l1.8 1.8M2.5 12H5M19 12h2.5M4.6 19.4l1.8-1.8M17.6 6.4l1.8-1.8" />
    </svg>
    <svg v-else viewBox="0 0 24 24" aria-hidden="true">
      <path d="M20 15.1A8 8 0 0 1 8.9 4 8 8 0 1 0 20 15.1Z" />
    </svg>
  </button>
  <div v-else class="theme-toggle" :class="{ 'theme-toggle--compact': compact }" role="group" aria-label="外观主题">
    <button
      type="button"
      :aria-pressed="theme === 'light'"
      :aria-label="compact ? '切换到白天模式' : undefined"
      title="白天模式"
      @click="selectTheme('light')"
    >
      {{ compact ? '昼' : '白天' }}
    </button>
    <button
      type="button"
      :aria-pressed="theme === 'dark'"
      :aria-label="compact ? '切换到晚上模式' : undefined"
      title="晚上模式"
      @click="selectTheme('dark')"
    >
      {{ compact ? '夜' : '晚上' }}
    </button>
  </div>
</template>

<style scoped>
.theme-toggle-icon {
  display: grid;
  flex: 0 0 44px;
  width: 44px;
  height: 44px;
  place-items: center;
  padding: 0;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--bg-raised);
  color: var(--muted);
  cursor: pointer;
  transition: background-color 160ms ease, border-color 160ms ease, color 160ms ease;
}

.theme-toggle-icon:hover {
  border-color: color-mix(in srgb, var(--accent) 42%, var(--line));
  background: var(--surface-hover);
  color: var(--text);
}

.theme-toggle-icon:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--accent) 72%, transparent);
  outline-offset: 2px;
}

.theme-toggle-icon svg {
  width: 19px;
  height: 19px;
  fill: none;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 1.7;
}

.theme-toggle {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  min-width: 132px;
  padding: 3px;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: color-mix(in srgb, var(--bg-input) 82%, transparent);
}

.theme-toggle button {
  min-width: 0;
  min-height: 44px;
  padding: 0 10px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  font: inherit;
  font-size: 12px;
  letter-spacing: .04em;
  transition: background-color 160ms ease, color 160ms ease, box-shadow 160ms ease;
}

.theme-toggle button:hover {
  color: var(--text);
}

.theme-toggle button[aria-pressed='true'] {
  background: var(--bg-elevated);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent) 32%, var(--line));
  color: var(--text);
  font-weight: 700;
}

.theme-toggle--compact {
  min-width: 82px;
}

.theme-toggle--compact button {
  min-height: 44px;
  padding-inline: 8px;
  font-size: 11px;
}

@media (prefers-reduced-motion: reduce) {
  .theme-toggle-icon,
  .theme-toggle button {
    transition: none;
  }
}
</style>
