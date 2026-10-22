import {
  BookOpenCheck,
  CircleCheck,
  CircleSlash,
  CircleX,
  Loader2,
  ShieldX,
  Sparkles,
  TriangleAlert,
} from 'lucide-react'
import { motion } from 'motion/react'
import { useEffect, useState } from 'react'
import { stepHeadline } from '@/features/skills/headline'
import { usePrefersReducedMotion } from '@/hooks/use-reduced-motion'
import { crossFade } from '@/lib/motion'
import { cn } from '@/lib/utils'
import { isSafetyBlock, needsEvidence, type ActiveSkill, type Now, type Step } from './derive'
import { formatMs } from './format'
import { ToolIcon } from './tool-icon'

// One line that always says, in plain words, what the agent is doing right now and why. It is the
// same step as the pulsing device on the map and the running step in the timeline.

/** Changes whenever the banner says something new: a new check, thinking, the answer. */
function nowKey(now: Now): string {
  if (now.kind === 'working') return `working-${now.step.key}`
  if (now.kind === 'thinking') return `thinking-${now.last?.key ?? ''}`
  return now.kind
}

/**
 * How long the AI has been thinking. On the free AI tier it can take half a minute between steps
 * (the live run of 2026-10-22), and a screen that does not change looks stuck. It counts from when
 * the banner started saying it (it restarts with each new line); not announced: the banner is a
 * live region and a ticking number would be read out every second.
 */
function ThinkingFor() {
  const [seconds, setSeconds] = useState(0)
  useEffect(() => {
    const timer = setInterval(() => setSeconds((s) => s + 1), 1000)
    return () => clearInterval(timer)
  }, [])
  if (seconds < 3) return null
  return (
    <span aria-hidden="true" className="font-normal text-muted-foreground tabular-nums">
      {seconds} s
    </span>
  )
}

/** The running tool's icon with a spinning ring around it. */
function Working({ tool }: { tool: string }) {
  return (
    <span className="relative flex size-6 shrink-0 items-center justify-center text-primary">
      <Loader2
        aria-hidden="true"
        className="absolute size-6 animate-spin opacity-50 motion-reduce:animate-none"
      />
      <ToolIcon tool={tool} className="size-3.5" />
    </span>
  )
}

function Result({ step }: { step: Step }) {
  if (isSafetyBlock(step)) {
    return (
      <span className="flex items-start gap-1.5 text-status-critical">
        <ShieldX aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
        Blocked by the safety check: {step.summary}
      </span>
    )
  }
  // A limit of the investigation, or a request the tool turned down: nothing wrong on the network.
  if (step.kind === 'refused' || step.failure === 'request') {
    return (
      <span className="flex items-start gap-1.5">
        <CircleSlash aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
        {step.rule === 'budget'
          ? 'Check limit reached: the AI writes its answer from what it found'
          : `Not run: ${step.summary}`}
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

/**
 * The "why" of the running check, typed out as the AI's own words arrive. Screen readers get the
 * whole sentence at once; with reduced motion it is all there at once.
 */
function Typed({ text }: { text: string }) {
  const reduced = usePrefersReducedMotion()
  const [count, setCount] = useState(0)
  const done = reduced || count >= text.length
  useEffect(() => {
    if (done) return
    const timer = setInterval(() => setCount((c) => c + 2), 20)
    return () => clearInterval(timer)
  }, [done])
  return (
    <>
      <span aria-hidden="true">
        {done ? text : text.slice(0, count)}
        {!done && (
          <span className="ml-px inline-block h-3.5 w-1.5 translate-y-0.5 bg-provenance-ai/70" />
        )}
      </span>
      <span className="sr-only">{text}</span>
    </>
  )
}

/** The steps of the skill as a rail: done, the one being carried out, still to do. */
function SkillRail({
  total,
  reached,
  current,
}: {
  total: number
  reached: number
  current: number | null
}) {
  return (
    <span aria-hidden="true" className="mt-1 flex gap-0.5">
      {Array.from({ length: total }, (_, i) => (
        <span
          key={i}
          className={cn(
            'h-1 w-5 rounded-full',
            current === i + 1
              ? 'animate-pulse bg-provenance-ai motion-reduce:animate-none'
              : i < reached
                ? 'bg-provenance-ai/60'
                : 'bg-border',
          )}
        />
      ))}
    </span>
  )
}

/** Which expert skill the agent follows, and which of its steps the current check is. */
function SkillLine({
  skill,
  step,
  reached,
}: {
  skill: ActiveSkill
  step: number | null
  reached: number
}) {
  return (
    <div className="mt-1 flex items-start gap-1.5 text-sm text-provenance-ai">
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
        {skill.steps.length > 0 && (
          <SkillRail total={skill.steps.length} reached={reached} current={step} />
        )}
      </span>
    </div>
  )
}

export function NowBanner({
  now,
  stepCount,
  skill = null,
  skillReached = 0,
}: {
  now: Now
  stepCount: number
  skill?: ActiveSkill | null
  /** The highest step of the skill a check carried out in this reply. */
  skillReached?: number
}) {
  return (
    <section
      aria-label="What the agent is doing now"
      aria-live="polite"
      className={cn(
        'rounded-lg border px-4 py-3 transition-shadow duration-(--motion-slow)',
        now.kind === 'working' && 'glow',
        now.kind === 'thinking' && 'ai-glow',
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

      {/* What it is doing replaces what it did, in place: the new line fades in at once (no
          waiting for the old one to fade out, so news such as "stopped" is never delayed). */}
      <motion.div key={nowKey(now)} variants={crossFade} initial="hidden" animate="shown">
        {now.kind === 'starting' && (
          <p className="mt-1 flex items-center gap-2 text-[15px] font-medium">
            <Loader2
              aria-hidden="true"
              className="size-4 animate-spin motion-reduce:animate-none"
            />
            Reading the question and choosing the first check…
            <ThinkingFor />
          </p>
        )}

        {skill && (now.kind === 'working' || now.kind === 'thinking') && (
          <SkillLine
            skill={skill}
            step={now.kind === 'working' ? now.step.skillStep : null}
            reached={skillReached}
          />
        )}

        {now.kind === 'working' && (
          <div className="mt-1 space-y-1">
            <p className="flex items-center gap-2 text-[15px] font-semibold">
              <Working tool={now.step.tool} />
              {now.step.sentence}
            </p>
            {now.step.why && (
              <p className="flex items-start gap-1.5 pl-8 text-sm text-provenance-ai">
                <Sparkles aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
                <span>
                  <span className="font-semibold">Why: </span>
                  <Typed key={now.step.key} text={now.step.why} />
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
              <ThinkingFor />
            </p>
            {now.last && (
              <div className="pl-6 text-sm text-muted-foreground">
                <span className="font-medium text-foreground">Last result</span> (
                {now.last.sentence}
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
          <div className="mt-1 space-y-1 text-sm">
            <p role="alert" className="text-status-critical">
              {now.message}
            </p>
            {now.detail && (
              <details>
                <summary className="cursor-pointer text-xs text-muted-foreground">
                  Technical details
                </summary>
                <p className="mt-1 font-mono text-xs break-all text-muted-foreground">
                  {now.detail}
                </p>
              </details>
            )}
          </div>
        )}
      </motion.div>
    </section>
  )
}
