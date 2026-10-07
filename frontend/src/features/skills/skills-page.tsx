import { useQuery } from '@tanstack/react-query'
import { BookOpenCheck, FileWarning, PenLine, TriangleAlert } from 'lucide-react'
import { api, type Skill, type SkillCatalog } from '@/api'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { StepText } from './step-text'

// The expert skills the agent can follow: read-only for now (they are edited as SKILL.md files;
// an editor comes with the Admin section).

export function ReviewBadge({ reviewedBy }: { reviewedBy: string }) {
  return reviewedBy ? (
    <Badge variant="outline" className="border-status-healthy-border text-status-healthy">
      Reviewed by {reviewedBy}
    </Badge>
  ) : (
    <Badge variant="outline" className="border-status-warning-border text-status-warning">
      Draft · not reviewed
    </Badge>
  )
}

function SkillCard({ skill }: { skill: Skill }) {
  return (
    <section aria-labelledby={`skill-${skill.name}`} className="rounded-lg border bg-card">
      <header className="space-y-1.5 border-b px-5 py-4">
        <div className="flex flex-wrap items-center gap-2">
          <h2 id={`skill-${skill.name}`} className="font-mono text-[15px] font-semibold">
            {skill.name}
          </h2>
          <ReviewBadge reviewedBy={skill.reviewed_by} />
        </div>
        <p className="text-sm">{skill.description}</p>
        {skill.author && (
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <PenLine aria-hidden="true" className="size-3.5" /> {skill.author}
          </p>
        )}
      </header>
      <div className="space-y-3 px-5 py-4 text-sm">
        {skill.intro && <p className="text-muted-foreground">{skill.intro}</p>}
        <ol aria-label={`Steps of ${skill.name}`} className="space-y-2">
          {skill.steps.map((step, index) => (
            <li key={index} className="flex gap-3">
              <span className="flex size-6 shrink-0 items-center justify-center rounded-full border bg-secondary text-xs font-semibold">
                {index + 1}
              </span>
              <p className="pt-0.5">
                <StepText text={step} />
              </p>
            </li>
          ))}
        </ol>
        <p className="text-xs text-muted-foreground">
          Tools it uses: {skill.tools.join(', ')} · file skills/{skill.path}
        </p>
      </div>
    </section>
  )
}

export function SkillsView({ catalog }: { catalog: SkillCatalog }) {
  return (
    <div className="space-y-5">
      {!catalog.tools_checked && (
        <p role="status" className="flex items-start gap-2 text-sm text-status-warning">
          <TriangleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          The MCP servers are not running, so the tool names in the skills could not be checked.
        </p>
      )}
      {catalog.problems.length > 0 && (
        <section
          aria-label="Skills that need fixing"
          className="rounded-lg border border-status-critical-border bg-status-critical-bg px-5 py-4"
        >
          <h2 className="flex items-center gap-2 font-semibold text-status-critical">
            <FileWarning aria-hidden="true" className="size-4" /> Not used until fixed
          </h2>
          <ul className="mt-2 space-y-2 text-sm">
            {catalog.problems.map((p) => (
              <li key={p.folder}>
                <span className="font-mono font-semibold">skills/{p.folder}</span>
                <ul className="ml-4 list-disc">
                  {p.problems.map((problem) => (
                    <li key={problem}>{problem}</li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </section>
      )}
      {catalog.skills.length === 0 ? (
        <p className="text-sm text-muted-foreground">No skills yet.</p>
      ) : (
        <div className="grid gap-5 xl:grid-cols-2">
          {catalog.skills.map((skill) => (
            <SkillCard key={skill.name} skill={skill} />
          ))}
        </div>
      )}
    </div>
  )
}

export function SkillsPage() {
  const catalog = useQuery({ queryKey: ['skills'], queryFn: api.skills })
  return (
    <div className="mx-auto max-w-[1400px] space-y-5 px-6 py-6">
      <div>
        <h1 className="flex items-center gap-2 text-xl font-semibold">
          <BookOpenCheck aria-hidden="true" className="size-5 text-primary" /> Skills
        </h1>
        <p className="max-w-3xl text-sm text-muted-foreground">
          Procedures the network engineers wrote for frequent questions. The agent reads each
          skill's description, opens the one that fits the question and follows its steps; the
          Investigate page shows which step it is on. A skill can only use the read-only tools.
        </p>
      </div>
      {catalog.isPending ? (
        <Skeleton className="h-96 w-full" />
      ) : catalog.isError ? (
        <p role="alert" className="text-sm text-status-critical">
          Could not load the skills: {catalog.error.message}
        </p>
      ) : (
        <SkillsView catalog={catalog.data} />
      )}
    </div>
  )
}
