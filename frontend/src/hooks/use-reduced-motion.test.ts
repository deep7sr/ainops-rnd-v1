import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { usePrefersReducedMotion } from './use-reduced-motion'

/** A browser whose "reduce motion" setting can be switched while the page is open. */
function fakeSetting(reduce: boolean) {
  const listeners = new Set<() => void>()
  const query = {
    get matches() {
      return reduce
    },
    addEventListener: (_: string, fn: () => void) => listeners.add(fn),
    removeEventListener: (_: string, fn: () => void) => listeners.delete(fn),
  }
  vi.stubGlobal(
    'matchMedia',
    vi.fn((media: string) =>
      media === '(prefers-reduced-motion: reduce)' ? query : { ...query, matches: false },
    ),
  )
  return {
    set(next: boolean) {
      reduce = next
      listeners.forEach((fn) => fn())
    },
  }
}

describe('reduced motion', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('follows the system setting', () => {
    fakeSetting(true)
    expect(renderHook(() => usePrefersReducedMotion()).result.current).toBe(true)
  })

  it('moves when the system does not ask otherwise', () => {
    fakeSetting(false)
    expect(renderHook(() => usePrefersReducedMotion()).result.current).toBe(false)
  })

  it('stops the motion as soon as the setting changes, without a reload', () => {
    const setting = fakeSetting(false)
    const { result } = renderHook(() => usePrefersReducedMotion())
    act(() => setting.set(true))
    expect(result.current).toBe(true)
  })
})
