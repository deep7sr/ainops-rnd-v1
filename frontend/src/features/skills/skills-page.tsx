import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, BookOpenCheck, Pencil, Plus, Search, TriangleAlert } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router'
import { api, type SkillCatalog, type SkillStatus } from '@/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import { shortDate, skillTitle } from './labels'
import { NeedsFixingBadge, SkillStatusBadge } from './skill-badges'
import { SkillHistory } from './skill-history'
import { RestoreVersion, SkillStatusPanel } from './skill-status'
import { BrokenSkillView, SkillView } from './skill-view'

// The expert skills: a list on the left, the opened skill on the right (each skill has its own
// link, /skills/<name>). On narrow screens the list and the opened skill take turns.

type Filter = 'all' | SkillStatus | 'broken'

const FILTERS: { filter: Filter; label: string }[] = [
  { filter: 'all', label: 'All' },
  { filter: 'live', label: 'Live' },
  { filter: 'draft', label: 'Drafts' },
  { filter: 'off', label: 'Off' },
  { filter: 'broken', label: 'Need fixing' },
]

type Entry =
  | { kind: 'skill'; skill: SkillCatalog['skills'][number] }
  | { kind: 'broken'; problem: SkillCatalog['problems'][number] }

function entryName(entry: Entry) {
  return entry.kind === 'skill' ? entry.skill.name : entry.problem.folder
}

function inFilter(entry: Entry, filter: Filter) {
  if (filter === 'all') return true
  if (entry.kind === 'broken') return filter === 'broken'
  return entry.skill.status === filter
}

function matches(entry: Entry, text: string) {
  const wanted = text.trim().toLowerCase()
  if (!wanted) return true
  const words =
    entry.kind === 'skill'
      ? [entry.skill.name, entry.skill.description, entry.skill.intro, ...entry.skill.tools]
      : [entry.problem.folder]
  return words.join(' ').toLowerCase().includes(wanted)
}

function Row({
  entry,
  selected,
  auto,
}: {
  entry: Entry
  selected: boolean
  /** Opened because nothing was chosen: shown as opened only where both columns show. */
  auto: boolean
}) {
  const name = entryName(entry)
  return (
    <li>
      <Link
        to={`/skills/${encodeURIComponent(name)}`}
        aria-current={selected ? 'true' : undefined}
        className={cn(
          'block space-y-1 border-l-2 px-4 py-3 hover:bg-accent focus-visible:bg-accent focus-visible:outline-none',
          selected && !auto && 'border-primary bg-secondary',
          selected && auto && 'border-transparent lg:border-primary lg:bg-secondary',
          !selected && 'border-transparent',
        )}
      >
        <span className="flex items-start justify-between gap-2">
          <span className="text-sm font-medium">{skillTitle(name)}</span>
          {entry.kind === 'broken' ? (
            <NeedsFixingBadge />
          ) : (
            <SkillStatusBadge status={entry.skill.status} />
          )}
        </span>
        {entry.kind === 'skill' ? (
          <>
            <span className="line-clamp-2 text-xs text-muted-foreground">
              {entry.skill.description}
            </span>
            <span className="block text-xs text-muted-foreground tabular-nums">
              {entry.skill.steps.length} {entry.skill.steps.length === 1 ? 'step' : 'steps'} ·{' '}
              {entry.skill.usage.count === 0
                ? 'not used yet'
                : `used ${entry.skill.usage.count}× · last ${shortDate(entry.skill.usage.last_at ?? '')}`}
            </span>
          </>
        ) : (
          <span className="line-clamp-2 text-xs text-status-critical">
            {entry.problem.problems[0]}
          </span>
        )}
      </Link>
    </li>
  )
}

