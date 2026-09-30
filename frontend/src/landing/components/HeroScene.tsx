import { useEffect, useRef, useState } from 'react'
import {
  animate,
  motion,
  useInView,
  useMotionValue,
  useMotionValueEvent,
  useScroll,
  useSpring,
  useTransform,
  type MotionValue,
} from 'motion/react'
import { HERO_IMAGE } from '../config'
import { applyTheme, registerSky, useTheme } from '../theme'
import { ease, useReduced } from '../motion'

/*
 * Painted scene behind the Home hero, driven by the theme toggle.
 * Dark (default): night sky, the rocket climbs and hovers in the top-right
 * ("rise to the top of AI answers"). Switch to light: the rocket blasts out
 * of the corner, the sun pops up and the sky warms into golden hour. Switch
 * back: the sun drops, night returns and the rocket launches again.
 * Layers shift with the mouse for depth. Set HERO_IMAGE in config.ts to use
 * your own illustration instead.
 */

// Rocket flight in the 1440×900 scene space: from the hills, out past the top-right corner.
const FLIGHT = 'M 600 930 C 850 820, 1010 660, 1080 480 S 1230 120, 1540 -170'
const SETTLE = 0.64 // where the rocket hovers at night
// Where the sun rises (just inside the visible top-right corner).
const SUN = { x: 1175, y: 215 }
const DAWN_S = 2.6

/** Offset a layer by the shared pointer position, scaled by its depth. */
function useDepth(px: MotionValue<number>, py: MotionValue<number>, depth: number) {
  return {
    x: useTransform(px, (v) => v * depth),
    y: useTransform(py, (v) => v * depth),
  }
}

function Stars({ play }: { play: boolean }) {
  const ref = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = ref.current
    const ctx = canvas?.getContext('2d')
    if (!canvas || !ctx) return

    let seed = 7
    const rand = () => ((seed = (seed * 16807) % 2147483647) - 1) / 2147483646
    let stars: { x: number; y: number; r: number; a: number; p: number; s: number }[] = []
    let frame = 0

    const size = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      canvas.width = canvas.clientWidth * dpr
      canvas.height = canvas.clientHeight * dpr
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      seed = 7
      const n = Math.round((canvas.clientWidth * canvas.clientHeight) / 3800)
      stars = Array.from({ length: n }, () => {
        const y = Math.pow(rand(), 1.6) * canvas.clientHeight * 0.8 // denser toward the top
        return { x: rand() * canvas.clientWidth, y, r: 0.3 + Math.pow(rand(), 3) * 1.6, a: 0.35 + rand() * 0.65, p: rand() * 6.28, s: 0.6 + rand() * 1.8 }
      })
    }

    const draw = (t: number) => {
      ctx.clearRect(0, 0, canvas.clientWidth, canvas.clientHeight)
      for (const s of stars) {
        const tw = play ? 0.65 + 0.35 * Math.sin(t / 1000 * s.s + s.p) : 1
        ctx.globalAlpha = s.a * tw
        ctx.fillStyle = '#fff6e8'
        ctx.beginPath()
        ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2)
        ctx.fill()
        if (s.r > 1.35) {
          // The few bright stars get a soft halo.
          ctx.globalAlpha = s.a * tw * 0.18
          ctx.beginPath()
          ctx.arc(s.x, s.y, s.r * 4, 0, Math.PI * 2)
          ctx.fill()
        }
      }
      if (play) frame = requestAnimationFrame(draw)
    }

    size()
    frame = requestAnimationFrame(draw)
    window.addEventListener('resize', size)
    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('resize', size)
    }
  }, [play])

  return <canvas ref={ref} className="scene__stars" />
}

