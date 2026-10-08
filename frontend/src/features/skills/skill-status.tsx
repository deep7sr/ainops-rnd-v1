import { useMutation, useQueryClient } from '@tanstack/react-query'
import { CircleCheck, CirclePause, CirclePlay, FlaskConical, Loader2 } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { api, type SavedSkill, type Skill, type SkillStatus } from '@/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { rememberName, savedName } from '@/lib/your-name'
import { cn } from '@/lib/utils'
import { shortDate } from './labels'

// Whether AINOPS uses a skill, and the steps to get it there: try it, review it, make it live.
// Only live skills are offered to AINOPS; an edit sends a skill back to draft.

function explanation(skill: Skill): string {
  if (skill.status === 'live') return 'AINOPS uses this skill for every question it fits.'
  if (skill.status === 'off') return 'AINOPS does not use this skill. Make it live to use it again.'
  return skill.reviewed_by
    ? 'Reviewed and ready. AINOPS does not use it until it is live.'
    : 'AINOPS does not use it yet. Try it on a question, have it reviewed, then make it live.'
}

const BOX: Record<SkillStatus, string> = {
  live: 'border-status-healthy-border bg-status-healthy-bg',
  draft: 'border-status-warning-border bg-status-warning-bg',
  off: 'border-status-unknown-border bg-status-unknown-bg',
}

type Change = { kind: 'review' } | { kind: 'status'; status: SkillStatus }

export function SkillStatusPanel({ skill, version }: { skill: Skill; version: string | null }) {
  const [by, setBy] = useState(savedName)
  const queryClient = useQueryClient()
  const change = useMutation({
    mutationFn: (what: Change): Promise<SavedSkill> => {
      const name = by.trim()
      if (!version) throw new Error('reload the page: the skill file could not be read')
      return what.kind === 'review'
        ? api.reviewSkill(skill.name, name, version)
        : api.setSkillStatus(skill.name, what.status, name, version)
    },
    onSuccess: () => {
      rememberName(by.trim())
      void queryClient.invalidateQueries({ queryKey: ['skills'] })
    },
  })
  const named = by.trim().length > 0
  const busy = change.isPending
  const pending = (what: Change['kind']) =>
    busy && change.variables?.kind === what ? (
      <Loader2 aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
    ) : null

  return (
    <section
      aria-label="Status"
      className={cn('space-y-3 rounded-md border px-4 py-3', BOX[skill.status])}
    >
      <div className="space-y-0.5">
        <p className="text-sm font-medium">{explanation(skill)}</p>
        <p className="text-xs text-muted-foreground">
          {skill.reviewed_by
            ? `Reviewed by ${skill.reviewed_by}${skill.reviewed_at ? ` on ${shortDate(skill.reviewed_at)}` : ''}.`
            : 'Not reviewed yet.'}{' '}
          Only a reviewed skill can go live; changing a skill sends it back to draft.
        </p>
      </div>
      <div className="flex flex-wrap items-end gap-2">
        {skill.status !== 'live' && (
          <Button asChild variant="outline" size="sm" className="bg-card">
            <Link to={`/?try=${encodeURIComponent(skill.name)}`}>
              <FlaskConical aria-hidden="true" /> Try this skill
            </Link>
          </Button>
        )}
        <div className="space-y-1">
          <label htmlFor="status-by" className="block text-xs font-semibold">
            Your name
          </label>
          <Input
            id="status-by"
            value={by}
            onChange={(event) => setBy(event.target.value)}
            maxLength={80}
            autoComplete="name"
            className="h-7 w-40 bg-card text-sm"
          />
        </div>
        {!skill.reviewed_by && (
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="bg-card"
            disabled={!named || busy}
            onClick={() => change.mutate({ kind: 'review' })}
          >
            {pending('review') ?? <CircleCheck aria-hidden="true" />} Mark reviewed
          </Button>
        )}
        {skill.status !== 'live' && (
          <Button
            type="button"
            size="sm"
            disabled={!named || busy || !skill.reviewed_by}
            title={skill.reviewed_by ? undefined : 'Review it first'}
            onClick={() => change.mutate({ kind: 'status', status: 'live' })}
          >
            {pending('status') ?? <CirclePlay aria-hidden="true" />} Make live
          </Button>
        )}
        {skill.status === 'live' && (
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="bg-card"
            disabled={!named || busy}
            onClick={() => change.mutate({ kind: 'status', status: 'off' })}
          >
            {pending('status') ?? <CirclePause aria-hidden="true" />} Turn off
          </Button>
        )}
      </div>
      {change.isError && (
        <p role="alert" className="text-sm text-status-critical">
          Not changed: {change.error.message}
        </p>
      )}
    </section>
  )
}

/** "Restore this version" for an earlier version in History: saved like an edit (a draft). */
export function RestoreVersion({
  name,
  entry,
  version,
  onRestored,
}: {
  name: string
  entry: string
  version: string | null
  onRestored: () => void
}) {
  const [by, setBy] = useState(savedName)
  const queryClient = useQueryClient()
  const restore = useMutation({
    mutationFn: () => {
      if (!version) throw new Error('reload the page: the skill file could not be read')
      return api.restoreSkill(name, entry, by.trim(), version)
    },
    onSuccess: () => {
      rememberName(by.trim())
      void queryClient.invalidateQueries({ queryKey: ['skills'] })
      void queryClient.invalidateQueries({ queryKey: ['skill-history', name] })
      onRestored()
    },
  })
  return (
    <div className="space-y-2 rounded-md border bg-muted/40 px-3 py-2">
      <p className="text-xs text-muted-foreground">
        Restoring saves this version as a new change: the current one is kept in History, and the
        skill becomes a draft that needs a new review.
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <div className="space-y-1">
          <label htmlFor="restore-by" className="block text-xs font-semibold">
            Your name
          </label>
          <Input
            id="restore-by"
            value={by}
            onChange={(event) => setBy(event.target.value)}
            maxLength={80}
            className="h-7 w-40 text-sm"
          />
        </div>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={!by.trim() || restore.isPending}
          onClick={() => restore.mutate()}
        >
          Restore this version
        </Button>
      </div>
      {restore.isError && (
        <p role="alert" className="text-sm text-status-critical">
          Not restored: {restore.error.message}
        </p>
      )}
    </div>
  )
}
