import { describe, expect, it } from 'vitest'
import type { RunEvent } from '@/api'
import { HOLD_MS, MAX_LAG_MS, showTimes, shownCount } from './director'

// The fault-1 investigation recorded on the live lab: its real rhythm (long silences while the AI
// thinks, then several events at once) used as arrival times, as if it were being watched live.
const files = import.meta.glob<{ events: RunEvent[] }>('../../../../fixtures/runs/*.json', {
  eager: true,
  import: 'default',
})
const RECORDED = Object.entries(files).find(([path]) =>
  path.endsWith('/fault1-leased-line-shut-run1.json'),
)?.[1].events as RunEvent[]
const TYPES = RECORDED.map((e) => e.type)
const ARRIVALS = RECORDED.map((e) => ('at_ms' in e ? e.at_ms : 0))
const CALL_HOLD = HOLD_MS.tool_call ?? 0

describe('pacing the live view', () => {
  const times = showTimes(ARRIVALS, TYPES, 0)

  it('the recorded run has bursts to pace and silences to wait through', () => {
    const gaps = ARRIVALS.slice(1).map((t, i) => t - ARRIVALS[i])
    expect(gaps.some((g) => g < 200)).toBe(true)
    expect(gaps.some((g) => g > 5000)).toBe(true)
  })

  it('never shows an event before it happened', () => {
    times.forEach((t, i) => expect(t).toBeGreaterThanOrEqual(ARRIVALS[i]))
  })

  it(`is never more than ${MAX_LAG_MS / 1000} s behind`, () => {
    times.forEach((t, i) => expect(t - ARRIVALS[i]).toBeLessThanOrEqual(MAX_LAG_MS))
  })

  it('keeps the order', () => {
    times.slice(1).forEach((t, i) => expect(t).toBeGreaterThanOrEqual(times[i]))
  })

  it('gives a check its moment before its result follows', () => {
    // A call and its result 100 ms apart: the result waits for the call's moment on stage.
    const paced = showTimes([0, 100], ['tool_call', 'tool_result'], 0)
    expect(paced).toEqual([0, CALL_HOLD])
  })

  it('catches up a long burst instead of falling further behind', () => {
    const burst = Array.from({ length: 10 }, (_, i) => i * 10)
    const paced = showTimes(burst, Array(10).fill('tool_call'), 0)
    expect(paced[9]).toBe(burst[9] + MAX_LAG_MS)
    expect(shownCount(paced, burst[9] + MAX_LAG_MS)).toBe(10)
  })

  it('shows an event after a silence the moment it happens', () => {
    const paced = showTimes([0, 30_000], ['tool_result', 'tool_call'], 0)
    expect(paced[1]).toBe(30_000)
  })

  it('shows the history at once', () => {
    expect(showTimes(ARRIVALS, TYPES, null)).toEqual(ARRIVALS)
    const partly = showTimes(
      [0, 10, 20, 30],
      ['tool_call', 'tool_result', 'tool_call', 'tool_result'],
      3,
    )
    expect(partly.slice(0, 3)).toEqual([0, 10, 20])
    expect(partly[3]).toBe(20 + CALL_HOLD)
  })

  it('in the end everything is on screen, as without pacing', () => {
    expect(shownCount(times, Math.max(...ARRIVALS) + MAX_LAG_MS)).toBe(RECORDED.length)
  })
})