function Rocket({
  mode,
  reduced,
  dawn,
  onGone,
}: {
  mode: 'night' | 'day'
  reduced: boolean
  dawn: boolean
  onGone: () => void
}) {
  const pathRef = useRef<SVGPathElement>(null)
  const progress = useMotionValue(mode === 'day' ? 1 : 0)
  const hx = useMotionValue(0)
  const hy = useMotionValue(0)
  const angle = useMotionValue(0)

  const place = (p: number) => {
    const path = pathRef.current
    if (!path) return
    const len = path.getTotalLength()
    const a = path.getPointAtLength(p * len)
    const b = path.getPointAtLength(Math.min(len, p * len + 2))
    hx.set(a.x)
    hy.set(a.y)
    angle.set((Math.atan2(b.y - a.y, b.x - a.x) * 180) / Math.PI + 90)
  }
  useMotionValueEvent(progress, 'change', place)

  useEffect(() => {
    let live = true
    const at = progress.get()
    place(at)

    if (reduced) {
      progress.set(mode === 'day' ? 1 : SETTLE)
      if (mode === 'day') onGone()
      return
    }

    if (mode === 'day') {
      // Already gone (page opened in light): just bring the sun up.
      if (at >= 1) {
        const t = setTimeout(() => live && onGone(), 300)
        return () => {
          live = false
          clearTimeout(t)
        }
      }
      // Blast off: accelerate out through the top-right corner.
      const c = animate(progress, 1, { duration: 1.8, ease: [0.55, 0, 0.9, 0.55] })
      c.then(() => live && onGone())
      return () => {
        live = false
        c.stop()
      }
    }

    // Night: (re)launch from the hills and settle into a hover.
    const relaunch = at > SETTLE + 0.001
    if (relaunch) progress.jump(0)
    const c = animate(progress, SETTLE, { duration: 3.4, ease: [0.3, 0.1, 0.2, 1], delay: relaunch ? 0.9 : 0.5 })
    return () => {
      live = false
      c.stop()
    }
    // Reacts to the toggle only; onGone just flips a flag.
  }, [mode, reduced]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <defs>
        <linearGradient id="trail-fade" gradientUnits="userSpaceOnUse" x1="600" y1="930" x2="1540" y2="-170">
          <stop offset="0" stopColor="#f3c89a" stopOpacity="0" />
          <stop offset="0.35" stopColor="#f3c89a" stopOpacity="0.55" />
          <stop offset="0.62" stopColor="#fff1dc" stopOpacity="0.95" />
        </linearGradient>
        <filter id="trail-blur" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="18" />
        </filter>
        <radialGradient id="flame" cx="0.5" cy="0.2" r="0.8">
          <stop offset="0" stopColor="#fff4d6" />
          <stop offset="0.45" stopColor="#ffb25c" />
          <stop offset="1" stopColor="#ff6a3d" stopOpacity="0" />
        </radialGradient>
      </defs>

      <path ref={pathRef} d={FLIGHT} fill="none" stroke="none" />
      {/* Smoke plume, then a bright core, both drawn as the rocket climbs; they thin out at dawn. */}
      <motion.g animate={{ opacity: dawn ? 0.22 : 1 }} transition={{ duration: reduced ? 0 : DAWN_S + 1 }}>
        <motion.path d={FLIGHT} fill="none" stroke="url(#trail-fade)" strokeWidth="90" strokeLinecap="round" filter="url(#trail-blur)" style={{ pathLength: progress }} opacity={0.9} />
        <motion.path d={FLIGHT} fill="none" stroke="url(#trail-fade)" strokeWidth="7" strokeLinecap="round" style={{ pathLength: progress }} />
      </motion.g>

      <motion.g style={{ x: hx, y: hy, rotate: angle }}>
        <motion.ellipse
          cx="0"
          cy="30"
          rx="9"
          ry="22"
          fill="url(#flame)"
          animate={reduced ? undefined : { scaleY: [1, 1.25, 0.9, 1.15, 1] }}
          transition={{ duration: 0.6, repeat: Infinity, ease: 'easeInOut' }}
          style={{ originY: 0 }}
        />
        <path d="M0 -30 C 9 -20 10 -4 9 14 L -9 14 C -10 -4 -9 -20 0 -30 Z" fill="#f1ebe0" />
        <path d="M-9 4 L-17 20 L-9 16 Z M9 4 L17 20 L9 16 Z" fill="#c41e3a" />
        <circle cx="0" cy="-8" r="3.6" fill="#1d2645" stroke="#c9c2b6" strokeWidth="1.2" />
      </motion.g>
    </>
  )
}

