import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { api, type Case, type CaseStatus } from '@/api'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import { CaseView } from './case-view'
import { ReviewBox } from './review-box'

// Cases waiting for review, and the ones already reviewed. After a review the page moves on to
// the next pending case, so an engineer can work through them without going back to the list.

const TABS: { status: CaseStatus; label: string }[] = [
  { status: 'pending', label: 'Pending review' },
  { status: 'approved', label: 'Approved' },
  { status: 'rejected', label: 'Rejected' },
]

const EMPTY: Record<CaseStatus, string> = {
  pending:
    'Nothing waiting for review. AINOPS drafts a case after each diagnosis; you can also make one from an investigation.',
  approved: 'No approved cases yet.',
  rejected: 'No rejected cases.',
}

function CaseRow({ item, selected }: { item: Case; selected: boolean }) {
  return (
    <li>
      <Link
        to={`/cases/${item.id}`}
        aria-current={selected ? 'true' : undefined}
        className={cn(
          'block space-y-0.5 px-4 py-3 hover:bg-accent focus-visible:bg-accent focus-visible:outline-none',
          selected && 'bg-secondary',
        )}
      >
        <span className="line-clamp-2 text-sm font-medium">{item.question}</span>
        <span className="line-clamp-1 text-xs text-muted-foreground">
          {item.root_cause ?? 'No root cause yet: needs the real cause'}
        </span>
        <span className="block text-xs text-muted-foreground">
          {item.draft.devices.join(', ') || 'no device named'} ·{' '}
          {new Date(item.created_at).toLocaleDateString()}
        </span>
      </Link>
    </li>
  )
}

export function CasesPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [tab, setTab] = useState<CaseStatus | null>(null)
  const opened = useQuery({
    queryKey: ['cases', 'one', id],
    queryFn: () => api.case(id as string),
    enabled: Boolean(id),
  })
  // Opened from a link: show the tab the case is in.
  const status = tab ?? opened.data?.status ?? 'pending'
  const list = useQuery({ queryKey: ['cases', status], queryFn: () => api.cases(status) })
  const shown = id ? opened.data : list.data?.cases[0]

  const next = (reviewed: Case) => {
    const others = (list.data?.cases ?? []).filter(
      (c) => c.id !== reviewed.id && c.status === 'pending',
    )
    setTab('pending')
    void navigate(others[0] ? `/cases/${others[0].id}` : '/cases')
  }

  return (
    <div className="mx-auto max-w-6xl space-y-5 px-6 py-6">
      <div>
        <h1 className="text-xl font-semibold">Cases</h1>
        <p className="text-sm text-muted-foreground">
          What each investigation found, checked by an engineer. Only approved cases will be used to
          help AINOPS with similar problems later.
        </p>
      </div>

      <div role="tablist" aria-label="Cases by status" className="flex flex-wrap gap-2 border-b">
        {TABS.map(({ status: value, label }) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={status === value}
            onClick={() => {
              setTab(value)
              if (id) void navigate('/cases')
            }}
            className={cn(
              '-mb-px border-b-2 px-3 py-2 text-sm font-medium focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none',
              status === value
                ? 'border-primary text-foreground'
                : 'border-transparent text-muted-foreground hover:text-foreground',
            )}
          >
            {label}
            <span className="ml-1.5 rounded-full bg-muted px-1.5 text-xs tabular-nums">
              {list.data?.counts[value] ?? '–'}
            </span>
          </button>
        ))}
      </div>

      {list.isError ? (
        <p role="alert" className="text-sm text-status-critical">
          Could not load the cases: {list.error.message}
        </p>
      ) : list.isPending ? (
        <Skeleton className="h-64 w-full" />
      ) : (
        <div className="grid gap-5 lg:grid-cols-[320px_minmax(0,1fr)]">
          {list.data.cases.length === 0 ? (
            <p className="rounded-lg border border-dashed p-6 text-sm text-muted-foreground lg:col-span-2">
              {EMPTY[status]}
            </p>
          ) : (
            <ul
              aria-label={`${status} cases`}
              className="divide-y self-start rounded-lg border bg-card"
            >
              {list.data.cases.map((item) => (
                <CaseRow key={item.id} item={item} selected={item.id === shown?.id} />
              ))}
            </ul>
          )}
          {shown && (
            <div className="min-w-0 space-y-5 rounded-lg border bg-card p-5">
              <CaseView item={shown} />
              {shown.status === 'pending' && (
                <ReviewBox key={shown.id} item={shown} onReviewed={next} />
              )}
            </div>
          )}
          {id && opened.isError && (
            <p role="alert" className="text-sm text-status-critical">
              Could not open this case: {opened.error.message}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
