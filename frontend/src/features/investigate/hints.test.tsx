import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import type { Case, RunEvent } from '@/api'
import { CaseView } from '@/features/cases/case-view'
import { deriveInvestigation, touchesNetwork } from './derive'
import { ReportCard } from './report-card'
import { Timeline } from './timeline'

// Similar past cases shown as hints, and the token count. The hints event and the case are what
// the backend makes (fixtures/cases/samples, written by tests/test_similar.py and test_cases.py).

const files = import.meta.glob<unknown>('../../../../fixtures/cases/samples/*.json', {
  eager: true,
  import: 'default',
})
const sample = <T,>(name: string) =>
  structuredClone(Object.entries(files).find(([p]) => p.endsWith(`/${name}.json`))?.[1] as T)
const HINTS = sample<RunEvent & { type: 'hints' }>('hints-event')
const DEVICES = ['IPLC-RTR-TRV', 'IPLC-RTR-MAA']

const started: RunEvent = { type: 'started', question: 'Why?', tools: [], at_ms: 0 }
const none: RunEvent = { type: 'hints', cases: [], looked_at: 0, error: null, at_ms: 2 }
const message = (turn: number): RunEvent => ({
  type: 'message',
  turn,
  text: 'And now?',
  at: '2026-10-08T10:00:00+00:00',
})

describe('hints in the steps', () => {
  it('a similar past case becomes a hint step, never a check', () => {
    const view = deriveInvestigation([started, HINTS], DEVICES)
    expect(view.steps).toHaveLength(1)
    const [step] = view.steps
    expect(step.kind).toBe('hints')
    expect(step.evidenceId).toBeNull() // cannot be cited
    expect(step.sentence).toBe('Found 1 similar past case: hints, not evidence')
    expect(touchesNetwork(view.steps)).toBe(false)
    expect(view.highlight.states.size).toBe(0) // nothing on the map
  })

  it('with no similar case yet, the question says so once', () => {
    const view = deriveInvestigation([started, none, message(2), none], DEVICES)
    expect(view.steps.map((s) => s.sentence)).toEqual(['Looked for similar past cases: none yet'])
    expect(view.steps[0].summary).toBe('AINOPS learns from the cases engineers approve.')
  })

  it('says why it could not look', () => {
    const failed: RunEvent = { ...none, error: 'could not look up past cases: ConnectionError' }
    const view = deriveInvestigation([started, failed], DEVICES)
    expect(view.steps[0].summary).toBe('could not look up past cases: ConnectionError')
  })

  it('the timeline shows the case, the engineer’s root cause, the fix and why it matched', () => {
    const view = deriveInvestigation([started, HINTS], DEVICES)
    render(
      <MemoryRouter>
        <Timeline steps={view.steps} focused={null} />
      </MemoryRouter>,
    )
    const hint = within(screen.getByRole('list', { name: 'Similar past cases' })).getByRole(
      'listitem',
    )
    expect(within(hint).getByRole('link', { name: 'case-abc123' })).toHaveAttribute(
      'href',
      '/cases/case-abc123',
    )
    expect(hint).toHaveTextContent('approved by Praveen')
    expect(hint).toHaveTextContent(
      'Root cause (engineer): Fa2/0 on IPLC-RTR-MAA was shut during a change and not brought back',
    )
    expect(hint).toHaveTextContent('Fix: no shutdown on Fa2/0 (it worked)')
    expect(hint).toHaveTextContent(
      'Similar because: same subnets 192.168.100.0/24, 192.168.200.0/24; same site MAA, TRV',
    )
  })
})

describe('tokens', () => {
  const report = (tokens?: { input: number; output: number }): RunEvent => ({
    type: 'report',
    report: {
      outcome: 'answered',
      summary: 'x',
      root_cause: null,
      root_cause_evidence: [],
      affected: [],
      findings: [],
      next_steps: [],
      limitations: [],
    },
    confidence: 'high',
    confidence_reasons: [],
    tool_calls: 2,
    ...(tokens ? { tokens } : {}),
    at_ms: 9000,
  })

  it('the report says how many tokens the reply used', () => {
    const verdict = deriveInvestigation([report({ input: 17600, output: 800 })], []).verdict
    render(<ReportCard verdict={verdict!} onSelectEvidence={() => {}} />)
    expect(screen.getByText(/2 tool calls · 9\.0 s/)).toHaveTextContent('18.4k tokens')
  })

  it('older runs without a count show none', () => {
    const verdict = deriveInvestigation([report()], []).verdict
    render(<ReportCard verdict={verdict!} onSelectEvidence={() => {}} />)
    expect(screen.getByText(/2 tool calls/)).not.toHaveTextContent('tokens')
  })

  it('a case shows its tokens and the hints it was offered', () => {
    const item = { ...sample<Case>('fault1-pending'), tokens: 18400, hints_offered: ['case-old'] }
    render(
      <MemoryRouter>
        <CaseView item={item} />
      </MemoryRouter>,
    )
    expect(screen.getByText(/6 checks · 82\.3 s · 18\.4k tokens/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'case-old' })).toHaveAttribute(
      'href',
      '/cases/case-old',
    )
  })
})
