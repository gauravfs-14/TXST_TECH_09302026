import { useEffect, useId, useRef, useState } from 'react'
import { AnimatePresence, animate, motion, useInView, useMotionValue, useTransform } from 'motion/react'
import { Page } from '../components/Chrome'
import { DotField } from '../components/Effects'
import { CheckIcon, ChevronDownIcon } from '../components/Icons'
import { ease, fadeUp, stagger, useEnter, useReduced } from '../motion'

const PLANS = [
  {
    name: 'Local',
    blurb: 'For local and small businesses.',
    price: 99,
    from: false,
    rows: [
      ['Products covered', 'Up to 10'],
      ['AI assistants', '2'],
      ['Optimization loops', '4 full + unlimited minor'],
      ['Human approval', 'Business owner'],
    ],
  },
  {
    name: 'Growth',
    blurb: 'For growing catalogs.',
    price: 499,
    from: false,
    rows: [
      ['Products covered', 'Up to 25'],
      ['AI assistants', '4'],
      ['Optimization loops', '6 full + unlimited minor'],
      ['Human approval', 'Escalation review'],
    ],
  },
  {
    name: 'Enterprise',
    blurb: 'For large brands and catalogs.',
    price: 10000,
    from: true,
    rows: [
      ['Products covered', 'Custom'],
      ['AI assistants', '6+'],
      ['Optimization loops', 'Custom'],
      ['Human approval', 'Dedicated reviewer + audit logs'],
    ],
  },
]

const INCLUDED = [
  'Tracks your company and its products across AI assistants',
  'Checks every AI answer for accuracy',
  'Human approval before any change goes live',
]

/** Price that counts up from zero the first time it scrolls into view. */
function Price({ value }: { value: number }) {
  const reduced = useReduced()
  const ref = useRef<HTMLSpanElement>(null)
  const inView = useInView(ref, { once: true })
  const mv = useMotionValue(reduced ? value : 0)
  const text = useTransform(mv, (v) => `$${Math.round(v).toLocaleString('en-US')}`)
  useEffect(() => {
    if (!inView || reduced) return
    const c = animate(mv, value, { duration: 1.1, ease, delay: 0.35 })
    return c.stop
  }, [inView, reduced, value, mv])
  return (
    <motion.span ref={ref} aria-label={`$${value.toLocaleString('en-US')}`}>
      {text}
    </motion.span>
  )
}

const PRODUCTS = 8
const CHANGED = 5 // the one product a minor loop touches

/**
 * Full loop: a highlight sweeps across every product. Minor loop: only the
 * product that changed (say, a new price) is fixed.
 */
function LoopDemo({ kind }: { kind: 'full' | 'minor' }) {
  const reduced = useReduced()
  return (
    <div className="loopdemo" aria-hidden="true">
      {Array.from({ length: PRODUCTS }, (_, k) => {
        const touched = kind === 'full' || k === CHANGED
        return (
          <motion.span
            key={k}
            className={`loopdemo__item ${touched ? 'is-touched' : ''}`}
            animate={
              reduced || !touched
                ? undefined
                : { scale: [1, 1.25, 1], backgroundColor: ['var(--card-2)', 'var(--accent)', 'var(--accent-soft)'] }
            }
            transition={{
              duration: 0.7,
              ease: 'easeInOut',
              delay: kind === 'full' ? k * 0.18 : 0.6,
              repeat: Infinity,
              // Same period for every square so the sweep stays in step: sweep, then a pause.
              repeatDelay: kind === 'full' ? PRODUCTS * 0.18 + 1.6 - 0.7 : 2.8,
            }}
          />
        )
      })}
    </div>
  )
}

