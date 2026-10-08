import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowUp,
  ChevronDown,
  History,
  Loader2,
  Network,
  Plus,
  Router,
  ShieldCheck,
  Sparkles,
  Square,
  FlaskConical,
  X,
} from 'lucide-react'
import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import { api } from '@/api'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { CaseSection } from '@/features/cases/case-section'
import { skillTitle } from '@/features/skills/labels'
import { NetworkMap } from '@/features/topology/network-map'
import { useRunEvents } from '@/hooks/use-run-events'
import { cn } from '@/lib/utils'
import { conversationTurns, MAX_MESSAGES, type Turn } from './conversation'
import { deriveInvestigation, touchesNetwork, type Now } from './derive'
import { DevicePanel } from './device-panel'
import { OutcomeBadge, ReportCard } from './report-card'
import { formatMs } from './format'
import { NowBanner } from './now-banner'
import { Timeline } from './timeline'

const SUGGESTIONS = [
  'Is the leased line between TRV and MAA healthy?',
  'Why can the TRV LAN (192.168.100.10) not reach the MAA LAN (192.168.200.10)?',
  'Why is MAA-P2P not reachable?',
  'Is anything wrong at the MAA site?',
  'Shut down interface Fa2/0 on IPLC-RTR-MAA',
]

function QuestionBox({ compact }: { compact: boolean }) {
  const [question, setQuestion] = useState('')
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  // "Try this skill" on the Skills page opens /?try=<name>: the next question tries that skill.
  const [params, setParams] = useSearchParams()
  const trying = params.get('try')?.trim() || null
  const start = useMutation({
    mutationFn: (text: string) => api.startInvestigation(text, trying),
    onSuccess: ({ id }) => {
      setQuestion('')
      void queryClient.invalidateQueries({ queryKey: ['investigations'] })
      void navigate(`/investigations/${id}`)
    },
  })
  const submit = (text: string) => {
    if (text.trim().length >= 3 && !start.isPending) start.mutate(text.trim())
  }

  return (
    <div className="space-y-3">
      {trying && (
        <div
          role="status"
          className="flex items-start gap-2 rounded-md border border-status-warning-border bg-status-warning-bg px-3 py-2 text-sm"
        >
          <FlaskConical aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-status-warning" />
          <p className="min-w-0 flex-1">
            Trying the skill <span className="font-medium">{skillTitle(trying)}</span>: AINOPS
            follows it for this question even if it is not live yet. Ask a question it should fit.
          </p>
          <button
            type="button"
            aria-label="Stop trying this skill"
            onClick={() => {
              params.delete('try')
              setParams(params, { replace: true })
            }}
            className="rounded p-0.5 text-muted-foreground hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
          >
            <X aria-hidden="true" className="size-4" />
          </button>
        </div>
      )}
      <form
        onSubmit={(event) => {
          event.preventDefault()
          submit(question)
        }}
        className="relative"
      >
        <label htmlFor="question" className="sr-only">
          Ask AINOPS about the network
        </label>
        <Textarea
          id="question"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              submit(question)
            }
          }}
          placeholder="Ask about the network, e.g. why can the TRV LAN not reach MAA?"
          className={cn('resize-none pr-14 text-[15px]', compact ? 'min-h-12' : 'min-h-24')}
          maxLength={500}
        />
        <Button
          type="submit"
          size="icon"
          aria-label="Investigate"
          disabled={question.trim().length < 3 || start.isPending}
          className="absolute right-2.5 bottom-2.5"
        >
          {start.isPending ? (
            <Loader2 aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
          ) : (
            <ArrowUp aria-hidden="true" />
          )}
        </Button>
      </form>
      {start.isError && (
        <p role="alert" className="text-sm text-status-critical">
          Could not start the investigation: {start.error.message}
        </p>
      )}
      {!compact && (
        <div className="flex flex-wrap gap-2">
          {SUGGESTIONS.map((text) => (
            <button
              key={text}
              type="button"
              onClick={() => submit(text)}
              className="rounded-full border bg-card px-3 py-1.5 text-left text-sm text-muted-foreground hover:border-primary hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
            >
              {text}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function Welcome() {
  const recent = useQuery({ queryKey: ['investigations'], queryFn: api.investigations })
  return (
    <div className="mx-auto max-w-2xl space-y-8 py-10">
      <div className="space-y-2">
        <p className="flex items-center gap-2 text-xs font-semibold tracking-[0.14em] text-eyebrow uppercase">
          <Sparkles aria-hidden="true" className="size-3.5 text-provenance-ai" /> Agentic network
          troubleshooting
        </p>
        <h1 className="text-2xl font-semibold text-balance">What is wrong with the network?</h1>
        <p className="text-muted-foreground">
          AINOPS works out which devices matter from the knowledge graph, checks them live through
          read-only MCP tools, and explains the cause with evidence. It never changes a device.
        </p>
      </div>
      <QuestionBox compact={false} />
      {(recent.data?.length ?? 0) > 0 && (
        <div>
          <h2 className="flex items-center gap-2 text-xs font-semibold tracking-wider text-eyebrow uppercase">
            <History aria-hidden="true" className="size-3.5" /> Recent investigations
          </h2>
          <ul className="mt-2 divide-y rounded-md border bg-card">
            {recent.data?.slice(0, 5).map((run) => (
              <li key={run.id}>
                <Link
                  to={`/investigations/${run.id}`}
                  className="flex items-center justify-between gap-4 px-4 py-2.5 text-sm hover:bg-accent focus-visible:bg-accent focus-visible:outline-none"
                >
                  <span className="min-w-0 truncate">{run.title}</span>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {run.outcome?.replaceAll('_', ' ') ?? 'running'}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function Legend() {
  const items = [
    { swatch: <span className="h-0.5 w-5 bg-primary" />, text: 'path the agent follows' },
    {
      swatch: <span className="size-3 rounded-sm border-2 border-primary bg-secondary" />,
      text: 'being checked now',
    },
    {
      swatch: (
        <span className="size-3 rounded-sm border border-status-healthy-border bg-status-healthy-bg" />
      ),
      text: 'checked: healthy',
    },
    {
      swatch: (
        <span className="size-3 rounded-sm border border-status-warning-border bg-status-warning-bg" />
      ),
      text: 'checked: problem found',
    },
    {
      swatch: <span className="h-0.5 w-5 border-t-2 border-dashed border-status-critical" />,
      text: 'root cause',
    },
    { swatch: <span className="size-2.5 rounded-full bg-primary" />, text: 'ping in flight' },
  ]
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
      {items.map(({ swatch, text }) => (
        <li key={text} className="flex items-center gap-1.5">
          {swatch} {text}
        </li>
      ))}
    </ul>
  )
}

/** One message from the engineer in the conversation. The question is the page's heading. */
function MessageBubble({ turn }: { turn: Turn }) {
  const Heading = turn.number === 1 ? 'h1' : 'p'
  return (
    <div className="rounded-lg border bg-muted/40 px-4 py-3">
      <p className="text-xs font-semibold tracking-wider text-eyebrow uppercase">
        {turn.number === 1 ? 'Your question' : `Your message ${turn.number}`}
        {turn.at && (
          <span className="ml-2 font-normal tracking-normal normal-case">
            {new Date(turn.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </span>
        )}
      </p>
      <Heading
        className={cn(
          'mt-1 text-balance',
          turn.number === 1 ? 'text-lg font-semibold' : 'text-[15px] font-medium',
        )}
      >
        {turn.message || '…'}
      </Heading>
    </div>
  )
}

/** An earlier reply, folded to one line; it opens to the full report. */
function EarlierReply({
  turn,
  onSelectEvidence,
}: {
  turn: Turn
  onSelectEvidence: (id: string) => void
}) {
  const [open, setOpen] = useState(false)
  const report = turn.verdict?.report
  const line = report
    ? (report.root_cause ?? report.summary)
    : turn.ended === 'stopped'
      ? 'You stopped this reply before it finished.'
      : (turn.error ?? 'This reply did not finish.')
  return (
    <section aria-label={`Reply to message ${turn.number}`} className="space-y-2">
      <button
        type="button"
        aria-expanded={report ? open : undefined}
        disabled={!report}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-start gap-3 rounded-lg border bg-card px-4 py-3 text-left hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none disabled:hover:bg-card"
      >
        {report ? (
          <OutcomeBadge outcome={report.outcome} />
        ) : (
          <span className="shrink-0 rounded-md border px-2.5 py-1 text-sm font-semibold text-muted-foreground">
            {turn.ended === 'stopped' ? 'Stopped' : 'Failed'}
          </span>
        )}
        <span className="min-w-0 flex-1 pt-1 text-sm">
          <span className="line-clamp-2">{line}</span>
          <span className="mt-0.5 block text-xs text-muted-foreground">
            {turn.checks.length === 0
              ? 'No new checks'
              : `${turn.checks.length} check${turn.checks.length === 1 ? '' : 's'} (${turn.checks[0]}–${turn.checks[turn.checks.length - 1]})`}
          </span>
        </span>
        {report && (
          <ChevronDown
            aria-hidden="true"
            className={cn('mt-1.5 size-4 shrink-0 transition-transform', open && 'rotate-180')}
          />
        )}
      </button>
      {open && turn.verdict && (
        <ReportCard verdict={turn.verdict} onSelectEvidence={onSelectEvidence} />
      )}
    </section>
  )
}

/** Where the engineer answers AINOPS: ask why, correct it, or tell it where to look. */
function ReplyBox({
  runId,
  running,
  messages,
  onSent,
}: {
  runId: string
  running: boolean
  messages: number
  onSent: (turn: number) => void
}) {
  const [text, setText] = useState('')
  const queryClient = useQueryClient()
  const send = useMutation({
    mutationFn: (message: string) => api.sendMessage(runId, message),
    onSuccess: ({ turn }) => {
      setText('')
      onSent(turn)
      void queryClient.invalidateQueries({ queryKey: ['investigations'] })
    },
  })
  const stop = useMutation({ mutationFn: () => api.stopRun(runId) })
  const submit = () => {
    if (text.trim() && !send.isPending) send.mutate(text.trim())
  }

  if (running) {
    return (
      <div className="flex items-center justify-between gap-3 rounded-lg border bg-card px-4 py-3">
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 aria-hidden="true" className="size-4 animate-spin motion-reduce:animate-none" />
          AINOPS is working on {messages > 1 ? 'your message' : 'your question'}. Going the wrong
          way? Stop it and tell it where to look.
        </p>
        <Button variant="outline" size="sm" onClick={() => stop.mutate()} disabled={stop.isPending}>
          <Square aria-hidden="true" /> Stop
        </Button>
        {stop.isError && (
          <p role="alert" className="text-sm text-status-critical">
            Could not stop: {stop.error.message}
          </p>
        )}
      </div>
    )
  }
  if (messages >= MAX_MESSAGES) {
    return (
      <p className="rounded-lg border bg-card px-4 py-3 text-sm text-muted-foreground">
        This conversation has reached {MAX_MESSAGES} messages.{' '}
        <Link to="/" className="font-medium text-primary underline-offset-4 hover:underline">
          Start a new investigation
        </Link>{' '}
        to go on.
      </p>
    )
  }
  return (
    <div className="space-y-1.5">
      <form
        onSubmit={(event) => {
          event.preventDefault()
          submit()
        }}
        className="relative"
      >
        <label htmlFor="reply" className="sr-only">
          Reply to AINOPS
        </label>
        <Textarea
          id="reply"
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              submit()
            }
          }}
          placeholder="Reply to AINOPS: ask why, correct it, or tell it where to look"
          className="min-h-12 resize-none bg-card pr-14 text-[15px]"
          maxLength={500}
        />
        <Button
          type="submit"
          size="icon"
          aria-label="Send"
          disabled={!text.trim() || send.isPending}
          className="absolute right-2.5 bottom-2.5"
        >
          {send.isPending ? (
            <Loader2 aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
          ) : (
            <ArrowUp aria-hidden="true" />
          )}
        </Button>
      </form>
      {send.isError ? (
        <p role="alert" className="text-sm text-status-critical">
          Could not send: {send.error.message}
        </p>
      ) : (
        <p className="text-xs text-muted-foreground">
          AINOPS answers from what it already checked, or checks the devices again. It never changes
          the network.
        </p>
      )}
    </div>
  )
}

function Run({ runId }: { runId: string }) {
  const { events, done, error, resume } = useRunEvents(runId)
  const topology = useQuery({ queryKey: ['topology'], queryFn: api.topology })
  const deviceNames = useMemo(
    () => topology.data?.devices.map((d) => d.name) ?? [],
    [topology.data],
  )
  const view = useMemo(() => deriveInvestigation(events, deviceNames), [events, deviceNames])
  const turns = useMemo(() => conversationTurns(events, deviceNames), [events, deviceNames])
  const [focused, setFocused] = useState<string | null>(null)
  const [panelDevice, setPanelDevice] = useState<string | null>(null)
  // A message was sent and its turn has not shown up in the events yet.
  const [awaitingTurn, setAwaitingTurn] = useState<number | null>(null)
  const bottom = useRef<HTMLDivElement>(null)
  const waiting = awaitingTurn !== null && view.turn < awaitingTurn
  const running = waiting || (!done && !view.verdict && !view.error && !error)
  const now: Now = waiting
    ? { kind: 'starting' }
    : error && view.now.kind !== 'done'
      ? { kind: 'stopped', message: error }
      : view.now

  // Follow the live steps while the investigation runs.
  useEffect(() => {
    if (running) bottom.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [view.steps.length, running])

  const selectEvidence = (id: string) => {
    setPanelDevice(null)
    setFocused(id)
    document.getElementById(`step-${id}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }
  const topologyCalls = view.steps.filter((s) => s.server === 'topology').length
  const networkCalls = view.steps.filter((s) => s.server === 'network').length
  const refusals = view.steps.filter((s) => s.kind === 'refused').length
  const device = topology.data?.devices.find((d) => d.name === panelDevice) ?? null
  const latest = turns[turns.length - 1]
  // The case events of the latest reply: drafted, updated, or not saved.
  const caseEvents = events.filter((e) => e.type === 'case').length
  const notSaved = useMemo(() => {
    let note: string | null = null
    for (const event of events) {
      if (event.type === 'message') note = null
      else if (event.type === 'case') note = event.error ?? null
    }
    return note
  }, [events])

  return (
    <div className="grid h-full min-h-0 grid-cols-1 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
      <div className="flex min-h-0 flex-col lg:border-r">
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-6 py-5">
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs font-semibold tracking-wider text-eyebrow uppercase">
              Conversation
              {turns.length > 1 && (
                <span className="ml-2 font-normal tracking-normal normal-case">
                  {turns.length} messages
                </span>
              )}
            </p>
            <Button asChild variant="outline" size="sm">
              <Link to="/">
                <Plus aria-hidden="true" /> New investigation
              </Link>
            </Button>
          </div>

          {turns.slice(0, -1).map((turn) => (
            <Fragment key={turn.number}>
              <MessageBubble turn={turn} />
              <EarlierReply turn={turn} onSelectEvidence={selectEvidence} />
            </Fragment>
          ))}
          {latest && <MessageBubble turn={latest} />}

          <NowBanner now={now} stepCount={view.steps.length} skill={view.skill} />

          {/* The map appears once the agent looks at the network: a greeting or a refusal has
              nothing to show on it. It keeps everything checked in the whole conversation. */}
          {touchesNetwork(view.steps) && (
            <>
              <div className="rounded-lg border bg-card p-2">
                {topology.data ? (
                  <NetworkMap
                    topology={topology.data}
                    highlight={view.highlight}
                    showEdges={false}
                    selected={panelDevice}
                    onSelect={(key) => {
                      if (deviceNames.includes(key)) setPanelDevice(key)
                    }}
                  />
                ) : (
                  <Skeleton className="aspect-[1000/560] w-full" />
                )}
              </div>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <Legend />
                <p className="text-xs text-muted-foreground">
                  Click a device to see what was found on it.
                </p>
              </div>
              <div className="grid grid-cols-3 gap-2 text-sm">
                {[
                  { icon: Network, label: 'Topology MCP calls', value: topologyCalls },
                  { icon: Router, label: 'Network MCP calls', value: networkCalls },
                  { icon: ShieldCheck, label: 'Blocked by safety check', value: refusals },
                ].map(({ icon: Icon, label, value }) => (
                  <div key={label} className="rounded-md border bg-card px-3 py-2">
                    <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                      <Icon aria-hidden="true" className="size-3.5" /> {label}
                    </p>
                    <p className="mt-0.5 text-xl font-semibold tabular-nums">{value}</p>
                  </div>
                ))}
              </div>
            </>
          )}

          {view.verdict && !waiting && (
            <ReportCard verdict={view.verdict} onSelectEvidence={selectEvidence} />
          )}
          {!running && (
            <CaseSection
              runId={runId}
              outcome={view.verdict?.report.outcome ?? null}
              caseEvents={caseEvents}
              notSaved={notSaved}
            />
          )}
        </div>

        <div className="border-t bg-background px-6 py-3">
          <ReplyBox
            runId={runId}
            running={running}
            messages={turns.length}
            onSent={(turn) => {
              setAwaitingTurn(turn)
              resume()
            }}
          />
        </div>
      </div>

      <aside
        aria-label="Steps of the investigation"
        className="min-h-0 overflow-y-auto bg-muted/30 px-5 py-5"
      >
        <div className="mb-3 flex items-center justify-between">
          <p className="text-xs font-semibold tracking-wider text-eyebrow uppercase">
            What the agent did, step by step
          </p>
          <p className="text-xs text-muted-foreground">
            {view.verdict && !waiting
              ? `done in ${formatMs(view.verdict.atMs)}`
              : running
                ? 'live'
                : ''}
          </p>
        </div>

        {view.steps.length === 0 && running && <Skeleton className="h-16 w-full" />}

        <Timeline steps={view.steps} focused={focused} onSelectDevice={setPanelDevice} />

        {running && view.steps.length > 0 && view.steps.every((s) => s.state !== 'running') && (
          <p className="flex items-center gap-2 pl-11 text-sm text-provenance-ai">
            <Sparkles aria-hidden="true" className="size-3.5" />
            Reading the evidence and deciding the next step…
          </p>
        )}
        <div ref={bottom} />
      </aside>

      <DevicePanel
        device={device}
        state={device ? view.highlight.states.get(device.name) : undefined}
        issues={device ? (view.highlight.issues.get(device.name) ?? []) : []}
        steps={view.steps}
        onClose={() => setPanelDevice(null)}
        onSelectEvidence={selectEvidence}
      />
    </div>
  )
}

export function InvestigatePage() {
  const { id } = useParams()
  return id ? (
    <Run runId={id} />
  ) : (
    <div className="h-full overflow-y-auto px-6">
      <Welcome />
    </div>
  )
}
