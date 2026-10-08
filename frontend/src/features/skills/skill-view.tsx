import { FileText, Wrench } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import type { Skill, SkillProblem, SkillUsage } from '@/api'
import { cn } from '@/lib/utils'
import { outcomeLabel, shortDate, skillTitle } from './labels'
import { NeedsFixingBadge, SkillStatusBadge } from './skill-badges'
import { StepText } from './step-text'

// One skill, opened: when AINOPS uses it, its steps, the tools it needs and where it was used.
// The editor shows the same view as its preview, so what is saved is what this page shows.

function Label({ children }: { children: ReactNode }) {
  return (
    <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
      {children}
    </h3>
  )
}

const OUTCOME_COLOUR: Record<string, string> = {
  diagnosed: 'text-status-critical',
  no_fault_found: 'text-status-healthy',
  inconclusive: 'text-status-warning',
}

function Usage({ usage }: { usage: SkillUsage }) {
  return (
    <section aria-label="Used in investigations" className="space-y-2">
      <Label>
        Used in investigations{usage.count > 0 && <span className="ml-1">({usage.count})</span>}
      </Label>
      {usage.count === 0 ? (
        <p className="text-sm text-muted-foreground">
          Not used yet. AINOPS opens it when a question fits the sentence above.
        </p>
      ) : (
        <ul className="divide-y rounded-md border">
          {usage.recent.map((run) => (
            <li key={run.id}>
              <Link
                to={`/investigations/${run.id}`}
                className="flex items-baseline gap-3 px-3 py-2 text-sm hover:bg-accent focus-visible:bg-accent focus-visible:outline-none"
              >
                <span className="w-24 shrink-0 text-xs text-muted-foreground tabular-nums">
                  {shortDate(run.started_at)}
                </span>
                <span className="min-w-0 flex-1 truncate">{run.title}</span>
                <span
                  className={cn(
                    'shrink-0 text-xs font-medium',
                    (run.outcome && OUTCOME_COLOUR[run.outcome]) ?? 'text-muted-foreground',
                  )}
                >
                  {outcomeLabel(run.outcome)}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {usage.count > usage.recent.length && (
        <p className="text-xs text-muted-foreground">
          The latest {usage.recent.length} are listed; History has them all.
        </p>
      )}
    </section>
  )
}

export function SkillView({
  skill,
  usage,
  actions,
  panel,
}: {
  skill: Skill
  /** Missing in the editor's preview. */
  usage?: SkillUsage
  /** Buttons for the skill (edit, history), shown under the title. */
  actions?: ReactNode
  /** Whether AINOPS uses it, and the buttons to change that (the Skills page only). */
  panel?: ReactNode
}) {
  return (
    <article aria-labelledby="skill-title" className="space-y-6">
      <header className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <h2 id="skill-title" className="text-lg font-semibold">
            {skillTitle(skill.name)}
          </h2>
          <SkillStatusBadge status={skill.status} />
        </div>
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
          <span className="font-mono">{skill.name}</span>
          {skill.author && <span>· author: {skill.author}</span>}
        </p>
        {actions && <div className="flex flex-wrap gap-2 pt-1">{actions}</div>}
      </header>

      {panel}

      <section aria-label="When AINOPS uses it" className="space-y-2">
        <Label>When AINOPS uses it</Label>
        <p className="rounded-md border-l-2 border-primary bg-muted/50 px-3 py-2 text-sm">
          {skill.description}
        </p>
        <p className="text-xs text-muted-foreground">
          AINOPS reads this sentence for every question and opens the skill when it fits.
        </p>
      </section>

      {skill.intro && (
        <section aria-label="About" className="space-y-2">
          <Label>About</Label>
          <p className="text-sm">{skill.intro}</p>
        </section>
      )}

      <section aria-label="Steps" className="space-y-3">
        <Label>Steps</Label>
        <ol aria-label={`Steps of ${skill.name}`} className="space-y-0">
          {skill.steps.map((step, index) => (
            <li key={index} className="relative flex gap-3 pb-4 last:pb-0">
              {index < skill.steps.length - 1 && (
                <span
                  aria-hidden="true"
                  className="absolute top-7 bottom-1 left-3 w-px -translate-x-1/2 bg-border"
                />
              )}
              <span className="relative flex size-6 shrink-0 items-center justify-center rounded-full border bg-card text-xs font-semibold tabular-nums">
                {index + 1}
              </span>
              <p className="min-w-0 pt-0.5 text-sm">
                <StepText text={step} />
              </p>
            </li>
          ))}
        </ol>
      </section>

      {skill.tools.length > 0 && (
        <section aria-label="Tools it uses" className="space-y-2">
          <Label>Tools it uses</Label>
          <ul className="flex flex-wrap gap-1.5">
            {skill.tools.map((tool) => (
              <li
                key={tool}
                className="flex items-center gap-1 rounded-md border bg-muted/40 px-2 py-0.5 font-mono text-xs"
              >
                <Wrench aria-hidden="true" className="size-3 text-muted-foreground" />
                {tool}
              </li>
            ))}
          </ul>
          <p className="text-xs text-muted-foreground">
            All read-only. A skill only guides AINOPS; it cannot run anything itself.
          </p>
        </section>
      )}

      {usage && <Usage usage={usage} />}

      <p className="flex items-center gap-1.5 border-t pt-3 text-xs text-muted-foreground">
        <FileText aria-hidden="true" className="size-3.5" />
        skills/{skill.path}
      </p>
    </article>
  )
}

/** A skill AINOPS leaves out: its file breaks a rule. */
export function BrokenSkillView({ problem }: { problem: SkillProblem }) {
  return (
    <article aria-labelledby="skill-title" className="space-y-4">
      <header className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <h2 id="skill-title" className="text-lg font-semibold">
            {skillTitle(problem.folder)}
          </h2>
          <NeedsFixingBadge />
        </div>
        <p className="font-mono text-xs text-muted-foreground">{problem.folder}</p>
      </header>
      <section
        aria-label="What to fix"
        className="space-y-2 rounded-md border border-status-critical-border bg-status-critical-bg px-4 py-3"
      >
        <p className="text-sm font-medium text-status-critical">
          AINOPS does not use this skill until these are fixed:
        </p>
        <ul className="ml-4 list-disc space-y-1 text-sm">
          {problem.problems.map((text) => (
            <li key={text}>{text}</li>
          ))}
        </ul>
      </section>
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <FileText aria-hidden="true" className="size-3.5" />
        Fix it in skills/{problem.folder}/SKILL.md (the rules are in skills/README.md).
      </p>
    </article>
  )
}
