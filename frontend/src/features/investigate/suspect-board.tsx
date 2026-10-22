// The suspect board under the map: every device the investigation is about, in the column the live
// checks put it in. A device glides to its new column when a check moves it. "No problem found"
// is what the checks so far say, not a proof that the device is fine. Data: hud.ts.

import {
  CircleCheck,
  CircleDashed,
  Crosshair,
  Loader2,
  TriangleAlert,
  type LucideIcon,
} from 'lucide-react'
import { LayoutGroup, motion } from 'motion/react'
import { DeviceGlyph } from '@/components/device-glyph'
import { DURATION, EASE_IN_OUT } from '@/lib/motion'
import { cn } from '@/lib/utils'
import type { Suspect, SuspectColumn } from './hud'

const COLUMNS: { key: SuspectColumn; title: string; icon: LucideIcon; tone: string }[] = [
  { key: 'todo', title: 'Not checked yet', icon: CircleDashed, tone: 'text-muted-foreground' },
  {
    key: 'healthy',
    title: 'Checked, no problem found',
    icon: CircleCheck,
    tone: 'text-status-healthy',
  },
  { key: 'problem', title: 'Problem seen', icon: TriangleAlert, tone: 'text-status-warning' },
  { key: 'cause', title: 'Root cause', icon: Crosshair, tone: 'text-status-critical' },
]

const CARD_TONE: Record<SuspectColumn, string> = {
  todo: 'border-border bg-card',
  healthy: 'border-status-healthy-border bg-status-healthy-bg',
  problem: 'border-status-warning-border bg-status-warning-bg',
  cause: 'border-status-critical-border bg-status-critical-bg',
}

/** The note under a device: in its column's colour, which is readable on its card. */
const NOTE_TONE: Record<SuspectColumn, string> = {
  todo: 'text-muted-foreground',
  healthy: 'text-status-healthy',
  problem: 'text-status-warning',
  cause: 'text-status-critical',
}

export function SuspectBoard({
  board,
  roles,
  onSelect,
}: {
  board: Record<SuspectColumn, Suspect[]>
  roles: Map<string, string>
  onSelect: (device: string) => void
}) {
  return (
    <section aria-label="Suspects" className="space-y-2">
      <p className="text-xs text-muted-foreground">
        <span className="font-semibold tracking-wider text-eyebrow uppercase">Suspects</span> ·
        where the live checks put each device so far
      </p>
      <LayoutGroup>
        <div className="grid grid-cols-2 gap-2 2xl:grid-cols-4">
          {COLUMNS.map(({ key, title, icon: Icon, tone }) => (
            <div
              key={key}
              role="group"
              aria-label={title}
              className="rounded-md border bg-muted/40 p-2"
            >
              <p className={cn('mb-1.5 flex items-center gap-1 text-[11px] font-semibold', tone)}>
                <Icon aria-hidden="true" className="size-3.5 shrink-0" />
                {title}
                <span className="ml-auto font-normal text-muted-foreground tabular-nums">
                  {board[key].length}
                </span>
              </p>
              {board[key].length === 0 ? (
                <p className="text-[11px] text-muted-foreground">None</p>
              ) : (
                <ul className="space-y-1">
                  {board[key].map((suspect) => (
                    <motion.li
                      key={suspect.device}
                      layoutId={`suspect-${suspect.device}`}
                      transition={{ duration: DURATION.slow * 1.5, ease: EASE_IN_OUT }}
                    >
                      <button
                        type="button"
                        onClick={() => onSelect(suspect.device)}
                        className={cn(
                          'w-full rounded border px-2 py-1 text-left text-xs focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none',
                          CARD_TONE[key],
                          suspect.checking && 'border-primary glow',
                        )}
                      >
                        <span className="flex items-center gap-1.5 font-medium">
                          <DeviceGlyph
                            deviceRole={roles.get(suspect.device) ?? ''}
                            className="size-4 shrink-0 text-primary"
                          />
                          <span className="min-w-0 truncate">{suspect.device}</span>
                          {suspect.checking && (
                            <>
                              <Loader2
                                aria-hidden="true"
                                className="ml-auto size-3 shrink-0 animate-spin text-primary motion-reduce:animate-none"
                              />
                              <span className="sr-only">(being checked now)</span>
                            </>
                          )}
                        </span>
                        {suspect.note && (
                          <span
                            className={cn('mt-0.5 line-clamp-2 block text-[11px]', NOTE_TONE[key])}
                          >
                            {suspect.note}
                          </span>
                        )}
                      </button>
                    </motion.li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      </LayoutGroup>
    </section>
  )
}
