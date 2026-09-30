import { AnimatePresence, MotionConfig, motion } from 'motion/react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { CursorDot } from './components/CursorDot'
import { ease, useReduced } from './motion'
import Home from './pages/Home'
import Product from './pages/Product'
import Pricing from './pages/Pricing'

export default function App() {
  const location = useLocation()
  const reduced = useReduced()

  return (
    <MotionConfig reducedMotion="user">
      <AnimatePresence mode="wait">
        <motion.div
          key={location.pathname}
          exit={{ opacity: 0 }}
          transition={{ duration: reduced ? 0 : 0.5, ease }}
        >
          <Routes location={location}>
            <Route path="/" element={<Home />} />
            <Route path="/product" element={<Product />} />
            <Route path="/pricing" element={<Pricing />} />
            {/* Earlier addresses land somewhere sensible. */}
            <Route path="/how-it-works" element={<Navigate to="/product" replace />} />
            <Route path="/trust" element={<Navigate to="/product#trust" replace />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </motion.div>
      </AnimatePresence>
      <CursorDot />
    </MotionConfig>
  )
}
