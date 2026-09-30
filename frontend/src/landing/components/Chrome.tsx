import { useEffect, useState, type ReactNode } from 'react'
import { AnimatePresence, motion, useMotionValueEvent, useScroll } from 'motion/react'
import { Link, NavLink, useLocation } from 'react-router-dom'
import { DASHBOARD_URL } from '../config'
import { press, useReduced } from '../motion'
import { useTheme } from '../theme'
import { MoonIcon, SunIcon } from './Icons'

/** Router link with Motion gesture props. */
export const MotionLink = motion.create(Link)

/** Brand mark (public/logo-mark.png): the Confiance logo on a transparent background. */
export function Logo() {
  return <img className="logo" src="/logo-mark.png" alt="Confiance" width={323} height={229} />
}

const LINKS = [
  { to: '/', label: 'Home' },
  { to: '/product', label: 'Product' },
  { to: '/pricing', label: 'Pricing' },
]

function ThemeToggle() {
  const { wanted, toggle } = useTheme()
  const reduced = useReduced()
  const dark = wanted === 'dark'
  const spring = reduced ? { duration: 0 } : { type: 'spring' as const, stiffness: 500, damping: 30 }

  return (
    <button type="button" role="switch" aria-checked={dark} aria-label="Dark mode" className="toggle" onClick={toggle}>
      <span className={`toggle__track ${dark ? 'is-on' : ''}`}>
        <motion.span layout transition={spring} className="toggle__knob">
          <AnimatePresence mode="wait" initial={false}>
            <motion.span
              key={wanted}
              className="toggle__icon"
              initial={{ rotate: -90, opacity: 0, scale: 0.6 }}
              animate={{ rotate: 0, opacity: 1, scale: 1 }}
              exit={{ rotate: 90, opacity: 0, scale: 0.6 }}
              transition={{ duration: reduced ? 0 : 0.25 }}
            >
              {dark ? <MoonIcon size={14} /> : <SunIcon size={14} />}
            </motion.span>
          </AnimatePresence>
        </motion.span>
      </span>
    </button>
  )
}

export function Nav({ overlay = false }: { overlay?: boolean }) {
  // Hairline under the sticky nav once content scrolls beneath it. Over the
  // Home scene the nav stays transparent until the scene has scrolled away.
  const { scrollY } = useScroll()
  const [scrolled, setScrolled] = useState(false)
  const [floating, setFloating] = useState(false)
  useMotionValueEvent(scrollY, 'change', (y) => {
    setScrolled(y > (overlay ? window.innerHeight - 140 : 8))
    setFloating(y > 8)
  })

  return (
    <header
      className={`nav ${scrolled ? 'is-scrolled' : ''} ${overlay ? 'nav--overlay' : ''} ${floating ? 'is-floating' : ''}`}
    >
      <div className="container nav__inner">
        <MotionLink to="/" className="nav__home" aria-label="Confiance, home" {...press}>
          <Logo />
        </MotionLink>
        <nav aria-label="Main">
          <ul className="nav__links">
            {LINKS.map((l) => (
              <li key={l.to}>
                <NavLink to={l.to} end className="nav__link">
                  {l.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <div className="nav__end">
          <ThemeToggle />
          <motion.a href={DASHBOARD_URL} className="btn btn--nav" {...press}>
            Open dashboard
          </motion.a>
        </div>
      </div>
    </header>
  )
}

/** A tab page: sticky nav above scrolling sections. Opens at the top unless a #section is linked. */
export function Page({ children, overlayNav = false }: { children: ReactNode; overlayNav?: boolean }) {
  const { hash } = useLocation()
  useEffect(() => {
    if (hash) document.querySelector(hash)?.scrollIntoView()
    else window.scrollTo(0, 0)
  }, [hash])
  return (
    <div className="page">
      <Nav overlay={overlayNav} />
      <main>{children}</main>
    </div>
  )
}

export function Pill({ children }: { children: ReactNode }) {
  return <span className="pill pill--warn">{children}</span>
}
