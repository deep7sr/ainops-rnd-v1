import {
  BookOpenCheck,
  ChevronDown,
  CircleCheck,
  CircleX,
  Lightbulb,
  Loader2,
  Network,
  Router,
  SearchCheck,
  ShieldX,
  Sparkles,
  TriangleAlert,
  type LucideIcon,
} from 'lucide-react'
import { Fragment, useState } from 'react'
import { Link } from 'react-router'
import type { HintCase } from '@/api'
import { JsonView } from '@/components/json-view'
import { SkillBadge } from '@/features/skills/skill-badges'
import { StepText } from '@/features/skills/step-text'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { Step } from './derive'
import { formatMs } from './format'
import { readTrace } from './trace'
import { TraceHops } from './trace-hops'

const SERVER_ICON: Record<string, LucideIcon> = { topology: Network, network: Router }

function argText(args: Record<string, unknown>): string {
  return Object.entries(args)
    .filter(([key]) => key !== 'device')
    .map(([key, value]) => `${key}=${String(value)}`)
    .join(' ')
}

/** The agent opened an expert skill: which one, why, and the steps it will follow. */
function SkillItem({ step, last }: { step: Step; last: boolean }) {
  const steps = Array.isArray(step.data) ? (step.data as string[]) : []
  return (
    <li className="flex gap-3">
      <div className="flex flex-col items-center">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-md border border-provenance-ai/40 bg-secondary text-provenance-ai">
          <BookOpenCheck aria-hidden="true" className="size-4" />
        </span>
        {!last && <span aria-hidden="true" className="w-px flex-1 bg-border" />}
      </div>
      <div className="mb-3 min-w-0 flex-1 rounded-md border border-transparent px-3 py-2.5">
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
        <div className="mt-2 rounded-md border bg-background/60 px-3 py-2 text-sm">
          <p className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <SkillBadge
              status={String(step.args.status ?? '')}
              reviewedBy={String(step.args.reviewed_by ?? '')}
            />
            {step.summary}
          </p>
          <ol aria-label={`Steps of the skill`} className="mt-1.5 space-y-1">
            {steps.map((text, index) => (
              <li key={index} className="flex gap-2">
                <span className="w-4 shrink-0 text-right font-mono text-xs leading-5 text-muted-foreground">
                  {index + 1}
                </span>
                <span className="min-w-0">
                  <StepText text={text} />
                </span>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </li>
  )
}

const WORKED = { yes: ' (it worked)', no: ' (it did not work)', unknown: '' } as const

/** AINOPS's own check before answering: an unproven root cause was sent back to be checked. */
function RecheckItem({ step, last }: { step: Step; last: boolean }) {
  return (
    <li className="flex gap-3">
      <div className="flex flex-col items-center">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-md border border-status-warning-border bg-status-warning-bg text-status-warning">
          <SearchCheck aria-hidden="true" className="size-4" />
        </span>
        {!last && <span aria-hidden="true" className="w-px flex-1 bg-border" />}
      </div>
      <div className="mb-3 min-w-0 flex-1 px-3 py-2.5">
        <p className="text-sm font-medium">{step.sentence}</p>
        <p className="text-xs text-muted-foreground">{step.summary}</p>
      </div>
    </li>
  )
}

/** Similar past cases shown to the AI as hints. Dashed: a hint, never evidence. */
function HintsItem({ step, last }: { step: Step; last: boolean }) {
  const cases = Array.isArray(step.data) ? (step.data as HintCase[]) : []
  return (
    <li className="flex gap-3">
      <div className="flex flex-col items-center">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-md border border-dashed border-muted-foreground/60 bg-background text-muted-foreground">
          <Lightbulb aria-hidden="true" className="size-4" />
        </span>
        {!last && <span aria-hidden="true" className="w-px flex-1 bg-border" />}
      </div>
      <div className="mb-3 min-w-0 flex-1 px-3 py-2.5">
        <p className="text-sm font-medium">{step.sentence}</p>
        <p className="text-xs text-muted-foreground">{step.summary}</p>
        {cases.length > 0 && (
          <ul aria-label="Similar past cases" className="mt-2 space-y-2">
            {cases.map((hint) => (
              <li
                key={hint.case_id}
                className="rounded-md border border-dashed bg-background/60 px-3 py-2 text-sm"
              >
                <p className="text-xs text-muted-foreground">
                  <Link
                    to={`/cases/${hint.case_id}`}
                    className="font-mono text-primary underline-offset-4 hover:underline"
                  >
                    {hint.case_id}
                  </Link>{' '}
                  · approved by {hint.reviewer || 'an engineer'} · “{hint.question}”
                </p>
                <p className="mt-1">
                  <span className="font-medium">
                    {hint.corrected ? 'Root cause (engineer): ' : 'Root cause: '}
                  </span>
                  {hint.root_cause}
                </p>
                {hint.fix && (
                  <p className="text-xs text-muted-foreground">
                    Fix: {hint.fix}
                    {hint.fix_worked ? WORKED[hint.fix_worked] : ''}
                  </p>
                )}
                <p className="mt-1 text-xs text-muted-foreground">
                  Similar because: {hint.reasons.join('; ')}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </li>
  )
}

/** Which step of the open skill a check carries out, or that it goes beyond the skill. */
function SkillStepTag({ step }: { step: number | null }) {
  if (step === null) return null
  return step > 0 ? (
    <span className="rounded border border-provenance-ai/40 px-1.5 py-px text-[11px] font-medium text-provenance-ai">
      Skill step {step}
    </span>
  ) : (
    <span className="rounded border px-1.5 py-px text-[11px] font-medium text-muted-foreground">
      Beyond the skill
    </span>
  )
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
  const trace = step.tool === 'trace_route' && step.state === 'ok' ? readTrace(step.data) : null

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
          <SkillStepTag step={step.skillStep} />
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

        {trace && <TraceHops trace={trace} />}

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
        <Fragment key={step.key}>
          {/* The checks for a follow-up message start under a divider naming that message. */}
          {step.turn > 1 && step.turn !== steps[index - 1]?.turn && (
            <li className="my-3 flex items-center gap-2 text-xs font-medium text-muted-foreground">
              <span aria-hidden="true" className="h-px flex-1 bg-border" />
              For your message {step.turn}
              <span aria-hidden="true" className="h-px flex-1 bg-border" />
            </li>
          )}
          {step.kind === 'skill' ? (
            <SkillItem step={step} last={index === steps.length - 1} />
          ) : step.kind === 'hints' ? (
            <HintsItem step={step} last={index === steps.length - 1} />
          ) : step.kind === 'recheck' ? (
            <RecheckItem step={step} last={index === steps.length - 1} />
          ) : (
            <StepItem
              step={step}
              focused={focused !== null && focused === step.evidenceId}
              last={index === steps.length - 1}
              onSelectDevice={onSelectDevice}
            />
          )}
        </Fragment>
      ))}
    </ol>
  )
}
