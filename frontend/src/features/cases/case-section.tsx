import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, ClipboardPlus, Loader2 } from 'lucide-react'
import { useEffect } from 'react'
import { Link } from 'react-router'
import { api, type Report } from '@/api'
import { Button } from '@/components/ui/button'
import { CaseStatusBadge } from './case-view'
import { ReviewBox } from './review-box'

// Under the latest report on the Investigate page: the conversation's case. Pending: the review
// box, so the engineer reviews right where they read the answer. Reviewed: who did what. No case
// yet after an inconclusive or healthy reply: a button to make one and write the real cause.

const MAKE_TEXT: Partial<Record<Report['outcome'], string>> = {
  inconclusive: 'AINOPS could not find the cause. If you know it, make a case so AINOPS can learn.',
  no_fault_found:
    'AINOPS found no fault. If there was one after all, make a case and write the real cause.',
  diagnosed: 'This diagnosis has no case yet.',
}

const caseLink =
  'inline-flex items-center gap-1 font-medium text-primary underline-offset-4 hover:underline'

export function CaseSection({
  runId,
  outcome,
  caseEvents,
  notSaved,
}: {
  runId: string
  /** How the latest reply ended. */
  outcome: Report['outcome'] | null
  /** How many case events the run has sent: a new one means the case changed. */
  caseEvents: number
  /** Why the latest reply's case could not be saved, if it could not. */
  notSaved: string | null
}) {
  const queryClient = useQueryClient()
  const found = useQuery({ queryKey: ['run-case', runId], queryFn: () => api.runCase(runId) })
  useEffect(() => {
    void queryClient.invalidateQueries({ queryKey: ['run-case', runId] })
  }, [caseEvents, outcome, runId, queryClient])
  const make = useMutation({
    mutationFn: () => api.makeCase(runId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['run-case', runId] })
      void queryClient.invalidateQueries({ queryKey: ['cases'] })
    },
  })

  if (notSaved) {
    return (
      <p role="alert" className="rounded-lg border px-4 py-3 text-sm text-status-critical">
        The case for this diagnosis was not saved ({notSaved.replace(/^case not saved: /, '')}). The
        diagnosis above stands; make the case later from History.
      </p>
    )
  }
  const item = found.data?.case
  if (item?.status === 'pending') {
    return (
      <div className="space-y-1.5">
        <ReviewBox key={`${item.id}-${item.updated_at}`} item={item} />
        <p className="text-xs text-muted-foreground">
          <Link to={`/cases/${item.id}`} className={caseLink}>
            Open the case <ArrowRight aria-hidden="true" className="size-3" />
          </Link>
        </p>
      </div>
    )
  }
  if (item) {
    return (
      <div className="flex flex-wrap items-center gap-2 rounded-lg border bg-card px-4 py-3 text-sm">
        <CaseStatusBadge status={item.status} />
        {item.review && (
          <span>
            by {item.review.reviewer}
            {item.review.action === 'correct' && ', with a corrected root cause'}
          </span>
        )}
        <Link to={`/cases/${item.id}`} className={`ml-auto ${caseLink}`}>
          Open the case <ArrowRight aria-hidden="true" className="size-3" />
        </Link>
      </div>
    )
  }
  if (found.data?.can_make && outcome && MAKE_TEXT[outcome]) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-card px-4 py-3">
        <p className="text-sm text-muted-foreground">{MAKE_TEXT[outcome]}</p>
        <Button variant="outline" size="sm" onClick={() => make.mutate()} disabled={make.isPending}>
          {make.isPending ? (
            <Loader2 aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
          ) : (
            <ClipboardPlus aria-hidden="true" />
          )}
          Make a case
        </Button>
        {make.isError && (
          <p role="alert" className="w-full text-sm text-status-critical">
            Not made: {make.error.message}
          </p>
        )}
      </div>
    )
  }
  return null
}