export function SkillsView({
  catalog,
  selected: wanted,
}: {
  catalog: SkillCatalog
  /** The skill in the link; without one the first skill is opened (wide screens). */
  selected?: string
}) {
  const [filter, setFilter] = useState<Filter>('all')
  const [search, setSearch] = useState('')

  const entries = useMemo<Entry[]>(
    () => [
      ...catalog.skills.map((skill) => ({ kind: 'skill' as const, skill })),
      ...catalog.problems.map((problem) => ({ kind: 'broken' as const, problem })),
    ],
    [catalog],
  )
  const counts = Object.fromEntries(
    FILTERS.map(({ filter: f }) => [f, entries.filter((e) => inFilter(e, f)).length]),
  ) as Record<Filter, number>
  const shown = entries.filter((e) => inFilter(e, filter) && matches(e, search))
  const opened = wanted ? entries.find((e) => entryName(e) === wanted) : (shown[0] ?? entries[0])

  return (
    <div className="space-y-4">
      {!catalog.tools_checked && (
        <p role="status" className="flex items-start gap-2 text-sm text-status-warning">
          <TriangleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          The MCP servers are not running, so the tool names in the skills could not be checked.
        </p>
      )}

      {entries.length === 0 ? (
        <p className="rounded-lg border border-dashed p-6 text-sm text-muted-foreground">
          No skills yet. A skill is the checklist an experienced engineer follows for a common
          problem; AINOPS follows it too.
        </p>
      ) : (
        <div className="grid gap-5 lg:grid-cols-[340px_minmax(0,1fr)]">
          <div className={cn('space-y-3 self-start', wanted && 'hidden lg:block')}>
            <div className="relative">
              <Search
                aria-hidden="true"
                className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground"
              />
              <Input
                type="search"
                aria-label="Search skills"
                placeholder="Search skills or tools"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                className="pl-8"
              />
            </div>
            <div role="group" aria-label="Show" className="flex flex-wrap gap-1.5">
              {FILTERS.map(({ filter: value, label }) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={filter === value}
                  onClick={() => setFilter(value)}
                  className={cn(
                    'rounded-full border px-2.5 py-1 text-xs font-medium focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none',
                    filter === value
                      ? 'border-primary bg-primary text-primary-foreground'
                      : 'bg-card text-muted-foreground hover:text-foreground',
                  )}
                >
                  {label}
                  <span className="ml-1 tabular-nums opacity-80">{counts[value]}</span>
                </button>
              ))}
            </div>
            {shown.length === 0 ? (
              <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
                No skill matches.
              </p>
            ) : (
              <ul
                aria-label="Skills"
                className="divide-y overflow-hidden rounded-lg border bg-card"
              >
                {shown.map((entry) => (
                  <Row
                    key={entryName(entry)}
                    entry={entry}
                    selected={opened !== undefined && entryName(entry) === entryName(opened)}
                    auto={!wanted}
                  />
                ))}
              </ul>
            )}
          </div>

          <div className={cn('min-w-0 space-y-3', !wanted && 'hidden lg:block')}>
            {wanted && (
              <Link
                to="/skills"
                className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground lg:hidden"
              >
                <ArrowLeft aria-hidden="true" className="size-4" /> All skills
              </Link>
            )}
            <div className="rounded-lg border bg-card p-5 sm:p-6">
              {opened === undefined ? (
                <p role="alert" className="text-sm text-muted-foreground">
                  There is no skill named "{wanted}".
                </p>
              ) : opened.kind === 'skill' ? (
                <SkillView
                  skill={opened.skill}
                  usage={opened.skill.usage}
                  panel={<SkillStatusPanel skill={opened.skill} version={opened.skill.version} />}
                  actions={
                    <>
                      <Button asChild size="sm">
                        <Link to={`/skills/${encodeURIComponent(opened.skill.name)}/edit`}>
                          <Pencil aria-hidden="true" /> Edit
                        </Link>
                      </Button>
                      <SkillHistory
                        name={opened.skill.name}
                        actions={(entry, done) => (
                          <RestoreVersion
                            name={opened.skill.name}
                            entry={entry.id}
                            version={opened.skill.version}
                            onRestored={done}
                          />
                        )}
                      />
                    </>
                  }
                />
              ) : (
                <BrokenSkillView problem={opened.problem} />
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export function SkillsPage() {
  const { name } = useParams()
  const catalog = useQuery({ queryKey: ['skills'], queryFn: api.skills })
  const skills = catalog.data?.skills ?? []
  const live = skills.filter((s) => s.status === 'live').length
  const broken = catalog.data?.problems.length ?? 0
  return (
    <div className="mx-auto max-w-6xl space-y-5 px-6 py-6">
      <div className="space-y-1">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h1 className="flex items-center gap-2 text-xl font-semibold">
            <BookOpenCheck aria-hidden="true" className="size-5 text-primary" /> Skills
          </h1>
          <Button asChild>
            <Link to="/skills/new">
              <Plus aria-hidden="true" /> New skill
            </Link>
          </Button>
        </div>
        <p className="max-w-3xl text-sm text-muted-foreground">
          Checklists the network engineers wrote for common problems. AINOPS opens the live skill
          that fits a question and follows its steps; the Investigate page shows which step it is
          on. A new or changed skill is a draft until it is reviewed and made live.
        </p>
        {catalog.data && (
          <p className="text-xs text-muted-foreground tabular-nums">
            {skills.length} {skills.length === 1 ? 'skill' : 'skills'} · {live} live · {broken}{' '}
            {broken === 1 ? 'needs' : 'need'} fixing
          </p>
        )}
      </div>
      {catalog.isPending ? (
        <Skeleton className="h-96 w-full" />
      ) : catalog.isError ? (
        <p role="alert" className="text-sm text-status-critical">
          Could not load the skills: {catalog.error.message}
        </p>
      ) : (
        <SkillsView catalog={catalog.data} selected={name} />
      )}
    </div>
  )
}
