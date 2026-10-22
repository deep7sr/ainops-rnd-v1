import { useEffect, useState, type RefObject } from 'react'

/** The element's width on screen in pixels; null until it is measured (or cannot be). */
export function useElementWidth(ref: RefObject<Element | null>): number | null {
  const [width, setWidth] = useState<number | null>(null)
  useEffect(() => {
    const element = ref.current
    if (!element || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width || null))
    observer.observe(element)
    return () => observer.disconnect()
  }, [ref])
  return width
}
