import { useEffect } from 'react'
import { animate, motion, useMotionValue, useSpring } from 'motion/react'
import { useReduced } from '../motion'

const spring = { stiffness: 170, damping: 18, mass: 0.6 }

/**
 * The pulsing red dot. It trails the mouse anywhere on the site; when the
 * mouse is away (or on touch screens) it rests on the element marked
 * `data-cursor-home` (the spot above the Home headline), or fades out on
 * pages without one.
 */
export function CursorDot() {
  const reduced = useReduced()
  const tx = useMotionValue(0)
  const ty = useMotionValue(0)
  const x = useSpring(tx, spring)
  const y = useSpring(ty, spring)
  const opacity = useMotionValue(0)

  useEffect(() => {
    if (reduced) return
    let tracking = false
    let placed = false
    let frame = 0

    const show = (on: boolean) => {
      const to = on ? 1 : 0
      if (opacity.get() !== to) animate(opacity, to, { duration: 0.3 })
    }
    const moveTo = (px: number, py: number) => {
      tx.set(px)
      ty.set(py)
      if (!placed) {
        // First placement: appear in place rather than flying in from a corner.
        x.jump(px)
        y.jump(py)
        placed = true
      }
      show(true)
    }

    // While the mouse is away, follow the home spot through scrolling,
    // entrance animations and page changes.
    const rest = () => {
      if (!tracking) {
        const home = document.querySelector('[data-cursor-home]')
        if (home) {
          const r = home.getBoundingClientRect()
          moveTo(r.left + r.width / 2, r.top + r.height / 2)
        } else {
          show(false)
        }
      }
      frame = requestAnimationFrame(rest)
    }

    const move = (e: PointerEvent) => {
      if (e.pointerType !== 'mouse') return
      tracking = true
      moveTo(e.clientX, e.clientY)
    }
    const leave = (e: MouseEvent) => {
      if (!e.relatedTarget) tracking = false // left the window
    }

    frame = requestAnimationFrame(rest)
    window.addEventListener('pointermove', move)
    document.addEventListener('mouseout', leave)
    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('pointermove', move)
      document.removeEventListener('mouseout', leave)
    }
  }, [reduced, tx, ty, x, y, opacity])

  if (reduced) return null

  return (
    <motion.div className="cursor-dot" style={{ x, y, opacity }} aria-hidden="true">
      <motion.span
        className="pulse__ring"
        animate={{ scale: [1, 3.2], opacity: [0.5, 0] }}
        transition={{ duration: 2.2, repeat: Infinity, ease: 'easeOut' }}
      />
      <span className="pulse__dot" />
    </motion.div>
  )
}
