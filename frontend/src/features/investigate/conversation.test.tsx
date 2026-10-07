import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { RunEvent } from '@/api'
import { conversationTurns, MAX_MESSAGES } from './conversation'
import { deriveInvestigation } from './derive'
import { InvestigatePage } from './investigate-page'

// Talking to AINOPS about an investigation. Turn 1 is the fault-1 run recorded on the live lab
// (5 Oct 2026); the follow-ups are added the way the backend adds them (api/runs.py).

const files = import.meta.glob<{ events: RunEvent[] }>('../../../../fixtures/runs/*.json', {
  eager: true,
  import: 'default',
})
const TURN_ONE = Object.entries(files).find(([p]) =>
  p.endsWith('/fault1-leased-line-shut-run1.json'),
)?.[1].events as RunEvent[]
const DEVICES = ['CORE-SW-TRV', 'IPLC-RTR-TRV', 'IPLC-RTR-MAA', 'CORE-SW-MAA']

const message = (text: string, turn = 2): RunEvent => ({
  type: 'message',
  turn,
  text,
  at: '2026-10-05T15:40:00+00:00',
})
const started = (question: string, turn = 2): RunEvent => ({
  type: 'started',
  question,
  tools: [],
  turn,
  at_ms: 0,
})
const ospfCall: RunEvent = {
  type: 'tool_call',
  id: 'E7',
  tool: 'get_ospf_neighbors',
  server: 'network',
  args: { device: 'IPLC-RTR-TRV' },
  why: 'The engineer says Fa2/0 is up: check OSPF on the TRV side',
  at_ms: 900,
}
const answered: RunEvent = {
  type: 'report',
  report: {
    outcome: 'answered',
    summary: 'E6 shows Fa2/0 administratively down on IPLC-RTR-MAA.',
    root_cause: null,
    root_cause_evidence: [],
    affected: [],
    findings: [],
    next_steps: [],
    limitations: [],
  },
  confidence: 'high',
  confidence_reasons: [],
  tool_calls: 0,
  at_ms: 2000,
}

describe('the conversation, rebuilt from the events', () => {
  it('a single investigation is one turn', () => {
    const turns = conversationTurns(TURN_ONE, DEVICES)
    expect(turns).toHaveLength(1)
    expect(turns[0].message).toMatch(/^Users at TRV/)
    expect(turns[0].verdict?.report.outcome).toBe('diagnosed')
    expect(turns[0].checks).toEqual(['E1', 'E2', 'E3', 'E4', 'E5', 'E6'])
  })

  it('a follow-up starts a new turn with its own reply', () => {
    const events = [...TURN_ONE, message('Why Fa2/0?'), started('Why Fa2/0?'), answered]
    const turns = conversationTurns(events, DEVICES)
    expect(turns.map((t) => [t.number, t.message, t.ended])).toEqual([
      [1, expect.stringMatching(/^Users at TRV/), 'report'],
      [2, 'Why Fa2/0?', 'report'],
    ])
    expect(turns[1].checks).toEqual([]) // answered from what was already checked
  })

  it('while a follow-up runs, the old report is not shown as its answer, the map keeps', () => {
    const view = deriveInvestigation([...TURN_ONE, message('Fa2/0 is up'), ospfCall], DEVICES)
    expect(view.verdict).toBeNull()
    expect(view.question).toBe('Fa2/0 is up')
    expect(view.turn).toBe(2)
    expect(view.now.kind).toBe('working')
    expect(view.steps.map((s) => s.turn)).toEqual([1, 1, 1, 1, 1, 1, 2])
    expect(view.highlight.states.get('IPLC-RTR-MAA')).toBe('problem') // found in turn 1
    expect(view.highlight.states.get('IPLC-RTR-TRV')).toBe('checking')
  })

  it('a stopped reply ends its running check and says it was stopped', () => {
    const stopped: RunEvent = { type: 'stopped', message: 'Stopped by the engineer.' }
    const events = [...TURN_ONE, message('Fa2/0 is up'), ospfCall, stopped]
    const view = deriveInvestigation(events, DEVICES)
    const last = view.steps[view.steps.length - 1]
    expect(last.state).toBe('error')
    expect(last.summary).toBe('Did not finish: stopped.')
    expect(view.now).toEqual({
      kind: 'stopped',
      message: 'You stopped AINOPS before it finished.',
    })
    expect(conversationTurns(events, DEVICES)[1].ended).toBe('stopped')
  })
})

// ---------- the page ----------