const LOOPS = {
  full: {
    title: 'Full loop',
    summary: 'Reviews and updates all of your products.',
    steps: [
      'Shopper agents ask AI assistants about every one of your products.',
      'Every claim in their answers is checked against your verified facts.',
      'Agents draft fixes for anything missing, outdated or wrong.',
      'You approve the changes that matter before anything goes live.',
      'Every product is re-tested to prove the fixes worked.',
    ],
    facts: [
      ['Covers', 'All your products'],
      ['Included', 'Local 4 · Growth 6 · Enterprise custom'],
    ],
  },
  minor: {
    title: 'Minor loop',
    summary: 'Fixes only what changed or was flagged, like a new price or updated hours.',
    steps: [
      'Something changes or gets flagged: a new price, updated hours, or an AI answer that drifted.',
      'Only the affected products are checked.',
      'A fix is drafted for just that change.',
      'You approve it before it goes live.',
      'The product is re-tested to confirm AI now gets it right.',
    ],
    facts: [
      ['Covers', 'Only what changed or was flagged'],
      ['Included', 'Unlimited on Local and Growth (fair use) · Enterprise custom'],
    ],
  },
} as const

/** A loop explainer that opens in place to show how it works and what's included. */
function LoopCard({ kind }: { kind: 'full' | 'minor' }) {
  const reduced = useReduced()
  const [open, setOpen] = useState(false)
  const panelId = useId()
  const loop = LOOPS[kind]
  const t = { duration: reduced ? 0 : 0.45, ease }

  return (
    <motion.div layout={!reduced} transition={t} className={`loopcard ${open ? 'is-open' : ''}`}>
      <button
        type="button"
        className="loopcard__head"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
      >
        <LoopDemo kind={kind} />
        <span className="loopcard__text">
          <span className="loops__title">{loop.title}</span>
          <span className="loops__text">{loop.summary}</span>
        </span>
        <motion.span className="loopcard__chev" animate={{ rotate: open ? 180 : 0 }} transition={t}>
          <ChevronDownIcon size={20} />
        </motion.span>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            id={panelId}
            role="region"
            aria-label={`${loop.title} details`}
            className="loopcard__panel"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={t}
          >
            <div className="loopcard__body">
              <h4 className="loopcard__label">How it works</h4>
              <ol className="loopcard__steps">
                {loop.steps.map((step, k) => (
                  <motion.li
                    key={step}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: reduced ? 0 : 0.35, ease, delay: reduced ? 0 : 0.1 + k * 0.06 }}
                  >
                    <span className="loopcard__num">{k + 1}</span>
                    {step}
                  </motion.li>
                ))}
              </ol>
              <dl className="loopcard__facts">
                {loop.facts.map(([label, value]) => (
                  <div key={label}>
                    <dt>{label}</dt>
                    <dd>{value}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

export default function Pricing() {
  const enter = useEnter()

  return (
    <Page>
      <div className="backdrop">
        <DotField />
      </div>
      <motion.div className="container biz" variants={stagger(0.12, 0.1)} {...enter}>
        <div className="biz__intro">
          <motion.h1 variants={fadeUp} className="h1 h1--md">
            Pay for the products you want understood.
          </motion.h1>
          <motion.p variants={fadeUp} className="lede lede--left biz__lede">
            One flat monthly subscription, based on how much you need to monitor and improve, not on how much AI
            you use.
          </motion.p>
          <motion.ul variants={fadeUp} className="included" aria-label="Every plan includes">
            {INCLUDED.map((f) => (
              <li key={f}>
                <CheckIcon size={16} strokeWidth={2.25} />
                {f}
              </li>
            ))}
          </motion.ul>
        </div>

        <motion.ul className="plans" variants={stagger(0.12, 0)}>
          {PLANS.map((p) => (
            <motion.li key={p.name} variants={fadeUp} className="plan">
              <h2 className="plan__name">{p.name}</h2>
              <p className="plan__blurb">{p.blurb}</p>
              <p className="plan__price">
                {p.from && <span className="plan__from">From</span>}
                <Price value={p.price} />
                <span className="plan__per">/ month</span>
              </p>
              <dl className="plan__rows">
                {p.rows.map(([label, value]) => (
                  <div key={label} className="plan__row">
                    <dt>{label}</dt>
                    <dd>{value}</dd>
                  </div>
                ))}
              </dl>
            </motion.li>
          ))}
        </motion.ul>

        <motion.section variants={fadeUp} className="loops" aria-label="Optimization loops">
          <LoopCard kind="full" />
          <LoopCard kind="minor" />
        </motion.section>
      </motion.div>
    </Page>
  )
}
