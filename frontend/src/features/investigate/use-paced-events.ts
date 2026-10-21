import { useEffect, useMemo, useState } from 'react'
import type { RunEvent } from '@/api'
import { showTimes, shownCount } from './director'

/**
 * The events of a run as the screen should show them now (see director.ts). Without pacing (the
 * person asked for reduced motion, or nothing has happened live yet) every event shows at once.
 */
export function usePacedEvents(
  events: RunEvent[],
  arrivals: number[],
  liveFrom: number | null,
  paced: boolean,
): RunEvent[] {
  const times = useMemo(
    () =>
      showTimes(
        arrivals,
        events.map((e) => e.type),
        paced ? liveFrom : null,
      ),
    [arrivals, events, liveFrom, paced],
  )
  // The clock only moves forward when the next event is due, so the page renders once per event.
  const [now, setNow] = useState(() => performance.now())
  // History (everything before `liveFrom`) is always on screen at once.
  const count =
    paced && liveFrom !== null
      ? Math.max(Math.min(liveFrom, events.length), shownCount(times, now))
      : events.length

  useEffect(() => {
    if (count >= times.length) return
    const timer = setTimeout(
      () => setNow(performance.now()),
      Math.max(0, times[count] - performance.now()),
    )
    return () => clearTimeout(timer)
  }, [times, count])

  return useMemo(() => (count === events.length ? events : events.slice(0, count)), [events, count])
}