class FakeEventSource {
  static readonly CLOSED = 2
  static opened: FakeEventSource[] = []
  readonly url: string
  readyState = 1
  onmessage: ((message: MessageEvent<string>) => void) | null = null
  onerror: (() => void) | null = null

  constructor(url: string) {
    this.url = url
    FakeEventSource.opened.push(this)
  }

  close() {
    this.readyState = FakeEventSource.CLOSED
  }

  send(...events: (RunEvent | { type: 'end' })[]) {
    act(() => {
      for (const event of events) {
        this.onmessage?.({ data: JSON.stringify(event) } as MessageEvent<string>)
      }
    })
  }
}

const latestSource = () => FakeEventSource.opened[FakeEventSource.opened.length - 1]
let posts: { url: string; body: unknown }[] = []

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn() // not in jsdom
  FakeEventSource.opened = []
  posts = []
  vi.stubGlobal('EventSource', FakeEventSource)
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        posts.push({ url, body: init.body ? JSON.parse(String(init.body)) : null })
        const answer = url.endsWith('/stop') ? { stopping: true } : { id: 'inv-1', turn: 2 }
        return Promise.resolve(new Response(JSON.stringify(answer)))
      }
      return new Promise(() => {}) // the topology: never needed here
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function openInvestigation() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={['/investigations/inv-1']}>
        <Routes>
          <Route path="/investigations/:id" element={<InvestigatePage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('replying to AINOPS on the Investigate page', () => {
  it('sends a follow-up, then shows the reply under the folded earlier one', async () => {
    const user = userEvent.setup()
    openInvestigation()
    latestSource().send(...TURN_ONE, { type: 'end' })

    await user.type(screen.getByLabelText('Reply to AINOPS'), 'Why Fa2/0?{Enter}')
    expect(posts).toEqual([{ url: '/api/runs/inv-1/messages', body: { text: 'Why Fa2/0?' } }])
    // It listens again from where it was, and offers Stop until the reply has come.
    expect(latestSource().url).toBe(`/api/runs/inv-1/events?after=${TURN_ONE.length}`)
    expect(await screen.findByRole('button', { name: /stop/i })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Diagnosis' })).not.toBeInTheDocument()

    latestSource().send(message('Why Fa2/0?'), started('Why Fa2/0?'), answered, { type: 'end' })
    const earlier = screen.getByRole('region', { name: 'Reply to message 1' })
    expect(within(earlier).getByText('Root cause found')).toBeInTheDocument()
    expect(within(earlier).getByText('6 checks (E1–E6)')).toBeInTheDocument()
    expect(screen.getByText('Your message 2')).toBeInTheDocument()
    const reply = screen.getByRole('region', { name: 'Diagnosis' }) // the latest reply, in full
    expect(within(reply).getByText(/E6 shows Fa2\/0 administratively down/)).toBeInTheDocument()
    expect(screen.getByLabelText('Reply to AINOPS')).toBeInTheDocument()

    // The earlier reply opens to its full report.
    await user.click(within(earlier).getByRole('button', { expanded: false }))
    expect(within(earlier).getByRole('region', { name: 'Diagnosis' })).toBeInTheDocument()
  })

  it('the engineer can stop a reply that is going the wrong way', async () => {
    const user = userEvent.setup()
    openInvestigation()
    latestSource().send(...TURN_ONE, message('Fa2/0 is up'), started('Fa2/0 is up'), ospfCall)
    expect(screen.queryByLabelText('Reply to AINOPS')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /stop/i }))
    expect(posts).toEqual([{ url: '/api/runs/inv-1/stop', body: null }])

    latestSource().send({ type: 'stopped', message: 'Stopped by the engineer.' }, { type: 'end' })
    expect(screen.getByText('You stopped AINOPS before it finished.')).toBeInTheDocument()
    expect(screen.getByLabelText('Reply to AINOPS')).toBeInTheDocument()
  })

  it('a conversation at its message limit points to a new investigation', () => {
    openInvestigation()
    const followUps = Array.from({ length: MAX_MESSAGES - 1 }, (_, i) => [
      message(`message ${i + 2}`, i + 2),
      answered,
    ]).flat()
    latestSource().send(...TURN_ONE, ...followUps, { type: 'end' })
    expect(screen.queryByLabelText('Reply to AINOPS')).not.toBeInTheDocument()
    expect(screen.getByText(/has reached 8 messages/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Start a new investigation' })).toHaveAttribute(
      'href',
      '/',
    )
  })
})
