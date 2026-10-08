import { CircleCheck, CircleDashed, CircleX } from 'lucide-react'
import type { DeviceStatus } from '@/api'
import { cn } from '@/lib/utils'

const LOOK = {
  reached: {
    label: 'Reached',
    icon: CircleCheck,
    className: 'border-status-healthy-border bg-status-healthy-bg text-status-healthy',
  },
  not_reached: {
    label: 'Not reached',
    icon: CircleX,
    className: 'border-status-warning-border bg-status-warning-bg text-status-warning',
  },
  not_discovered: {
    label: 'Not discovered yet',
    icon: CircleDashed,
    className: 'border-status-unknown-border bg-status-unknown-bg text-status-unknown',
  },
} as const

/** The device's status from the last discovery, as a coloured label with the time. */
export function DeviceStatusBadge({ status }: { status: DeviceStatus }) {
  const { label, icon: Icon, className } = LOOK[status.state]
  const time = status.state === 'not_reached' ? status.last_seen : status.at
  return (
    <span className="inline-flex flex-col items-start gap-0.5">
      <span
        className={cn(
          'inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] font-semibold',
          className,
        )}
      >
        <Icon aria-hidden="true" className="size-3" />
        {label}
      </span>
      {status.state !== 'not_discovered' && (
        <span className="text-[11px] text-muted-foreground">
          {status.state === 'not_reached' ? 'last seen ' : ''}
          {time ? new Date(time).toLocaleString() : 'unknown'}
        </span>
      )}
    </span>
  )
}
