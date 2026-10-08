import {
  CircleCheck,
  CircleHelp,
  Info,
  ShieldX,
  Sparkles,
  TriangleAlert,
  Wrench,
  type LucideIcon,
} from 'lucide-react'
import type { Report } from '@/api'
import { cn } from '@/lib/utils'
import { needsEvidence, type Verdict } from './derive'
import { formatMs, formatTokens } from './format'

const OUTCOMES: Record<Report['outcome'], { label: string; icon: LucideIcon; className: string }> =
  {
    diagnosed: {
      label: 'Root cause found',
      icon: TriangleAlert,
      className: 'border-status-critical-border bg-status-critical-bg text-status-critical',
    },
    no_fault_found: {
      label: 'No fault found',
      icon: CircleCheck,
      className: 'border-status-healthy-border bg-status-healthy-bg text-status-healthy',
    },
    inconclusive: {
      label: 'Inconclusive',
      icon: CircleHelp,
      className: 'border-status-warning-border bg-status-warning-bg text-status-warning',
    },
    refused: {
      label: 'Refused: read-only',
      icon: ShieldX,
      className: 'border-status-unknown-border bg-status-unknown-bg text-status-unknown',
    },
    answered: {
      label: 'Answered',
      icon: Info,
      className: 'border-provenance-rule-border bg-provenance-rule-bg text-provenance-rule',
    },
  }

const CONFIDENCE_BARS = { high: 3, medium: 2, low: 1 } as const

/** "Root cause found", "No fault found"…: how a reply ended, as a coloured label. */
export function OutcomeBadge({ outcome }: { outcome: Report['outcome'] }) {
  const { label, icon: Icon, className } = OUTCOMES[outcome]
  return (
    <span
      className={cn(
        'flex shrink-0 items-center gap-1.5 rounded-md border px-2.5 py-1 text-sm font-semibold',
        className,
      )}
    >
      <Icon aria-hidden="true" className="size-4" />
      {label}
    </span>
  )
}

function EvidenceChips({ ids, onSelect }: { ids: string[]; onSelect: (id: string) => void }) {
  return (
    <>
      {ids.map((id) => (
        <button
          key={id}
          type="button"
          onClick={() => onSelect(id)}
          aria-label={`Show evidence ${id}`}
          className="ml-1 rounded border bg-background px-1 py-px align-baseline font-mono text-[11px] text-primary hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
        >
          {id}
        </button>
      ))}
    </>
  )
}

export function ReportCard({
  verdict,
  onSelectEvidence,
}: {
  verdict: Verdict
  onSelectEvidence: (id: string) => void
}) {
  const { report, confidence, reasons } = verdict
  // A refusal or a plain answer needs no network evidence: no confidence meter.
  const withEvidence = needsEvidence(report.outcome)

  return (
    <section aria-label="Diagnosis" className="rounded-lg border bg-card shadow-xs">
      <header className="flex flex-wrap items-center gap-3 border-b px-5 py-3">
        <OutcomeBadge outcome={report.outcome} />
        {withEvidence && (
          <span className="flex items-center gap-2 text-sm" title={reasons.join('\n')}>
            <span className="flex items-end gap-0.5" aria-hidden="true">
              {[1, 2, 3].map((bar) => (
                <span
                  key={bar}
                  className={cn(
                    'w-1.5 rounded-sm',
                    bar === 1 ? 'h-2' : bar === 2 ? 'h-3' : 'h-4',
                    bar <= CONFIDENCE_BARS[confidence] ? 'bg-primary' : 'bg-border',
                  )}
                />
              ))}
            </span>
            <span className="font-medium capitalize">{confidence} confidence</span>
          </span>
        )}
        <span className="ml-auto flex items-center gap-1.5 text-xs text-muted-foreground">
          <Sparkles aria-hidden="true" className="size-3.5 text-provenance-ai" />
          {verdict.toolCalls} tool calls · {formatMs(verdict.atMs)}
          {verdict.tokens && verdict.tokens.input + verdict.tokens.output > 0 && (
            <> · {formatTokens(verdict.tokens.input + verdict.tokens.output)}</>
          )}
        </span>
      </header>

      <div className="space-y-5 px-5 py-4">
        <p className="text-[15px] leading-relaxed">{report.summary}</p>

        {report.root_cause && (
          <div className="rounded-md border border-status-critical-border bg-status-critical-bg/60 px-4 py-3">
            <p className="text-xs font-semibold tracking-wider text-status-critical uppercase">
              Root cause
            </p>
            <p className="mt-1 text-sm font-medium">
              {report.root_cause}
              <EvidenceChips ids={report.root_cause_evidence} onSelect={onSelectEvidence} />
            </p>
            {report.affected.length > 0 && (
              <p className="mt-1 text-xs text-muted-foreground">
                Affected: {report.affected.join(' · ')}
              </p>
            )}
          </div>
        )}

        {report.findings.length > 0 && (
          <div>
            <h3 className="text-xs font-semibold tracking-wider text-eyebrow uppercase">
              What the evidence shows
            </h3>
            <ul className="mt-2 space-y-1.5">
              {report.findings.map((finding, index) => (
                <li key={index} className="flex gap-2 text-sm">
                  <span
                    aria-hidden="true"
                    className="mt-2 size-1 shrink-0 rounded-full bg-muted-foreground"
                  />
                  <span>
                    {finding.text}
                    <EvidenceChips ids={finding.evidence} onSelect={onSelectEvidence} />
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {report.next_steps.length > 0 && (
          <div>
            <h3 className="text-xs font-semibold tracking-wider text-eyebrow uppercase">
              Recommended next steps
            </h3>
            <ol className="mt-2 space-y-1.5">
              {report.next_steps.map((step, index) => (
                <li key={index} className="flex items-start gap-2 text-sm">
                  <span
                    className={cn(
                      'mt-px flex shrink-0 items-center gap-1 rounded border px-1.5 py-px text-[10.5px] font-semibold uppercase',
                      step.kind === 'fix'
                        ? 'border-status-warning-border text-status-warning'
                        : step.kind === 'escalate'
                          ? 'border-status-critical-border text-status-critical'
                          : 'border-border text-muted-foreground',
                    )}
                  >
                    {step.kind === 'fix' && <Wrench aria-hidden="true" className="size-3" />}
                    {step.kind}
                  </span>
                  <span>{step.text}</span>
                </li>
              ))}
            </ol>
            {report.next_steps.some((s) => s.kind === 'fix') && (
              <p className="mt-2 text-xs text-muted-foreground">
                AINOPS is read-only: a fix is a suggestion for an engineer, never applied by AINOPS.
              </p>
            )}
          </div>
        )}

        <div className="grid gap-4 border-t pt-4 text-xs text-muted-foreground sm:grid-cols-2">
          {withEvidence && (
            <div>
              <p className="font-semibold text-foreground">Why this confidence</p>
              <ul className="mt-1 list-disc space-y-0.5 pl-4">
                {reasons.map((reason, index) => (
                  <li key={index}>{reason}</li>
                ))}
              </ul>
              <p className="mt-1">Computed by code from the evidence, not by the AI.</p>
            </div>
          )}
          {report.limitations.length > 0 && (
            <div>
              <p className="font-semibold text-foreground">Not checked</p>
              <ul className="mt-1 list-disc space-y-0.5 pl-4">
                {report.limitations.map((item, index) => (
                  <li key={index}>{item}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </section>
  )
}
