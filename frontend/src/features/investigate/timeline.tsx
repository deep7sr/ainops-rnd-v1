import {
  ChevronDown,
  CircleCheck,
  CircleX,
  Loader2,
  Network,
  Router,
  ShieldX,
  Sparkles,
  TriangleAlert,
  type LucideIcon,
} from 'lucide-react'
import { useState } from 'react'
import { JsonView } from '@/components/json-view'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { Step } from './derive'
import { formatMs } from './format'

const SERVER_ICON: Record<string, LucideIcon> = { topology: Network, network: Router }

function argText(args: Record<string, unknown>): string {
  return Object.entries(args)
    .filter(([key]) => key !== 'device')
    .map(([key, value]) => `${key}=${String(value)}`)
    .join(' ')
}

function StepItem({
  step,
  focused,
  last,
  onSelectDevice,
}: {
  step: Step
  focused: boolean
  last: boolean
  onSelectDevice?: (device: string) => void
}) {
  const [open, setOpen] = useState(false)
  const Icon = step.kind === 'refused' ? ShieldX : (SERVER_ICON[step.server] ?? Router)
  const details = argText(step.args)

  return (
    <li id={step.evidenceId ? `step-${step.evidenceId}` : undefined} className="flex gap-3">
      <div className="flex flex-col items-center">
        <span
          className={cn(
            'flex size-8 shrink-0 items-center justify-center rounded-md border',
            step.kind === 'refused'
              ? 'border-status-critical-border bg-status-critical-bg text-status-critical'
              : step.server === 'topology'
                ? 'border-provenance-rule-border bg-provenance-rule-bg text-provenance-rule'
                : 'border-border bg-secondary text-primary',
          )}
        >
          <Icon aria-hidden="true" className="size-4" />
        </span>
        {!last && <span aria-hidden="true" className="w-px flex-1 bg-border" />}
      </div>

      <div
        className={cn(
          'mb-3 min-w-0 flex-1 rounded-md border px-3 py-2.5 transition-colors duration-500',
          focused ? 'border-primary bg-secondary/60' : 'border-transparent',
        )}
      >
        <p className="text-sm font-medium">{step.sentence}</p>
        {step.why && (
          <p className="mt-0.5 flex items-start gap-1.5 text-sm text-provenance-ai">
            <Sparkles aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
            <span>
              <span className="font-semibold">Why: </span>
              {step.why}
            </span>
          </p>
        )}
        <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
          {step.evidenceId && (
            <span className="rounded border bg-background px-1.5 py-px font-mono text-[11px] text-primary">
              {step.evidenceId}
            </span>
          )}
          {step.kind === 'refused' ? (
            <span className="font-medium text-status-critical">
              Blocked by the AINOPS safety check
            </span>
          ) : (
            <span>{step.server} MCP</span>
          )}
          <code className="rounded bg-muted px-1.5 py-px font-mono text-[11.5px] text-foreground">
            {step.tool}
          </code>
          {step.device &&
            (onSelectDevice ? (
              <button
                type="button"
                onClick={() => onSelectDevice(step.device as string)}
                className="rounded font-medium text-foreground underline-offset-2 hover:underline focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
              >
                {step.device}
              </button>
            ) : (
              <span className="font-medium text-foreground">{step.device}</span>
            ))}
          {details && <span className="font-mono">{details}</span>}
        </div>

        <div className="mt-1.5 flex items-start justify-between gap-3">
          <p className="flex min-w-0 items-start gap-1.5 text-sm">
            {step.state === 'running' ? (
              <Loader2
                aria-hidden="true"
                className="mt-0.5 size-4 shrink-0 animate-spin text-primary motion-reduce:animate-none"
              />
            ) : step.state === 'ok' && step.health?.status === 'problem' ? (
              <TriangleAlert
                aria-hidden="true"
                className="mt-0.5 size-4 shrink-0 text-status-warning"
              />
            ) : step.state === 'ok' ? (
              <CircleCheck
                aria-hidden="true"
                className="mt-0.5 size-4 shrink-0 text-status-healthy"
              />
            ) : (
              <CircleX aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-status-critical" />
            )}
            <span className={cn(step.state === 'running' && 'text-muted-foreground')}>
              {step.state === 'running' ? 'Running…' : step.summary}
              {step.health?.status === 'problem' && (
                <span className="block font-medium text-status-warning">
                  Problem found: {step.health.issues.map((i) => i.text).join('; ')}
                </span>
              )}
            </span>
          </p>
          <span className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
            {step.evidence && (
              <Badge
                variant="outline"
                className={cn(
                  'h-5 px-1.5 text-[10.5px] font-medium uppercase',
                  step.evidence.source === 'live' ? 'text-status-healthy' : 'text-status-warning',
                )}
              >
                {step.evidence.source}
              </Badge>
            )}
            {formatMs(step.durationMs)}
          </span>
        </div>

        {step.state !== 'running' &&
          step.kind === 'tool' &&
          (step.data !== null || step.evidence) && (
            <div className="mt-1.5">
              <button
                type="button"
                onClick={() => setOpen((value) => !value)}
                aria-expanded={open}
                className="flex items-center gap-1 rounded text-xs text-primary hover:underline focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
              >
                <ChevronDown
                  aria-hidden="true"
                  className={cn('size-3.5 transition-transform', open && 'rotate-180')}
                />
                {open ? 'Hide' : 'Show'} evidence
              </button>
              {open && (
                <div className="mt-2 space-y-2">
                  {step.evidence && (
                    <p className="text-xs text-muted-foreground">
                      Command run by the MCP server:{' '}
                      <code className="rounded bg-muted px-1.5 py-px font-mono text-foreground">
                        {step.evidence.command}
                      </code>{' '}
                      (never shown to the AI)
                    </p>
                  )}
                  <JsonView value={step.data} />
                </div>
              )}
            </div>
          )}
      </div>
    </li>
  )
}

export function Timeline({
  steps,
  focused,
  onSelectDevice,
}: {
  steps: Step[]
  focused: string | null
  onSelectDevice?: (device: string) => void
}) {
  return (
    <ol aria-label="Investigation steps">
      {steps.map((step, index) => (
        <StepItem
          key={step.key}
          step={step}
          focused={focused !== null && focused === step.evidenceId}
          last={index === steps.length - 1}
          onSelectDevice={onSelectDevice}
        />
      ))}
    </ol>
  )
}
