import { computed, readonly, ref } from 'vue'

export type ColorTheme = 'dark' | 'light'

const STORAGE_KEY = 'frontier-agent:color-theme'
const activeTheme = ref<ColorTheme>('dark')
let initialized = false

export function resolveStoredTheme(value: string | null): ColorTheme {
  return value === 'light' ? 'light' : 'dark'
}

function applyTheme(theme: ColorTheme): void {
  document.documentElement.dataset.theme = theme
  document.documentElement.style.colorScheme = theme
}

export function initializeTheme(): void {
  if (initialized) return

  let stored: string | null = null
  try {
    stored = window.localStorage.getItem(STORAGE_KEY)
  } catch {
    // Storage can be unavailable in private or locked-down browsing contexts.
  }

  activeTheme.value = resolveStoredTheme(stored)
  applyTheme(activeTheme.value)
  initialized = true
}

export function setColorTheme(theme: ColorTheme): void {
  initializeTheme()
  activeTheme.value = theme
  applyTheme(theme)

  try {
    window.localStorage.setItem(STORAGE_KEY, theme)
  } catch {
    // The current page still switches even when persistence is unavailable.
  }
}

export function useTheme() {
  initializeTheme()

  return {
    theme: readonly(activeTheme),
    isLight: computed(() => activeTheme.value === 'light'),
    setTheme: setColorTheme,
  }
}
