// Motion settings in one place. The same timings are CSS variables in src/index.css (--motion-*), for
// CSS transitions; the token test checks the two stay equal. People who ask their system for reduced
// motion get none: <MotionConfig reducedMotion="user"> in main.tsx turns movement off for every
// `motion` element, and `useReducedMotion` (src/hooks) covers the hand-made SVG animation.

import type { Transition, Variants } from 'motion/react'

/** Durations in seconds (`motion` takes seconds; CSS has the same values in ms). */
export const DURATION = { fast: 0.15, base: 0.24, slow: 0.42 } as const

/** Fast start, soft landing: for things arriving. */
export const EASE_OUT = [0.22, 1, 0.36, 1] as const
/** For things moving from one place to another. */
export const EASE_IN_OUT = [0.65, 0, 0.35, 1] as const

export const enterTransition: Transition = { duration: DURATION.base, ease: EASE_OUT }

/** A new item slides in from below (timeline steps, cards). */
export const slideUp: Variants = {
  hidden: { opacity: 0, y: 8 },
  shown: { opacity: 1, y: 0, transition: enterTransition },
}

/** A result rises into place, a little slower than a step (the report card). */
export const rise: Variants = {
  hidden: { opacity: 0, y: 16, scale: 0.98 },
  shown: { opacity: 1, y: 0, scale: 1, transition: { duration: DURATION.slow, ease: EASE_OUT } },
}

/** One text replaces another in place (the "Now" banner). */
export const crossFade: Variants = {
  hidden: { opacity: 0, y: 4 },
  shown: { opacity: 1, y: 0, transition: { duration: DURATION.fast, ease: EASE_OUT } },
  gone: { opacity: 0, y: -4, transition: { duration: DURATION.fast, ease: EASE_IN_OUT } },
}
