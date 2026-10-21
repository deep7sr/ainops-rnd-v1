import { useSyncExternalStore } from 'react'

const REDUCED_MOTION = '(prefers-reduced-motion: reduce)'

function subscribe(onChange: () => void): () => void {
  const query = typeof window.matchMedia === 'function' ? window.matchMedia(REDUCED_MOTION) : null
  query?.addEventListener('change', onChange)
  return () => query?.removeEventListener('change', onChange)
}

/**
 * True when the person asked their system for reduced motion. `motion` elements already follow this
 * (MotionConfig in main.tsx) and CSS has `motion-reduce`; hand-made SVG animation (the map's ping
 * packets) needs to ask.
 */
export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => typeof window.matchMedia === 'function' && window.matchMedia(REDUCED_MOTION).matches,
    () => false,
  )
}