/** The sun that pops up in the top-right corner once the rocket has gone. */
function Sun({ dawn, reduced }: { dawn: boolean; reduced: boolean }) {
  const rays = Array.from({ length: 12 }, (_, k) => (k * 360) / 12)
  return (
    <>
      <defs>
        <radialGradient id="sun-core">
          <stop offset="0" stopColor="#fffaf0" />
          <stop offset="0.5" stopColor="#ffe29a" />
          <stop offset="1" stopColor="#ffb347" />
        </radialGradient>
        <radialGradient id="sun-glow">
          <stop offset="0" stopColor="#ffd98c" stopOpacity="0.75" />
          <stop offset="0.35" stopColor="#ffc070" stopOpacity="0.3" />
          <stop offset="1" stopColor="#ffb060" stopOpacity="0" />
        </radialGradient>
      </defs>
      <motion.g
        initial={false}
        animate={dawn ? { scale: 1, opacity: 1 } : { scale: 0, opacity: 0 }}
        transition={
          reduced
            ? { duration: 0 }
            : dawn
              ? { type: 'spring', stiffness: 110, damping: 11 }
              : { duration: 0.6, ease: 'easeIn' }
        }
      >
        <circle cx={SUN.x} cy={SUN.y} r="300" fill="url(#sun-glow)" />
        <motion.g
          animate={reduced ? undefined : { rotate: 360 }}
          transition={{ duration: 60, repeat: Infinity, ease: 'linear' }}
        >
          {rays.map((deg) => {
            const r = (deg * Math.PI) / 180
            return (
              <line
                key={deg}
                x1={SUN.x + Math.cos(r) * 66}
                y1={SUN.y + Math.sin(r) * 66}
                x2={SUN.x + Math.cos(r) * 94}
                y2={SUN.y + Math.sin(r) * 94}
                stroke="#ffe0a0"
                strokeOpacity="0.7"
                strokeWidth="4"
                strokeLinecap="round"
              />
            )
          })}
        </motion.g>
        <circle cx={SUN.x} cy={SUN.y} r="48" fill="url(#sun-core)" />
      </motion.g>
    </>
  )
}

