import { useEffect, useState } from 'react'
import { useReducedMotion, type Variants } from 'motion/react'

export const ease = [0.16, 1, 0.3, 1] as const

/** Parent that reveals its `fadeUp` children one after another. */
export const stagger = (gap = 0.18, delay = 0.1): Variants => ({
  hidden: {},
  show: { transition: { staggerChildren: gap, delayChildren: delay } },
})

/** Content rises 28px into place. */
export const fadeUp: Variants = {
  hidden: { opacity: 0, y: 28 },
  show: { opacity: 1, y: 0, transition: { duration: 0.85, ease } },
}

/** True when the visitor asked the OS to reduce motion. */
export function useReduced() {
  return useReducedMotion() ?? false
}

/** Props for a stagger root: skips the entrance entirely under reduced motion. */
export function useEnter() {
  const reduced = useReduced()
  return { initial: reduced ? (false as const) : 'hidden', animate: 'show' }
}

/**
 * Cycles 0..count-1, holding each step for `ms`. Setting the index manually restarts the timer,
 * so a click never gets overridden a moment later.
 */
export function useTicker(count: number, ms: number | readonly number[], paused: boolean, start = 0) {
  const [index, setIndex] = useState(start)
  // `ms` may list a hold time per step, so a key moment can stay on screen longer.
  const hold = typeof ms === 'number' ? ms : ms[index]
  useEffect(() => {
    if (paused) return
    const t = setTimeout(() => setIndex((v) => (v + 1) % count), hold)
    return () => clearTimeout(t)
  }, [index, paused, count, hold])
  return [index, setIndex] as const
}

/** Spring feedback for buttons and links (hover lift, press squish). */
export const press = {
  whileHover: { scale: 1.04 },
  whileTap: { scale: 0.97 },
  transition: { type: 'spring', stiffness: 400, damping: 17 },
} as const

/**
 * Props for a section that reveals its `fadeUp` children as it scrolls into
 * view (once). Under reduced motion it renders in its final state.
 */
export function useReveal(amount = 0.25) {
  const reduced = useReduced()
  return {
    initial: reduced ? (false as const) : 'hidden',
    whileInView: 'show',
    viewport: { once: true, amount },
  }
}
