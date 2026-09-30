import { useEffect, useRef, type ReactNode } from 'react'
import {
  animate,
  motion,
  useMotionTemplate,
  useMotionValue,
  useScroll,
  useSpring,
  useTransform,
  type MotionValue,
} from 'motion/react'
import { useReduced } from '../motion'

/**
 * Dot-grid backdrop for a section (Aceternity-style). Dots fade out where the
 * content sits, so the clear area pulls the eye there; under a mouse, a patch
 * of dots lights up in logo red and trails the cursor.
 */
export function DotField({ focus = 'center' }: { focus?: 'center' | 'right' }) {
  const reduced = useReduced()
  const ref = useRef<HTMLDivElement>(null)
  const x = useMotionValue(0)
  const y = useMotionValue(0)
  const glow = useMotionValue(0)
  const sx = useSpring(x, { stiffness: 260, damping: 32 })
  const sy = useSpring(y, { stiffness: 260, damping: 32 })
  const mask = useMotionTemplate`radial-gradient(220px circle at ${sx}px ${sy}px, #000 0%, transparent 72%)`

  useEffect(() => {
    const host = ref.current?.parentElement
    if (reduced || !host) return
    const move = (e: PointerEvent) => {
      if (e.pointerType !== 'mouse') return
      const r = host.getBoundingClientRect()
      x.set(e.clientX - r.left)
      y.set(e.clientY - r.top)
      if (glow.get() === 0) animate(glow, 1, { duration: 0.4 })
    }
    const leave = () => animate(glow, 0, { duration: 0.5 })
    host.addEventListener('pointermove', move)
    host.addEventListener('pointerleave', leave)
    return () => {
      host.removeEventListener('pointermove', move)
      host.removeEventListener('pointerleave', leave)
    }
  }, [reduced, x, y, glow])

  return (
    <div ref={ref} className={`dotfield dotfield--${focus}`} aria-hidden="true">
      <div className="dotfield__base" />
      {!reduced && (
        <motion.div className="dotfield__glow" style={{ maskImage: mask, WebkitMaskImage: mask, opacity: glow }} />
      )}
    </div>
  )
}

const tiltSpring = { stiffness: 150, damping: 20 }

/**
 * 3D card (Aceternity "container scroll"): starts tilted back and swings
 * upright as it scrolls into view, then leans gently toward the mouse.
 */
export function Tilt({ children, className = '' }: { children: ReactNode; className?: string }) {
  const reduced = useReduced()
  const ref = useRef<HTMLDivElement>(null)
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start end', 'start 40%'] })
  const scrollTilt = useSpring(useTransform(scrollYProgress, [0, 1], [26, 0]), { stiffness: 120, damping: 30 })
  const scale = useSpring(useTransform(scrollYProgress, [0, 1], [0.9, 1]), { stiffness: 120, damping: 30 })

  // Pointer position across the card, -0.5..0.5.
  const px = useMotionValue(0)
  const py = useMotionValue(0)
  const leanX = useSpring(useTransform(py, [-0.5, 0.5], [5, -5]), tiltSpring)
  const leanY = useSpring(useTransform(px, [-0.5, 0.5], [-7, 7]), tiltSpring)
  const rotateX = useTransform([scrollTilt, leanX] as MotionValue<number>[], ([a, b]: number[]) => a + b)

  return (
    <div ref={ref} className={`tilt ${className}`}>
      <motion.div
        className="tilt__card"
        style={reduced ? undefined : { rotateX, rotateY: leanY, scale }}
        onPointerMove={(e) => {
          if (reduced || e.pointerType !== 'mouse') return
          const r = e.currentTarget.getBoundingClientRect()
          px.set((e.clientX - r.left) / r.width - 0.5)
          py.set((e.clientY - r.top) / r.height - 0.5)
        }}
        onPointerLeave={() => {
          px.set(0)
          py.set(0)
        }}
      >
        {children}
      </motion.div>
    </div>
  )
}
