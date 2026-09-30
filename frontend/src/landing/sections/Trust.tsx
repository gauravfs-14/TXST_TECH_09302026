import { useRef } from 'react'
import { AnimatePresence, motion, useInView } from 'motion/react'
import { DotField } from '../components/Effects'
import { ChatIcon, CubeIcon, LockIcon, PersonIcon, RefreshIcon, SearchIcon, WrenchIcon } from '../components/Icons'
import { ease, fadeUp, stagger, useReduced, useReveal, useTicker } from '../motion'

const CHIPS = [
  { icon: CubeIcon, text: 'Isolated container per client' },
  { icon: LockIcon, text: 'No shopper personal or payment data' },
  { icon: PersonIcon, text: 'You approve what matters' },
]

const STEPS = [
  { name: 'ASK', line: 'Shopper agents question AI', icon: ChatIcon },
  { name: 'CHECK', line: 'Every claim vs. your facts', icon: SearchIcon },
  { name: 'FIX', line: 'Agents draft the change', icon: WrenchIcon },
  { name: 'APPROVE', line: 'You sign off on what matters', icon: PersonIcon },
  { name: 'RE-TEST', line: 'Prove it, watch for drift', icon: RefreshIcon },
]
const APPROVE = 3
const CHIP_FOR_APPROVE = 2

const SIZE = 520
const R = 208
const NODE = 92

function Loop({
  reduced,
  active,
  setActive,
}: {
  reduced: boolean
  active: number
  setActive: (k: number) => void
}) {
  const Icon = STEPS[active].icon

  return (
    <div className="loop" style={{ width: SIZE, height: SIZE }}>
      <motion.svg
        className="loop__ring"
        width={SIZE}
        height={SIZE}
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        aria-hidden="true"
        animate={reduced ? undefined : { rotate: 360 }}
        transition={{ duration: 40, repeat: Infinity, ease: 'linear' }}
      >
        <circle className="loop__dash" cx={SIZE / 2} cy={SIZE / 2} r={R} fill="none" strokeWidth="2" strokeDasharray="6 10" />
      </motion.svg>

      {/* Progress arc: fills clockwise from ASK to the active step, then resets. */}
      <svg className="loop__progress" width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`} aria-hidden="true">
        <motion.circle
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={R}
          fill="none"
          className="loop__arc"
          strokeWidth="3"
          strokeLinecap="round"
          initial={false}
          animate={{ pathLength: active / STEPS.length, opacity: active === 0 ? 0 : 1 }}
          transition={{ duration: reduced ? 0 : 0.9, ease }}
        />
      </svg>

      <div className="loop__center">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={active}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -12 }}
            transition={{ duration: reduced ? 0 : 0.45, ease }}
          >
            <span className={`loop__icon ${active === APPROVE ? 'is-human' : ''}`}>
              <Icon size={22} />
            </span>
            <span className={`loop__step ${active === APPROVE ? 'is-human' : ''}`}>Step {active + 1}</span>
            <p className="loop__line">{STEPS[active].line}</p>
          </motion.div>
        </AnimatePresence>
      </div>

      {STEPS.map((st, k) => {
        const angle = (-90 + k * (360 / STEPS.length)) * (Math.PI / 180)
        const on = k === active
        return (
          <motion.button
            key={st.name}
            type="button"
            className={`loop__node ${on ? 'is-on' : ''} ${k === APPROVE ? 'is-human' : ''}`}
            style={{
              left: SIZE / 2 + R * Math.cos(angle) - NODE / 2,
              top: SIZE / 2 + R * Math.sin(angle) - NODE / 2,
              width: NODE,
              height: NODE,
            }}
            aria-pressed={on}
            aria-label={`Step ${k + 1}, ${st.name}: ${st.line}`}
            onClick={() => setActive(k)}
            animate={{ scale: on ? 1.14 : 1 }}
            transition={{ duration: reduced ? 0 : 0.5, ease }}
          >
            {st.name}
          </motion.button>
        )
      })}
    </div>
  )
}

export function Trust() {
  const reveal = useReveal()
  const reduced = useReduced()
  const ref = useRef<HTMLDivElement>(null)
  // The loop only runs while you can see it.
  const inView = useInView(ref, { amount: 0.4 })
  const [active, setActive] = useTicker(STEPS.length, 2200, reduced || !inView)

  return (
    <section id="trust" className="section">
      <DotField focus="right" />
      <motion.div className="container split" variants={stagger(0.2, 0.05)} {...reveal}>
        <div className="split__copy">
          <motion.h2 variants={fadeUp} className="h1">
            Private. Accurate. Always improving.
          </motion.h2>
          <motion.p variants={fadeUp} className="lede lede--left">
            Your data stays separate, shopper data is never touched, and nothing important changes without your
            approval.
          </motion.p>
          <motion.ul className="chips" variants={stagger(0.2, 0.05)}>
            {CHIPS.map(({ icon: I, text }, k) => (
              <motion.li
                key={text}
                variants={fadeUp}
                className={`chip ${k === CHIP_FOR_APPROVE && active === APPROVE ? 'is-live' : ''}`}
              >
                <span className="chip__icon">
                  <I size={22} />
                </span>
                {text}
              </motion.li>
            ))}
          </motion.ul>
        </div>

        <motion.figure variants={fadeUp} className="loop-wrap" ref={ref}>
          <Loop reduced={reduced} active={active} setActive={setActive} />
          <figcaption className="loop-wrap__cap">
            The agentic GEO loop runs on its own, and pauses for you when it matters.
          </figcaption>
        </motion.figure>
      </motion.div>
    </section>
  )
}
