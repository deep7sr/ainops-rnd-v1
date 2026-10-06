import { useMutation } from '@tanstack/react-query'
import { CircleCheck, CircleX, Loader2, RefreshCw, Sparkles, TriangleAlert } from 'lucide-react'
import { api, type GraphDevice, type ToolHealth } from '@/api'
import { JsonView } from '@/components/json-view'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import type { DeviceState } from '@/features/topology/highlight'
import { cn } from '@/lib/utils'
import type { Step } from './derive'
import { formatMs } from './format'
import { hopsOf } from './trace'

// Clicking a device on the live map: what it is, what the agent found on it in this run (with the
// evidence), its interfaces from the knowledge graph, and a live read-only check on demand.

const STATE_TEXT: Record<DeviceState, string> = {
  checking: 'Being checked now',
  ok: 'Checked: healthy',
  problem: 'Checked: problem found',
  unreachable: 'Did not answer',
  checked: 'Checked',
}

function HealthLine({ health, summary }: { health: ToolHealth | null; summary: string }) {
  if (health?.status === 'problem') {
    return (
      <ul className="space-y-0.5">
        {health.issues.map((issue) => (
          <li key={issue.text} className="flex items-start gap-1.5 font-medium text-status-warning">
            <TriangleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            {issue.text}
          </li>
        ))}
      </ul>
    )
  }
  return (
    <p className="flex items-start gap-1.5">
      <CircleCheck aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-status-healthy" />
      {summary}
    </p>
  )
}

function LiveCheck({ device }: { device: string }) {
  const check = useMutation({
    mutationFn: () => api.callTool('network', 'get_interfaces', { device }),
  })
  const structured = check.data?.structured as
    { summary?: string; health?: ToolHealth; evidence?: { source?: string } } | null | undefined

  return (
    <div className="space-y-2">
      <Button variant="outline" size="sm" onClick={() => check.mutate()} disabled={check.isPending}>
        {check.isPending ? (
          <Loader2 aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
        ) : (
          <RefreshCw aria-hidden="true" />
        )}
        Check interfaces now
      </Button>
      <p className="text-xs text-muted-foreground">
        Runs the read-only interface check on the device through the network MCP server (it is
        written to the audit log). It never changes the device.
      </p>
      {check.isError && (
        <p role="alert" className="text-sm text-status-critical">
          {check.error.message}
        </p>
      )}
      {check.data &&
        (check.data.is_error ? (
          <p role="alert" className="flex items-start gap-1.5 text-sm text-status-critical">
            <CircleX aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            {check.data.text}
          </p>
        ) : (
          <div className="text-sm">
            <HealthLine health={structured?.health ?? null} summary={structured?.summary ?? ''} />
          </div>
        ))}
    </div>
  )
}

export function DevicePanel({
  device,
  state,
  issues,
  steps,
  onClose,
  onSelectEvidence,
}: {
  device: GraphDevice | null
  state: DeviceState | undefined
  issues: string[]
  steps: Step[]
  onClose: () => void
  onSelectEvidence: (id: string) => void
}) {
  const mine = device
    ? steps.filter((s) => s.device === device.name || hopsOf(s).includes(device.name))
    : []

  return (
    <Sheet open={device !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-md">
        {device && (
          <>
            <SheetHeader>
              <SheetTitle>{device.name}</SheetTitle>
              <SheetDescription>
                {device.description || device.role} · {device.site} ·{' '}
                {device.platform === 'juniper_junos' ? 'Juniper Junos' : 'Cisco IOS'}
              </SheetDescription>
            </SheetHeader>

            <div className="space-y-6 px-4 pb-6">
              <section className="space-y-1.5">
                <h3 className="eyebrow">In this investigation</h3>
                <p
                  className={cn(
                    'text-sm font-medium',
                    state === 'problem' && 'text-status-warning',
                    state === 'ok' && 'text-status-healthy',
                    state === 'unreachable' && 'text-status-critical',
                  )}
                >
                  {state ? STATE_TEXT[state] : 'Not checked by the agent'}
                </p>
                {issues.length > 0 && (
                  <ul className="list-disc pl-5 text-sm text-status-warning">
                    {issues.map((issue) => (
                      <li key={issue}>{issue}</li>
                    ))}
                  </ul>
                )}
              </section>

              {mine.length > 0 && (
                <section className="space-y-3">
                  <h3 className="eyebrow">What the agent checked here</h3>
                  <ol className="space-y-3">
                    {mine.map((step) => (
                      <li key={step.key} className="space-y-1.5 rounded-md border p-3 text-sm">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-medium">{step.sentence}</span>
                          {step.evidenceId && (
                            <button
                              type="button"
                              onClick={() => onSelectEvidence(step.evidenceId as string)}
                              className="shrink-0 rounded border bg-background px-1.5 py-px font-mono text-[11px] text-primary hover:border-primary focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
                            >
                              {step.evidenceId}
                            </button>
                          )}
                        </div>
                        {step.why && (
                          <p className="flex items-start gap-1.5 text-provenance-ai">
                            <Sparkles aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
                            {step.why}
                          </p>
                        )}
                        {step.state === 'running' ? (
                          <p className="text-muted-foreground">Running…</p>
                        ) : step.state === 'error' ? (
                          <p className="text-status-critical">{step.summary}</p>
                        ) : (
                          <HealthLine health={step.health} summary={step.summary} />
                        )}
                        {step.evidence && (
                          <details className="text-xs">
                            <summary className="cursor-pointer text-primary">
                              Evidence: <code className="font-mono">{step.evidence.command}</code>{' '}
                              <Badge
                                variant="outline"
                                className="ml-1 h-4 px-1 text-[10px] uppercase"
                              >
                                {step.evidence.source}
                              </Badge>{' '}
                              {formatMs(step.durationMs)}
                            </summary>
                            <JsonView value={step.data} className="mt-2" />
                          </details>
                        )}
                      </li>
                    ))}
                  </ol>
                </section>
              )}

              <section className="space-y-2">
                <h3 className="eyebrow">Interfaces (last discovery)</h3>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-muted-foreground">
                      <th className="py-1 font-medium">Interface</th>
                      <th className="py-1 font-medium">Status</th>
                      <th className="py-1 font-medium">IPv4</th>
                    </tr>
                  </thead>
                  <tbody>
                    {device.interfaces.map((i) => (
                      <tr key={i.name} className="border-t">
                        <td className="py-1 font-mono">{i.name}</td>
                        <td
                          className={cn(
                            'py-1',
                            i.status === 'up' ? 'text-status-healthy' : 'text-status-critical',
                          )}
                        >
                          {i.status}
                        </td>
                        <td className="py-1 font-mono">{i.ipv4.join(', ') || '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>

              <section className="space-y-2">
                <h3 className="eyebrow">Live status</h3>
                <LiveCheck device={device.name} />
              </section>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}