export function HeroScene() {
  const reduced = useReduced()
  const ref = useRef<HTMLDivElement>(null)
  const visible = useInView(ref)
  // The theme toggle drives the sky: light means the sun comes up once the
  // rocket has left; dark means night, straight away.
  const { wanted } = useTheme()
  const day = wanted === 'light'
  const [dawn, setDawn] = useState(false)
  useEffect(() => {
    if (!day) setDawn(false)
  }, [day])

  // While the sky is on screen it owns the switch to daylight: the rest of
  // the page turns sunny only once the sun is fully up.
  useEffect(() => {
    if (!visible || reduced) return
    return registerSky()
  }, [visible, reduced])
  useEffect(() => {
    if (!dawn || !day) return
    const t = setTimeout(() => applyTheme('light'), reduced ? 0 : DAWN_S * 1000)
    return () => clearTimeout(t)
  }, [dawn, day, reduced])
  const fadeDawn = { duration: reduced ? 0 : DAWN_S, ease: 'easeInOut' as const }

  // Shared pointer position, -1..1 across the hero, smoothed.
  const rawX = useMotionValue(0)
  const rawY = useMotionValue(0)
  const px = useSpring(rawX, { stiffness: 60, damping: 20 })
  const py = useSpring(rawY, { stiffness: 60, damping: 20 })

  useEffect(() => {
    const host = ref.current?.parentElement
    if (reduced || !host) return
    const move = (e: PointerEvent) => {
      if (e.pointerType !== 'mouse') return
      const r = host.getBoundingClientRect()
      rawX.set(((e.clientX - r.left) / r.width) * 2 - 1)
      rawY.set(((e.clientY - r.top) / r.height) * 2 - 1)
    }
    const leave = () => {
      rawX.set(0)
      rawY.set(0)
    }
    host.addEventListener('pointermove', move)
    host.addEventListener('pointerleave', leave)
    return () => {
      host.removeEventListener('pointermove', move)
      host.removeEventListener('pointerleave', leave)
    }
  }, [reduced, rawX, rawY])

  // The whole scene drifts slower than the page as you scroll away.
  const { scrollY } = useScroll()
  const drift = useTransform(scrollY, [0, 900], [0, reduced ? 0 : 160])

  const stars = useDepth(px, py, -6)
  const galaxy = useDepth(px, py, -10)
  const far = useDepth(px, py, -8)
  const mid = useDepth(px, py, -14)
  const near = useDepth(px, py, -22)
  const flight = useDepth(px, py, -16)
  const sun = useDepth(px, py, -5)

  if (HERO_IMAGE) {
    return (
      <div ref={ref} className="scene" aria-hidden="true">
        <motion.img className="scene__image" src={HERO_IMAGE} alt="" style={{ y: drift }} />
        <div className="scene__shade" />
      </div>
    )
  }

  return (
    <div ref={ref} className={`scene ${dawn ? 'is-dawn' : ''}`} aria-hidden="true">
      <motion.div className="scene__world" style={{ y: drift }}>
        <div className="scene__sky" />
        <motion.div
          className="scene__sky scene__sky--dawn"
          initial={false}
          animate={{ opacity: dawn ? 1 : 0 }}
          transition={fadeDawn}
        />
        <motion.div className="scene__layer" style={stars}>
          <motion.div
            className="scene__layer"
            initial={false}
            animate={{ opacity: dawn ? 0 : 1 }}
            transition={fadeDawn}
          >
            <Stars play={!reduced && visible && !dawn} />
          </motion.div>
        </motion.div>
        <motion.svg className="scene__layer" viewBox="0 0 1440 900" preserveAspectRatio="xMidYMax slice" style={sun}>
          <Sun dawn={dawn} reduced={reduced} />
        </motion.svg>
        <motion.div className="scene__galaxy" style={galaxy} />
        <motion.div className="scene__clouds" style={far}>
          <span className="cloud cloud--a" />
          <span className="cloud cloud--b" />
          <span className="cloud cloud--c" />
          <span className="cloud cloud--d" />
        </motion.div>

        <motion.svg className="scene__layer" viewBox="0 0 1440 900" preserveAspectRatio="xMidYMax slice" style={far}>
          <motion.path d="M-60 700 C 180 630 360 660 560 690 S 900 610 1120 640 S 1400 600 1520 620 L1520 960 L-60 960 Z" initial={false} animate={{ fill: dawn ? '#9c4f4f' : '#3a2a2e' }} transition={fadeDawn} />
          <path d="M-60 700 C 180 630 360 660 560 690 S 900 610 1120 640 S 1400 600 1520 620" fill="none" stroke="#f2a878" strokeOpacity="0.55" strokeWidth="2.5" />
        </motion.svg>

        <motion.svg className="scene__layer" viewBox="0 0 1440 900" preserveAspectRatio="xMidYMax slice" style={flight}>
          <Rocket mode={day ? 'day' : 'night'} reduced={reduced} dawn={dawn} onGone={() => setDawn(true)} />
        </motion.svg>

        <motion.svg className="scene__layer" viewBox="0 0 1440 900" preserveAspectRatio="xMidYMax slice" style={mid}>
          <motion.path d="M-60 780 C 220 720 420 760 700 770 S 1100 720 1520 760 L1520 960 L-60 960 Z" initial={false} animate={{ fill: dawn ? '#6e3444' : '#211a1e' }} transition={fadeDawn} />
          <path d="M-60 780 C 220 720 420 760 700 770 S 1100 720 1520 760" fill="none" stroke="#f5b886" strokeOpacity="0.4" strokeWidth="2" />
        </motion.svg>

        <motion.svg className="scene__layer" viewBox="0 0 1440 900" preserveAspectRatio="xMidYMax slice" style={near}>
          <motion.path d="M-80 850 C 260 800 520 830 820 845 S 1250 810 1540 830 L1540 980 L-80 980 Z" initial={false} animate={{ fill: dawn ? '#e6a878' : '#121013' }} transition={fadeDawn} />
        </motion.svg>
      </motion.div>
      <div className="scene__shade scene__shade--night" />
      <div className="scene__shade scene__shade--dawn" />
      {!reduced && (
        <motion.div
          className="scene__veil"
          initial={{ opacity: 1 }}
          animate={{ opacity: 0 }}
          transition={{ duration: 1.4, ease }}
        />
      )}
    </div>
  )
}
