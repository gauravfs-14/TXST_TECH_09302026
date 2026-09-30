import { useSyncExternalStore } from 'react'

export type Theme = 'light' | 'dark'

// v2: dark (the night sky with the rocket) is now the default for everyone.
const THEME_KEY = 'confiance-theme-v2'

/*
 * Two values:
 * - `theme`: what the page is painted in (<html data-theme>).
 * - `wanted`: what the toggle is set to.
 * They differ only briefly on Home: switching to light, the toggle flips at
 * once, the sky plays its sunrise, and the page turns sunny once the sun is
 * fully up (the hero calls applyTheme then).
 */

function read(): Theme {
  return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark'
}

let wanted: Theme = typeof document === 'undefined' ? 'dark' : read()
const listeners = new Set<() => void>()
const notify = () => listeners.forEach((l) => l())

function subscribe(onChange: () => void) {
  listeners.add(onChange)
  const mo = new MutationObserver(onChange)
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
  return () => {
    listeners.delete(onChange)
    mo.disconnect()
  }
}

/** Paint the page in `theme` and remember it for next visit. */
export function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme
  try {
    localStorage.setItem(THEME_KEY, theme)
  } catch {
    // Storage can be blocked (private mode); the toggle still works for this visit.
  }
}

// Set while the Home sky is on screen: it applies "light" itself after sunrise.
let skyActive = 0

/** The hero registers while visible; returns an unregister function. */
export function registerSky() {
  skyActive += 1
  return () => {
    skyActive -= 1
  }
}

export function useTheme() {
  const theme = useSyncExternalStore(subscribe, read, (): Theme => 'dark')
  const want = useSyncExternalStore(subscribe, () => wanted, (): Theme => 'dark')

  const toggle = () => {
    wanted = wanted === 'dark' ? 'light' : 'dark'
    notify()
    // Night comes in at once; daylight waits for the sunrise when the sky is on screen.
    if (wanted === 'dark' || skyActive === 0) applyTheme(wanted)
  }

  return { theme, wanted: want, toggle }
}
