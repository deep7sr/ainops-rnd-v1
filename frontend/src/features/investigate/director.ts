// Pacing: when each live event of an investigation reaches the screen.
//
// Real events come unevenly: 30 s of silence while the AI thinks, then three in one second. Shown
// as they come, a burst flashes past before anyone can follow the agent on the map. So each event
// gets a moment on screen before the next one is shown, with two hard rules:
// - never early: an event is never shown before it really happened (nothing is invented);
// - never far behind: at most MAX_LAG_MS after it happened, so a burst is caught up by shortening
//   the moments, and the screen stays a live view, not a replay.
// What happened before the page was opened (the history) is shown at once, without pacing.

import type { RunEvent } from '@/api'

/** How long an event keeps the stage before the next one may take it (ms). */
export const HOLD_MS: Partial<Record<RunEvent['type'], number>> = {
  tool_call: 1200, // the agent marker travels to the device, the console opens
  tool_result: 1500, // the output lines and the verdict stamp
  refused: 1500,
  recheck: 1200,
  skill: 900,
  hints: 700,
}

/** The screen is never more than this far behind the real investigation. */
export const MAX_LAG_MS = 3000

/**
 * When each event is shown, from when it arrived. `liveFrom`: index of the first event that arrived
 * live (the ones before it are history and are shown when they arrive); null: all history.
 */
export function showTimes(
  arrivals: number[],
  types: RunEvent['type'][],
  liveFrom: number | null,
  hold: (type: RunEvent['type']) => number = (type) => HOLD_MS[type] ?? 0,
): number[] {
  const times: number[] = []
  for (let i = 0; i < arrivals.length; i++) {
    const arrived = arrivals[i]
    if (liveFrom === null || i < liveFrom || i === 0) {
      times.push(arrived)
      continue
    }
    const free = times[i - 1] + hold(types[i - 1])
    times.push(Math.max(times[i - 1], Math.min(arrived + MAX_LAG_MS, Math.max(arrived, free))))
  }
  return times
}

/** How many events are on screen at `now`. */
export function shownCount(times: number[], now: number): number {
  let count = 0
  while (count < times.length && times[count] <= now) count++
  return count
}
