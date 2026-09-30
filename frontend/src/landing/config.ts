/**
 * Where "Open dashboard" goes. The dashboard lives in this same app at
 * /dashboard (see src/main.tsx); it is a plain link so the page reloads into
 * it. Set VITE_DASHBOARD_URL (e.g. in .env.local) to point elsewhere.
 */
export const DASHBOARD_URL: string = import.meta.env.VITE_DASHBOARD_URL || '/dashboard'

/**
 * The product walkthrough on the Home page. Paste any YouTube link here or set
 * VITE_YOUTUBE_URL (watch, youtu.be, embed or shorts links all work). Until
 * one is set, the section shows a "coming soon" frame.
 */
export const YOUTUBE_URL: string = import.meta.env.VITE_YOUTUBE_URL || ''

export function youtubeId(url: string): string | null {
  const m = url.match(/(?:v=|youtu\.be\/|embed\/|shorts\/)([\w-]{11})/)
  return m ? m[1] : null
}

/**
 * Optional background illustration for the Home hero (a path in /public or a
 * full URL). Leave empty to use the animated night scene drawn in code.
 */
export const HERO_IMAGE: string = import.meta.env.VITE_HERO_IMAGE || ''
