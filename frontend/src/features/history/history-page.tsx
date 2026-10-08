import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { api } from '@/api'
import { Skeleton } from '@/components/ui/skeleton'
import { CaseStatusBadge } from '@/features/cases/case-view'
import { formatMs } from '@/features/investigate/format'

export function HistoryPage() {
  const runs = useQuery({ queryKey: ['investigations'], queryFn: api.investigations })

  return (
    <div className="mx-auto max-w-5xl space-y-5 px-6 py-6">
      <div>
        <h1 className="text-xl font-semibold">History</h1>
        <p className="text-sm text-muted-foreground">
          Past investigations. Open one to replay every step, the evidence and the diagnosis, or to
          go on with the conversation.
        </p>
      </div>
      {runs.isPending ? (
        <Skeleton className="h-64 w-full" />
      ) : runs.isError ? (
        <p role="alert" className="text-sm text-status-critical">
          Could not load the history: {runs.error.message}
        </p>
      ) : runs.data.length === 0 ? (
        <p className="rounded-lg border border-dashed p-10 text-center text-sm text-muted-foreground">
          No investigations yet. Ask a question on the Investigate page.
        </p>
      ) : (
        <ul className="divide-y rounded-lg border bg-card">
          {runs.data.map((run) => (
            <li key={run.id}>
              <Link
                to={`/investigations/${run.id}`}
                className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 px-4 py-3 hover:bg-accent focus-visible:bg-accent focus-visible:outline-none sm:grid-cols-[minmax(0,1fr)_140px_110px_80px]"
              >
                <span className="truncate font-medium">{run.title}</span>
                <span className="text-sm text-muted-foreground capitalize">
                  {run.outcome?.replaceAll('_', ' ') ?? 'running…'}
                </span>
                <span className="hidden text-sm text-muted-foreground capitalize sm:block">
                  {run.confidence ? `${run.confidence} confidence` : ''}
                </span>
                <span className="hidden text-right text-sm text-muted-foreground tabular-nums sm:block">
                  {formatMs(run.duration_ms)}
                </span>
                <span className="col-span-full text-xs text-muted-foreground">
                  {new Date(run.started_at).toLocaleString()}
                  {(run.messages ?? 1) > 1 && ` · conversation of ${run.messages} messages`}
                  {run.case_status && (
                    <span className="ml-2 align-middle">
                      <CaseStatusBadge status={run.case_status} />
                    </span>
                  )}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
