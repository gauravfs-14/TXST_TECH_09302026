import { useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { DotField, Tilt } from '../components/Effects'
import { PlayIcon } from '../components/Icons'
import { YOUTUBE_URL, youtubeId } from '../config'
import { fadeUp, press, stagger, useReduced, useReveal } from '../motion'

/**
 * Click-to-play YouTube: shows the poster first and only loads YouTube once
 * someone presses play (faster page, no tracking until then).
 */
function Player({ id }: { id: string | null }) {
  const reduced = useReduced()
  const [playing, setPlaying] = useState(false)

  if (!id) {
    return (
      <div className="player player--empty">
        <span className="player__play" aria-hidden="true">
          <PlayIcon size={30} />
        </span>
        <p className="player__note">Product video coming soon</p>
      </div>
    )
  }

  return (
    <div className="player">
      <AnimatePresence initial={false}>
        {playing ? (
          <motion.iframe
            key="video"
            className="player__frame"
            src={`https://www.youtube-nocookie.com/embed/${id}?autoplay=1&rel=0`}
            title="Confiance product video"
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
            allowFullScreen
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: reduced ? 0 : 0.4 }}
          />
        ) : (
          <motion.button
            key="poster"
            type="button"
            className="player__poster"
            aria-label="Play the Confiance product video"
            onClick={() => setPlaying(true)}
            exit={{ opacity: 0 }}
            whileHover="hover"
            whileTap="tap"
          >
            <img src={`https://i.ytimg.com/vi/${id}/hqdefault.jpg`} alt="" />
            <motion.span
              className="player__play"
              variants={{ hover: { scale: 1.1 }, tap: { scale: 0.95 } }}
              transition={{ type: 'spring', stiffness: 400, damping: 17 }}
            >
              <PlayIcon size={30} />
            </motion.span>
          </motion.button>
        )}
      </AnimatePresence>
    </div>
  )
}

export function Video() {
  const reveal = useReveal()
  const id = youtubeId(YOUTUBE_URL)

  return (
    <section id="video" className="section video">
      <DotField />
      <motion.div className="container video__inner" variants={stagger(0.15, 0.05)} {...reveal}>
        <motion.h2 variants={fadeUp} className="h1">
          See Confiance in action
        </motion.h2>
        <motion.p variants={fadeUp} className="lede video__lede">
          A short walkthrough of what Confiance checks, fixes and proves for your products.
        </motion.p>
        <motion.div variants={fadeUp} className="video__stage">
          <Tilt>
            <Player id={id} />
          </Tilt>
        </motion.div>
        {id && (
          <motion.a
            variants={fadeUp}
            href={YOUTUBE_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="video__link"
            {...press}
          >
            Watch on YouTube<span className="sr-only"> (opens in a new tab)</span>
          </motion.a>
        )}
      </motion.div>
    </section>
  )
}
