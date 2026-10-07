import {
  BookOpenCheck,
  CircleCheck,
  CircleX,
  Loader2,
  ShieldX,
  Sparkles,
  TriangleAlert,
} from 'lucide-react'
import { stepHeadline } from '@/features/skills/headline'
import { cn } from '@/lib/utils'
import { needsEvidence, type ActiveSkill, type Now, type Step } from './derive'
import { formatMs } from './format'

// One line that always says, in plain words, what the agent is doing right now and why. It is the
// same step as the pulsing device on the map and the running step in the timeline.

function Result({ step }: { step: Step }) {
  if (step.kind === 'refused') {
    return (
      <span className="flex items-start gap-1.5 text-status-critical">
        <ShieldX aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
        Blocked by the safety check: {step.summary}
      </span>
    )
  }
  if (step.state === 'error') {
    return (
      <span className="flex items-start gap-1.5 text-status-critical">
        <CircleX aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
        {step.summary}
      </span>
    )
  }
  if (step.health?.status === 'problem') {
    return (
      <span className="flex items-start gap-1.5 font-medium text-status-warning">
        <TriangleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
        Found a problem{step.device && step.tool !== 'trace_route'
          ? ` on ${step.device}`
          : ''}: {step.health.issues.map((i) => i.text).join('; ')}
      </span>
    )
  }
  return (
    <span className="flex items-start gap-1.5">
      <CircleCheck aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-status-healthy" />
      {step.summary}
    </span>
  )
}

/** Which expert skill the agent follows, and which of its steps the current check is. */
function SkillLine({ skill, step }: { skill: ActiveSkill; step: number | null }) {
  return (
    <p className="mt-1 flex items-start gap-1.5 text-sm text-provenance-ai">
      <BookOpenCheck aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
      <span>
        Following skill <span className="font-mono font-semibold">{skill.name}</span>
        {step !== null && step > 0 && (
          <>
            {' '}
            · step {step} of {skill.steps.length}: {stepHeadline(skill.steps[step - 1] ?? '')}
          </>
        )}
        {step === 0 && ' · going beyond its steps'}
      </span>
    </p>
  )
}

export function NowBanner({
  now,
  stepCount,
  skill = null,
}: {
  now: Now
  stepCount: number
  skill?: ActiveSkill | null
}) {
  return (
    <section
      aria-label="What the agent is doing now"
      aria-live="polite"
      className={cn(
        'rounded-lg border px-4 py-3',
        now.kind === 'done'
          ? now.verdict.report.outcome === 'diagnosed'
            ? 'border-status-critical-border bg-status-critical-bg'
            : 'border-status-healthy-border bg-status-healthy-bg'
          : now.kind === 'stopped'
            ? 'border-status-critical-border bg-status-critical-bg'
            : 'border-primary/40 bg-secondary/60',
      )}
    >
      <p className="text-xs font-semibold tracking-wider text-eyebrow uppercase">
        {now.kind === 'done' ? 'Finished' : now.kind === 'stopped' ? 'Stopped' : 'Now'}
        {stepCount > 0 && now.kind !== 'done' && (
          <span className="ml-2 font-normal tracking-normal normal-case">step {stepCount}</span>
        )}
      </p>

      {now.kind === 'starting' && (
        <p className="mt-1 flex items-center gap-2 text-[15px] font-medium">
          <Loader2 aria-hidden="true" className="size-4 animate-spin motion-reduce:animate-none" />
          Reading the question and choosing the first check…
        </p>
      )}

      {skill && (now.kind === 'working' || now.kind === 'thinking') && (
        <SkillLine skill={skill} step={now.kind === 'working' ? now.step.skillStep : null} />
      )}

      {now.kind === 'working' && (
        <div className="mt-1 space-y-1">
          <p className="flex items-center gap-2 text-[15px] font-semibold">
            <Loader2
              aria-hidden="true"
              className="size-4 shrink-0 animate-spin text-primary motion-reduce:animate-none"
            />
            {now.step.sentence}
          </p>
          {now.step.why && (
            <p className="flex items-start gap-1.5 pl-6 text-sm text-provenance-ai">
              <Sparkles aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
              <span>
                <span className="font-semibold">Why: </span>
                {now.step.why}
              </span>
            </p>
          )}
        </div>
      )}

      {now.kind === 'thinking' && (
        <div className="mt-1 space-y-1">
          <p className="flex items-center gap-2 text-[15px] font-semibold text-provenance-ai">
            <Sparkles aria-hidden="true" className="size-4 shrink-0" />
            Reading the evidence and deciding the next step…
          </p>
          {now.last && (
            <div className="pl-6 text-sm text-muted-foreground">
              <span className="font-medium text-foreground">Last result</span> ({now.last.sentence}
              ): <Result step={now.last} />
            </div>
          )}
        </div>
      )}

      {now.kind === 'done' && (
        <div className="mt-1 space-y-1">
          <p className="text-[15px] font-semibold">
            {now.verdict.report.outcome === 'diagnosed' && now.verdict.report.root_cause
              ? `Root cause: ${now.verdict.report.root_cause}`
              : now.verdict.report.summary}
          </p>
          <p className="text-sm text-muted-foreground">
            {needsEvidence(now.verdict.report.outcome)
              ? `${now.verdict.toolCalls} ${now.verdict.toolCalls === 1 ? 'check' : 'checks'} in ${formatMs(now.verdict.atMs)} · confidence ${now.verdict.confidence}${
                  now.verdict.skillsUsed.length
                    ? ` · skill ${now.verdict.skillsUsed.join(', ')}`
                    : ''
                }`
              : now.verdict.report.outcome === 'refused'
                ? 'Refused before running any check: AINOPS only reads the network'
                : `Answered in ${formatMs(now.verdict.atMs)} without checking any device`}
          </p>
        </div>
      )}

      {now.kind === 'stopped' && (
        <p role="alert" className="mt-1 text-sm text-status-critical">
          {now.message}
        </p>
      )}
    </section>
  )
}
