import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowUp, History, Loader2, Network, Router, ShieldCheck, Sparkles } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { api } from '@/api'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { NetworkMap } from '@/features/topology/network-map'
import { useRunEvents } from '@/hooks/use-run-events'
import { cn } from '@/lib/utils'
import { deriveInvestigation, touchesNetwork, type Now } from './derive'
import { DevicePanel } from './device-panel'
import { ReportCard } from './report-card'
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
  const start = useMutation({
    mutationFn: (text: string) => api.startInvestigation(text),
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

function Run({ runId }: { runId: string }) {
  const { events, done, error } = useRunEvents(runId)
  const topology = useQuery({ queryKey: ['topology'], queryFn: api.topology })
  const deviceNames = useMemo(
    () => topology.data?.devices.map((d) => d.name) ?? [],
    [topology.data],
  )
  const view = useMemo(() => deriveInvestigation(events, deviceNames), [events, deviceNames])
  const [focused, setFocused] = useState<string | null>(null)
  const [panelDevice, setPanelDevice] = useState<string | null>(null)
  const bottom = useRef<HTMLDivElement>(null)
  const running = !done && !view.verdict && !view.error && !error
  const now: Now =
    error && view.now.kind !== 'done' ? { kind: 'stopped', message: error } : view.now

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

  return (
    <div className="grid h-full min-h-0 grid-cols-1 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
      <div className="min-h-0 space-y-4 overflow-y-auto px-6 py-5 lg:border-r">
        <div className="space-y-1">
          <p className="text-xs font-semibold tracking-wider text-eyebrow uppercase">Question</p>
          <h1 className="text-lg font-semibold text-balance">{view.question ?? '…'}</h1>
        </div>

        <NowBanner now={now} stepCount={view.steps.length} skill={view.skill} />

        {/* The map appears once the agent looks at the network: a greeting or a refusal has
            nothing to show on it. */}
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

        {view.verdict && <ReportCard verdict={view.verdict} onSelectEvidence={selectEvidence} />}
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
            {view.verdict ? `done in ${formatMs(view.verdict.atMs)}` : running ? 'live' : ''}
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
        {!running && (
          <div className="mt-4">
            <QuestionBox compact />
          </div>
        )}
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
