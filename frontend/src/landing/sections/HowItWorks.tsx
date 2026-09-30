import { useRef } from 'react'
import { AnimatePresence, motion, useInView } from 'motion/react'
import { Pill } from '../components/Chrome'
import { DotField, Tilt } from '../components/Effects'
import { DASHBOARD_URL } from '../config'
import { ease, fadeUp, press, stagger, useReduced, useReveal, useTicker } from '../motion'

/** Regions of /public/dashboard.png, in % of the image, toured one at a time. */
const SPOTS = [
  { x: 3, y: 12.4, w: 21.2, h: 14.2, title: 'One score for how AI sees you' },
  { x: 3, y: 28.6, w: 55.5, h: 32.4, title: 'Your rank in every AI assistant' },
  { x: 59.9, y: 28.6, w: 37.1, h: 37.4, title: 'Wrong facts become fixes you approve' },
  { x: 59.9, y: 67.9, w: 37.1, h: 28.4, title: 'Every change logged and re-tested' },
]

const SPOT_MS = 2800

export function HowItWorks({ titleAs: Title = 'h2' }: { titleAs?: 'h1' | 'h2' }) {
  const reduced = useReduced()
  const reveal = useReveal()
  const ref = useRef<HTMLDivElement>(null)
  // The tour only runs while you can see it.
  const inView = useInView(ref, { amount: 0.4 })
  const [active, setActive] = useTicker(SPOTS.length, SPOT_MS, reduced || !inView)
  const spot = SPOTS[active]

  return (
    <section id="how-it-works" className="section">
      <DotField focus="right" />
      <motion.div className="container split split--wide" variants={stagger(0.18, 0.05)} {...reveal}>
        <div className="split__copy">
          <motion.div variants={fadeUp}>
            <Title className="h1">How Confiance works</Title>
          </motion.div>
          <motion.p variants={fadeUp} className="lede lede--left">
            See what AI assistants say about your products, fix what’s wrong, and prove it worked.
          </motion.p>
          <motion.div variants={fadeUp}>
            <motion.a href={DASHBOARD_URL} className="btn btn--primary btn--lg" {...press}>
              Open dashboard <span aria-hidden="true">→</span>
            </motion.a>
          </motion.div>
        </div>

        <motion.figure variants={fadeUp} className="shot" ref={ref}>
          <Tilt>
            <div className="shot__frame">
              <img
                className="shot__img"
                src="/dashboard.png"
                width={1192}
                height={900}
                loading="lazy"
                alt="Dashboard overview with sample data: Trusted Visibility Score 82, rank in each AI assistant, fixes waiting for approval, and an audit log."
              />
              {/* One spotlight that glides between regions; everything else dims. */}
              <motion.span
                layout
                className="shot__spot"
                aria-hidden="true"
                style={{ left: `${spot.x}%`, top: `${spot.y}%`, width: `${spot.w}%`, height: `${spot.h}%` }}
                transition={{ layout: { duration: reduced ? 0 : 0.8, ease } }}
              />
              <span className="shot__demo">
                <Pill>Demo data</Pill>
              </span>
            </div>
          </Tilt>

          <figcaption className="tour" aria-label="What the dashboard shows">
            {SPOTS.map((s, k) => (
              <button
                key={s.title}
                type="button"
                className={`tour__step ${k === active ? 'is-on' : ''}`}
                aria-pressed={k === active}
                onClick={() => setActive(k)}
              >
                <span className="tour__num">{k + 1}</span>
                <span className="tour__title">{s.title}</span>
                <span className="tour__bar" aria-hidden="true">
                  <AnimatePresence initial={false}>
                    {k === active && (
                      <motion.span
                        key={`${active}-${inView}`}
                        className="tour__fill"
                        initial={{ scaleX: reduced || !inView ? 1 : 0 }}
                        animate={{ scaleX: 1 }}
                        exit={{ opacity: 0 }}
                        transition={{ duration: reduced || !inView ? 0 : SPOT_MS / 1000, ease: 'linear' }}
                      />
                    )}
                  </AnimatePresence>
                </span>
              </button>
            ))}
          </figcaption>
        </motion.figure>
      </motion.div>
    </section>
  )
}
