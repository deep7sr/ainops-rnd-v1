import { ArrowRight, CircleCheck, CircleX, Clock, Sparkles, UserRound, Wrench } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import type { Case, CaseStatus } from '@/api'
import { formatMs, formatTokens } from '@/features/investigate/format'
import { cn } from '@/lib/utils'

// One case: what AINOPS concluded and the proof, the engineer's review, and how the conversation
// went. What the AI said and what the engineer corrected are always shown apart.

const STATUS: Record<CaseStatus, { label: string; className: string; icon: typeof Clock }> = {
  pending: {
    label: 'Pending review',
    className: 'border-status-warning-border bg-status-warning-bg text-status-warning',
    icon: Clock,
  },
  approved: {
    label: 'Approved',
    className: 'border-status-healthy-border bg-status-healthy-bg text-status-healthy',
    icon: CircleCheck,
  },
  rejected: {
    label: 'Rejected',
    className: 'border-status-unknown-border bg-status-unknown-bg text-status-unknown',
    icon: CircleX,
  },
}

export function CaseStatusBadge({ status }: { status: CaseStatus }) {
  const { label, className, icon: Icon } = STATUS[status]
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] font-semibold',
        className,
      )}
    >
      <Icon aria-hidden="true" className="size-3" />
      {label}
    </span>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <h3 className="text-xs font-semibold tracking-wider text-eyebrow uppercase">{title}</h3>
      <div className="mt-1.5 text-sm">{children}</div>
    </div>
  )
}

const WORKED = { yes: 'it worked', no: 'it did not work', unknown: 'not known yet' } as const

export function CaseView({ item }: { item: Case }) {
  const { draft, review } = item
  const corrected = review?.action === 'correct' && review.root_cause
  return (
    <article aria-label={`Case ${item.id}`} className="space-y-5">
      <header className="space-y-2">
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <CaseStatusBadge status={item.status} />
          <span>
            {item.made_by === 'engineer' ? 'Made by an engineer' : 'Drafted by AINOPS'} ·{' '}
            {new Date(item.created_at).toLocaleString()}
          </span>
        </div>
        <h2 className="text-lg font-semibold text-balance">{item.question}</h2>
        <Link
          to={`/investigations/${item.run_id}`}
          className="inline-flex items-center gap-1 text-sm font-medium text-primary underline-offset-4 hover:underline"
        >
          See how AINOPS worked it out <ArrowRight aria-hidden="true" className="size-3.5" />
        </Link>
      </header>

      {review && (
        <div
          className={cn(
            'rounded-md border px-4 py-3 text-sm',
            item.status === 'approved'
              ? 'border-status-healthy-border bg-status-healthy-bg/50'
              : 'bg-muted/40',
          )}
        >
          <p className="flex items-center gap-1.5 font-medium">
            <UserRound aria-hidden="true" className="size-4" />
            {review.action === 'reject'
              ? 'Rejected'
              : review.action === 'correct'
                ? 'Corrected and approved'
                : 'Approved'}{' '}
            by {review.reviewer} · {new Date(review.at).toLocaleString()}
          </p>
          {review.reason && <p className="mt-1">Why: {review.reason}</p>}
          {review.fix_applied && (
            <p className="mt-1">
              Fix applied: {review.fix_applied}
              {review.fix_worked && ` (${WORKED[review.fix_worked]})`}
            </p>
          )}
        </div>
      )}

      <div className={cn('grid gap-3', corrected && 'sm:grid-cols-2')}>
        {corrected && (
          <div className="rounded-md border border-status-healthy-border bg-status-healthy-bg/40 px-4 py-3">
            <p className="text-xs font-semibold tracking-wider text-status-healthy uppercase">
              Root cause (engineer)
            </p>
            <p className="mt-1 text-sm font-medium">{review.root_cause}</p>
          </div>
        )}
        <div className="rounded-md border px-4 py-3">
          <p className="flex items-center gap-1.5 text-xs font-semibold tracking-wider text-eyebrow uppercase">
            <Sparkles aria-hidden="true" className="size-3.5 text-provenance-ai" />
            {corrected ? 'AINOPS said' : 'Root cause (AINOPS)'}
          </p>
          <p className="mt-1 text-sm font-medium">
            {draft.root_cause ?? 'No root cause found: ' + draft.summary}
          </p>
          {draft.confidence && (
            <p className="mt-1 text-xs text-muted-foreground">{draft.confidence} confidence</p>
          )}
        </div>
      </div>

      {draft.evidence.length > 0 && (
        <Section title="Proof (from the live devices)">
          <ul className="space-y-1.5">
            {draft.evidence.map((e) => (
              <li key={e.id} className="flex gap-2">
                <span className="mt-px shrink-0 rounded border px-1 font-mono text-[11px] text-primary">
                  {e.id}
                </span>
                <span>
                  <span className="font-mono text-xs">{e.tool}</span>
                  {e.device && <span className="font-medium"> {e.device}</span>}: {e.summary}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      <div className="grid gap-5 sm:grid-cols-2">
        {(draft.devices.length > 0 || draft.interfaces.length > 0) && (
          <Section title="Devices">
            <p className="flex flex-wrap gap-1.5">
              {(draft.interfaces.length > 0 ? draft.interfaces : draft.devices).map((name) => (
                <span key={name} className="rounded border bg-muted/40 px-1.5 py-0.5 text-xs">
                  {name}
                </span>
              ))}
            </p>
          </Section>
        )}
        {draft.path.length > 0 && (
          <Section title="Path">
            <p>{draft.path.join(' → ')}</p>
            {draft.path_note && <p className="text-xs text-muted-foreground">{draft.path_note}</p>}
          </Section>
        )}
        {draft.skills.length > 0 && <Section title="Skill used">{draft.skills.join(', ')}</Section>}
        <Section title="Investigation cost">
          {item.checks} check{item.checks === 1 ? '' : 's'} · {formatMs(item.duration_ms)}
          {item.tokens > 0 && ` · ${formatTokens(item.tokens)}`}
        </Section>
        {item.hints_offered.length > 0 && (
          <Section title="Past cases offered as hints">
            <p className="flex flex-wrap gap-2">
              {item.hints_offered.map((id) => (
                <Link
                  key={id}
                  to={`/cases/${id}`}
                  className="text-primary underline-offset-4 hover:underline"
                >
                  {id}
                </Link>
              ))}
            </p>
          </Section>
        )}
      </div>

      {draft.suggested_fix.length > 0 && (
        <Section title="Fix AINOPS suggested">
          <ul className="space-y-1">
            {draft.suggested_fix.map((text) => (
              <li key={text} className="flex gap-1.5">
                <Wrench aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" /> {text}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {item.conversation.length > 1 && (
        <Section title="How the conversation went">
          <ol className="space-y-2">
            {item.conversation.map((exchange, index) => (
              <li key={index} className="rounded-md border px-3 py-2">
                <p className="text-xs text-muted-foreground">
                  {index === 0 ? 'Question' : `Engineer, message ${index + 1}`}
                </p>
                <p>{exchange.message}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  AINOPS:{' '}
                  {exchange.outcome
                    ? (exchange.root_cause ?? exchange.outcome.replaceAll('_', ' '))
                    : 'stopped before it finished'}
                </p>
              </li>
            ))}
          </ol>
        </Section>
      )}
    </article>
  )
}
