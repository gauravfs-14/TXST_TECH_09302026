import { motion, type Easing, type Variants } from 'motion/react'
import { HeroScene } from '../components/HeroScene'
import { ChevronDownIcon, PlayIcon } from '../components/Icons'
import { ease, press, useReduced } from '../motion'

const HEADLINE = 'Your next customer won’t search. They’ll ask.'

/*
 * One orchestrated entrance, timed by hand (seconds): lines rise out of masks,
 * then a magnifying glass sweeps across "search." drawing a red strike; at the
 * end of the word the strike and glass fade, "search." brightens back to
 * white, and "They'll ask." lands.
 */
const T = { lines: [0.15, 0.3], sweep: 1.0, ask: 2.35, lede: 2.7, cta: 2.85, cue: 3.4 }

// One loop of the "search." sweep, in seconds: the glass crosses the word
// (lighting it up), clears, the word stays bright, then slowly dims again.
const CROSS_S = 1.9
const CYCLE_S = 5.8
const AT_END = CROSS_S / CYCLE_S // glass reaches the end of the word
const DIM_FROM = 0.74 // bright hold ends, word starts dimming back
const DIM_TO = 0.92

const rise: Variants = {
  hidden: { y: '110%' },
  show: (delay: number) => ({ y: 0, transition: { duration: 0.9, ease, delay } }),
}
const fade: Variants = {
  hidden: { opacity: 0, y: 28 },
  show: (delay: number) => ({ opacity: 1, y: 0, transition: { duration: 0.85, ease, delay } }),
}
const sweepEase = [0.45, 0, 0.35, 1] as const

// Every part of the sweep shares one clock, so they stay in step on each loop.
const loop = (delay: number, times: number[], ease: Easing | Easing[] = 'linear') => ({
  duration: CYCLE_S,
  times,
  ease,
  delay,
  repeat: Infinity,
})
const travel = [0, AT_END, 1]
const travelEase: Easing[] = [sweepEase, 'linear']

// Red trail behind the glass: bright at the glass, fading out over the
// letters already passed; it clears when the glass reaches the end.
const strike: Variants = {
  hidden: { width: '0%', opacity: 1 },
  show: (delay: number) => ({
    width: ['0%', '100%', '100%'],
    opacity: [1, 1, 0, 0],
    transition: {
      width: loop(delay, travel, travelEase),
      opacity: loop(delay, [0, AT_END, AT_END + 0.1, 1]),
    },
  }),
}
// The magnifying glass rides the head of the trail, then pops away.
const lens: Variants = {
  hidden: { left: '0%', opacity: 0, scale: 0.6 },
  show: (delay: number) => ({
    left: ['0%', '100%', '100%'],
    opacity: [0, 1, 1, 0, 0],
    scale: [0.6, 1, 1, 0.4, 0.4],
    transition: {
      left: loop(delay, travel, travelEase),
      opacity: loop(delay, [0, 0.03, AT_END, AT_END + 0.07, 1]),
      scale: loop(delay, [0, 0.03, AT_END, AT_END + 0.07, 1]),
    },
  }),
}
// A bright copy of "search." over the dim one, revealed left to right right
// behind the glass; after a hold it fades back so the next sweep lights it again.
const lit: Variants = {
  hidden: { clipPath: 'inset(0 100% 0 0)', opacity: 1 },
  show: (delay: number) => ({
    clipPath: ['inset(0 100% 0 0)', 'inset(0 0% 0 0)', 'inset(0 0% 0 0)'],
    opacity: [1, 1, 0, 0],
    transition: {
      clipPath: loop(delay, travel, travelEase),
      opacity: loop(delay, [0, DIM_FROM, DIM_TO, 1], 'easeInOut'),
    },
  }),
}

export function HomeHero() {
  const reduced = useReduced()

  return (
    <section className="hero" aria-label="Introduction">
      <HeroScene />
      <motion.div
        className="container hero__inner"
        variants={{ hidden: {}, show: {} }}
        initial={reduced ? false : 'hidden'}
        animate="show"
      >
        {/* Home spot for the site-wide cursor dot (CursorDot); a still dot under reduced motion. */}
        <motion.div variants={fade} custom={0} className="pulse" data-cursor-home aria-hidden="true">
          {reduced && <span className="pulse__dot" />}
        </motion.div>

        <h1 className="display hero__title" aria-label={HEADLINE}>
          <span className="mask" aria-hidden="true">
            <motion.span className="mask__line" variants={rise} custom={T.lines[0]}>
              Your next customer
            </motion.span>
          </span>
          <span className="mask" aria-hidden="true">
            <motion.span className="mask__line" variants={rise} custom={T.lines[1]}>
              won’t{' '}
              <span className="struck">
                {/* Under reduced motion the sweep is skipped: "search." simply reads plain. */}
                <span className={reduced ? undefined : 'struck__dim'}>search.</span>
                {!reduced && (
                  <>
                    <motion.span className="struck__lit" variants={lit} custom={T.sweep}>
                      search.
                    </motion.span>
                    <motion.span className="struck__line" variants={strike} custom={T.sweep} />
                    <motion.span className="struck__lens" variants={lens} custom={T.sweep}>
                      {/* Magnifying glass in the rocket's flame colors. */}
                      <svg viewBox="0 0 24 24" fill="none" strokeWidth="2.75" strokeLinecap="round" aria-hidden="true">
                        <defs>
                          <linearGradient id="lens-fire" gradientUnits="userSpaceOnUse" x1="4" y1="4" x2="21" y2="21">
                            <stop offset="0" stopColor="#fff4d6" />
                            <stop offset="0.5" stopColor="#ffb25c" />
                            <stop offset="1" stopColor="#ff6a3d" />
                          </linearGradient>
                        </defs>
                        <circle cx="11" cy="11" r="7" stroke="url(#lens-fire)" />
                        <path d="M16.5 16.5L21 21" stroke="url(#lens-fire)" />
                      </svg>
                    </motion.span>
                  </>
                )}
              </span>
            </motion.span>
          </span>
          <span className="mask" aria-hidden="true">
            <motion.span className="mask__line" variants={rise} custom={T.ask}>
              They’ll ask.
            </motion.span>
          </span>
        </h1>

        <motion.p variants={fade} custom={T.lede} className="lede hero__lede">
          Confiance makes sure AI assistants recommend your products, and get the facts right.
        </motion.p>

        <motion.div variants={fade} custom={T.cta} className="hero__ctas">
          <motion.a href="#how-it-works" className="btn btn--primary btn--lg" {...press}>
            See how it works
          </motion.a>
          <motion.a href="#video" className="btn btn--ghost btn--lg" {...press}>
            <PlayIcon size={18} /> Watch the video
          </motion.a>
        </motion.div>
      </motion.div>

      <motion.a
        href="#how-it-works"
        className="scroll-cue"
        aria-label="Scroll to how it works"
        initial={reduced ? false : { opacity: 0 }}
        animate={{ opacity: 1, transition: { delay: T.cue } }}
      >
        <motion.span
          animate={reduced ? undefined : { y: [0, 6, 0] }}
          transition={{ duration: 1.6, repeat: Infinity, ease: 'easeInOut' }}
        >
          <ChevronDownIcon size={22} />
        </motion.span>
      </motion.a>
    </section>
  )
}
