import { useSyncExternalStore } from 'react'

const MOBILE_BREAKPOINT = 768
const MOBILE_QUERY = `(max-width: ${MOBILE_BREAKPOINT - 1}px)`

// AINOPS: rewritten with useSyncExternalStore (React's tool for following a browser value) instead of
// shadcn's setState-in-an-effect, which rendered twice and is flagged by the react-hooks lint rules.
function subscribe(onChange: () => void): () => void {
  const media = window.matchMedia(MOBILE_QUERY)
  media.addEventListener('change', onChange)
  return () => media.removeEventListener('change', onChange)
}

/** True when the window is narrower than 768 px (the sidebar becomes a slide-in panel). */
export function useIsMobile(): boolean {
  return useSyncExternalStore(subscribe, () => window.matchMedia(MOBILE_QUERY).matches)
}
