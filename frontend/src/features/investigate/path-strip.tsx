// The path as a line of stops under the map, like a metro line: from the source LAN through every
// device to the destination LAN, each in the colour of what the checks found. It reads the same
// for 3 hops or 30, where the map gets crowded. Data: the path the agent found (get_path or a
// trace) and the LANs of the question (features/topology/lan.ts).

import { motion } from 'motion/react'
import { DeviceGlyph } from '@/components/device-glyph'
import type { DeviceState } from '@/features/topology/highlight'
import { DURATION, EASE_OUT } from '@/lib/motion'
import { cn } from '@/lib/utils'
import type { Stop } from './path-stops'

const SAYS: Record<DeviceState, string> = {
  checking: 'being checked now',
  ok: 'checked, healthy',
  problem: 'problem found',
  unreachable: 'did not answer',
  checked: 'checked',
}

export function PathStrip({
  stops,
  states,
  faults,
}: {
  stops: Stop[]
  states: Map<string, DeviceState>
  faults: Set<string>
}) {
  if (stops.length === 0) return null
  const hops = stops.length - 1
  return (
    <div className="flex items-center gap-3 overflow-x-auto rounded-lg border bg-card px-3 py-2">
      <p className="shrink-0 text-xs font-semibold tracking-wider text-eyebrow uppercase">
        Path · {hops} {hops === 1 ? 'hop' : 'hops'}
      </p>
      <ol aria-label="The path, hop by hop" className="flex items-center">
        {stops.map((stop, i) => {
          const state = stop.lan ? undefined : states.get(stop.name)
          const fault = faults.has(stop.name)
          return (
            <motion.li
              key={stop.name}
              initial={{ opacity: 0, x: -6 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: DURATION.base, ease: EASE_OUT, delay: i * 0.06 }}
              className="flex shrink-0 items-center"
            >
              {i > 0 && (
                <span
                  aria-hidden="true"
                  className={cn('h-0.5 w-4', fault ? 'bg-status-critical' : 'bg-primary/60')}
                />
              )}
              <span
                className={cn(
                  'flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap transition-colors duration-(--motion-base)',
                  fault
                    ? 'border-status-critical-border bg-status-critical-bg text-status-critical'
                    : state === 'checking'
                      ? 'border-primary bg-secondary text-foreground glow'
                      : state === 'problem'
                        ? 'border-status-warning-border bg-status-warning-bg text-status-warning'
                        : state === 'ok'
                          ? 'border-status-healthy-border bg-status-healthy-bg text-foreground'
                          : state === 'unreachable'
                            ? 'border-status-unknown-border bg-status-unknown-bg text-foreground'
                            : 'border-primary/40 bg-card text-foreground',
                )}
              >
                <DeviceGlyph
                  deviceRole={stop.role}
                  className={cn(
                    'size-4',
                    fault
                      ? 'text-status-critical'
                      : state === 'problem'
                        ? 'text-status-warning'
                        : state === 'ok'
                          ? 'text-status-healthy'
                          : 'text-primary',
                  )}
                />
                {stop.name}
                {(fault || state) && (
                  <span className="sr-only">: {fault ? 'root cause' : SAYS[state!]}</span>
                )}
              </span>
            </motion.li>
          )
        })}
      </ol>
    </div>
  )
}
