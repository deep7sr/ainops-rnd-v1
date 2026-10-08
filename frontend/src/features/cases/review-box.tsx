import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Check, Loader2, Pencil, X, type LucideIcon } from 'lucide-react'
import { useState } from 'react'
import { api, type Case, type CaseReview, type ReviewRequest } from '@/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import { rememberName, savedName } from '@/lib/your-name'
import { missing } from './review-rules'

// "Was this diagnosis right?" The engineer approves the case, corrects it, or rejects it. The same
// box sits under the report on the Investigate page and on the Cases page. The server checks
// every rule again (backend cases.py); this box only helps fill it in.

type Action = CaseReview['action']
type Worked = NonNullable<CaseReview['fix_worked']>

const CHOICES: { action: Action; label: string; icon: LucideIcon }[] = [
  { action: 'approve', label: 'Yes, approve', icon: Check },
  { action: 'correct', label: 'Correct it', icon: Pencil },
  { action: 'reject', label: 'No, reject', icon: X },
]

const WORKED: { value: Worked; label: string }[] = [
  { value: 'yes', label: 'Yes' },
  { value: 'no', label: 'No' },
  { value: 'unknown', label: 'Not known yet' },
]

const fieldLabel = 'text-xs font-semibold text-foreground'

export function ReviewBox({
  item,
  onReviewed,
  heading = 'Was this diagnosis right?',
}: {
  item: Case
  onReviewed?: (reviewed: Case) => void
  heading?: string
}) {
  const hasRootCause = Boolean(item.draft.root_cause)
  // A case without a root cause (made by hand) can only be corrected or rejected.
  const [action, setAction] = useState<Action | null>(hasRootCause ? null : 'correct')
  const [reviewer, setReviewer] = useState(savedName)
  const [rootCause, setRootCause] = useState(item.draft.root_cause ?? '')
  const [fixApplied, setFixApplied] = useState('')
  const [worked, setWorked] = useState<Worked | null>(null)
  const [reason, setReason] = useState('')
  const queryClient = useQueryClient()

  const form: ReviewRequest = {
    action: action ?? 'approve',
    reviewer,
    ...(action === 'correct' ? { root_cause: rootCause } : {}),
    ...(action !== 'reject' && fixApplied.trim() ? { fix_applied: fixApplied } : {}),
    ...(action !== 'reject' && worked ? { fix_worked: worked } : {}),
    ...(action === 'reject' ? { reason } : {}),
  }
  const problem = missing(action, form)
  const save = useMutation({
    mutationFn: () => api.reviewCase(item.id, form),
    onSuccess: (reviewed) => {
      rememberName(reviewer.trim())
      void queryClient.invalidateQueries({ queryKey: ['cases'] })
      void queryClient.invalidateQueries({ queryKey: ['investigations'] })
      void queryClient.invalidateQueries({ queryKey: ['run-case', item.run_id] })
      onReviewed?.(reviewed)
    },
  })

  return (
    <section aria-label="Review this case" className="space-y-3 rounded-lg border bg-card p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold">{heading}</h2>
        <p className="text-xs text-muted-foreground">
          Approved cases teach AINOPS. Pending until an engineer reviews it.
        </p>
      </div>

      <div role="group" aria-label="Your review" className="flex flex-wrap gap-2">
        {CHOICES.map(({ action: choice, label, icon: Icon }) => {
          const blocked = choice === 'approve' && !hasRootCause
          return (
            <Button
              key={choice}
              type="button"
              variant={action === choice ? 'default' : 'outline'}
              size="sm"
              aria-pressed={action === choice}
              disabled={blocked}
              title={
                blocked ? 'AINOPS found no root cause: correct it with the real one' : undefined
              }
              onClick={() => setAction(choice)}
            >
              <Icon aria-hidden="true" /> {label}
            </Button>
          )
        })}
      </div>

      {action === 'correct' && (
        <div className="space-y-1">
          <label htmlFor={`root-cause-${item.id}`} className={fieldLabel}>
            The real root cause
          </label>
          <Textarea
            id={`root-cause-${item.id}`}
            value={rootCause}
            onChange={(event) => setRootCause(event.target.value)}
            maxLength={500}
            className="min-h-16 text-sm"
          />
          {hasRootCause && (
            <p className="text-xs text-muted-foreground">
              What AINOPS said is kept next to your correction.
            </p>
          )}
        </div>
      )}

      {action === 'reject' && (
        <div className="space-y-1">
          <label htmlFor={`reason-${item.id}`} className={fieldLabel}>
            Why is it wrong?
          </label>
          <Textarea
            id={`reason-${item.id}`}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            maxLength={500}
            placeholder="e.g. the fault was on the far-end router, not this one"
            className="min-h-16 text-sm"
          />
        </div>
      )}

      {(action === 'approve' || action === 'correct') && (
        <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto]">
          <div className="space-y-1">
            <label htmlFor={`fix-${item.id}`} className={fieldLabel}>
              Fix applied <span className="font-normal text-muted-foreground">(optional)</span>
            </label>
            <Input
              id={`fix-${item.id}`}
              value={fixApplied}
              onChange={(event) => setFixApplied(event.target.value)}
              maxLength={500}
              placeholder="e.g. no shutdown on Fa2/0"
            />
          </div>
          <fieldset className="space-y-1">
            <legend className={fieldLabel}>Did it work?</legend>
            <div className="flex gap-1">
              {WORKED.map(({ value, label }) => (
                <Button
                  key={value}
                  type="button"
                  size="sm"
                  variant={worked === value ? 'secondary' : 'ghost'}
                  aria-pressed={worked === value}
                  onClick={() => setWorked(worked === value ? null : value)}
                  className={cn(worked === value && 'ring-1 ring-primary/40')}
                >
                  {label}
                </Button>
              ))}
            </div>
          </fieldset>
        </div>
      )}

      <form
        onSubmit={(event) => {
          event.preventDefault()
          if (!problem && !save.isPending) save.mutate()
        }}
        className="flex flex-wrap items-end gap-3 border-t pt-3"
      >
        <div className="min-w-48 flex-1 space-y-1">
          <label htmlFor={`reviewer-${item.id}`} className={fieldLabel}>
            Your name
          </label>
          <Input
            id={`reviewer-${item.id}`}
            value={reviewer}
            onChange={(event) => setReviewer(event.target.value)}
            maxLength={80}
            autoComplete="name"
          />
        </div>
        <Button type="submit" disabled={Boolean(problem) || save.isPending}>
          {save.isPending && (
            <Loader2 aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
          )}
          Save review
        </Button>
      </form>
      {save.isError ? (
        <p role="alert" className="text-sm text-status-critical">
          Not saved: {save.error.message}
        </p>
      ) : (
        action && problem && <p className="text-xs text-muted-foreground">{problem}</p>
      )}
    </section>
  )
}
