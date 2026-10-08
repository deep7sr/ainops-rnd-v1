import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, History } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { api, type SkillHistoryEntry } from '@/api'
import { Button } from '@/components/ui/button'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { skillTitle } from './labels'
import { SkillView } from './skill-view'

// Earlier versions of a skill: every save on the Skills page keeps the version it replaced.

function when(iso: string) {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString()
}

function OldVersion({
  name,
  entry,
  onBack,
  actions,
}: {
  name: string
  entry: SkillHistoryEntry
  onBack: () => void
  actions?: (entry: SkillHistoryEntry, done: () => void) => ReactNode
}) {
  const old = useQuery({
    queryKey: ['skill-version', name, entry.id],
    queryFn: () => api.skillOldVersion(name, entry.id),
  })
  return (
    <div className="space-y-4">
      <Button type="button" variant="ghost" size="sm" onClick={onBack}>
        <ArrowLeft aria-hidden="true" /> All versions
      </Button>
      <p className="text-sm text-muted-foreground">
        Replaced {when(entry.replaced_at)}
        {entry.saved_by && <> · saved by {entry.saved_by}</>}
      </p>
      {actions?.(entry, onBack)}
      {old.isPending ? (
        <Skeleton className="h-64 w-full" />
      ) : old.isError ? (
        <p role="alert" className="text-sm text-status-critical">
          Could not open this version: {old.error.message}
        </p>
      ) : old.data.skill ? (
        <div className="rounded-lg border bg-card p-4">
          <SkillView skill={old.data.skill} />
        </div>
      ) : (
        <pre className="overflow-x-auto rounded-md border bg-muted/40 p-3 text-xs whitespace-pre-wrap">
          {old.data.markdown}
        </pre>
      )}
    </div>
  )
}

export function SkillHistory({
  name,
  actions,
}: {
  name: string
  /** Buttons for an old version (restore); `done` goes back to the list of versions. */
  actions?: (entry: SkillHistoryEntry, done: () => void) => ReactNode
}) {
  const [open, setOpen] = useState(false)
  const [opened, setOpened] = useState<SkillHistoryEntry | null>(null)
  const entries = useQuery({
    queryKey: ['skill-history', name],
    queryFn: () => api.skillHistory(name),
    enabled: open,
  })
  return (
    <Sheet
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (!next) setOpened(null)
      }}
    >
      <SheetTrigger asChild>
        <Button type="button" variant="outline" size="sm">
          <History aria-hidden="true" /> History
        </Button>
      </SheetTrigger>
      <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
        <SheetHeader>
          <SheetTitle>Earlier versions of “{skillTitle(name)}”</SheetTitle>
          <SheetDescription>
            Every save on this page keeps the version it replaced. Versions written before that are
            in git.
          </SheetDescription>
        </SheetHeader>
        <div className="px-4 pb-6">
          {opened ? (
            <OldVersion
              name={name}
              entry={opened}
              onBack={() => setOpened(null)}
              actions={actions}
            />
          ) : entries.isPending ? (
            <Skeleton className="h-32 w-full" />
          ) : entries.isError ? (
            <p role="alert" className="text-sm text-status-critical">
              Could not load the versions: {entries.error.message}
            </p>
          ) : entries.data.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No earlier versions: the skill has not been changed on this page.
            </p>
          ) : (
            <ul aria-label="Earlier versions" className="divide-y rounded-md border">
              {entries.data.map((entry) => (
                <li key={entry.id}>
                  <button
                    type="button"
                    onClick={() => setOpened(entry)}
                    className="block w-full space-y-0.5 px-3 py-2 text-left hover:bg-accent focus-visible:bg-accent focus-visible:outline-none"
                  >
                    <span className="block text-sm">Replaced {when(entry.replaced_at)}</span>
                    <span className="block text-xs text-muted-foreground">
                      {entry.saved_by ? `saved by ${entry.saved_by}` : 'written by hand'}
                      {entry.reviewed_by
                        ? ` · reviewed by ${entry.reviewed_by}`
                        : ' · not reviewed'}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}
