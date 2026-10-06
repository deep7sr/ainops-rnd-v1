import { CircleCheck, CornerDownRight, TriangleAlert } from 'lucide-react'
import { cn } from '@/lib/utils'
import { distanceText, endText, routeSource, type Trace } from './trace'

// The routing tables the trace followed, one line per device: which route the device itself chose
// for the destination and where it sends the traffic next.

export function TraceHops({ trace }: { trace: Trace }) {
  const arrived = trace.status === 'reached'
  return (
    <div className="mt-2 rounded-md border bg-background/60 px-3 py-2 text-sm">
      {trace.startNote && <p className="mb-1.5 text-xs text-muted-foreground">{trace.startNote}</p>}
      <ol aria-label="Route followed" className="space-y-1.5">
        {trace.hops.map((hop, index) => (
          <li key={`${hop.device}-${index}`} className="flex gap-2">
            <span className="w-4 shrink-0 text-right font-mono text-xs leading-5 text-muted-foreground">
              {index + 1}
            </span>
            <div className="min-w-0">
              <span className="font-medium">{hop.device}</span>
              {hop.route ? (
                <span className="text-muted-foreground">
                  {' '}
                  uses{' '}
                  <code className="font-mono text-[12px] text-foreground">
                    {hop.route.prefix}
                  </code>, {routeSource(hop.route.protocol)}
                  {hop.route.distanceMetric && ` (${distanceText(hop.route.distanceMetric)})`}
                </span>
              ) : (
                <span className="text-muted-foreground"> has no route for it</span>
              )}
              {hop.route?.nextHop && (
                <span className="flex items-center gap-1 text-xs text-muted-foreground">
                  <CornerDownRight aria-hidden="true" className="size-3 shrink-0" />
                  next hop {hop.route.nextHop}
                  {hop.nextHopDevice && ` (${hop.nextHopDevice})`}
                  {hop.route.interface && ` out of ${hop.route.interface}`}
                  {hop.equalPaths > 1 && `; ${hop.equalPaths} equal paths, following the first`}
                </span>
              )}
              {hop.note && <span className="block text-xs text-status-warning">{hop.note}</span>}
            </div>
          </li>
        ))}
      </ol>
      <p
        className={cn(
          'mt-2 flex items-start gap-1.5 text-sm font-medium',
          arrived ? 'text-status-healthy' : 'text-status-warning',
        )}
      >
        {arrived ? (
          <CircleCheck aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
        ) : (
          <TriangleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
        )}
        {endText(trace)}
      </p>
    </div>
  )
}
