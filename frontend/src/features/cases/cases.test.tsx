import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Case, CaseStatus } from '@/api'
import { CaseSection } from './case-section'
import { CaseView } from './case-view'
import { CasesPage } from './cases-page'
import { ReviewBox } from './review-box'
import { missing } from './review-rules'

// Cases as the backend makes them (fixtures/cases/samples, written by backend tests/test_cases.py
// from investigations recorded on the live lab).

const files = import.meta.glob<Case>('../../../../fixtures/cases/samples/*.json', {
  eager: true,
  import: 'default',
})
const sample = (name: string) =>
  structuredClone(Object.entries(files).find(([p]) => p.endsWith(`/${name}.json`))?.[1] as Case)
const PENDING = sample('fault1-pending')
const CORRECTED = sample('fault1-corrected')
const BY_HAND = sample('healthy-by-hand')
const SECOND: Case = {
  ...sample('fault1-pending'),
  id: 'case-second',
  run_id: 'inv-second',
  question: 'Is the leased line between TRV and MAA healthy?',
}

// ---------- a fake API ----------

let posts: { url: string; body: unknown }[] = []
let reply: (url: string, body: unknown) => { status: number; body: unknown } = () => ({
  status: 404,
  body: {},
})

function respond(status: number, body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status }))
}

beforeEach(() => {
  posts = []
  window.localStorage.clear()
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      const body = init?.body ? JSON.parse(String(init.body)) : null
      if (init?.method === 'POST') posts.push({ url, body })
      const answer = reply(url, body)
      return respond(answer.status, answer.body)
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>
}

function show(node: ReactNode, path = '/') {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="*" element={node} />
        </Routes>
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const reviewed = (item: Case, status: CaseStatus) => ({ ...item, status })

// ---------- the rules the form helps with ----------

describe('what is still missing before a review can be saved', () => {
  it('names the first thing missing', () => {
    expect(missing(null, { action: 'approve', reviewer: 'D' })).toMatch(/Choose/)
    expect(missing('reject', { action: 'reject', reviewer: 'D', reason: '  ' })).toMatch(/why/)
    expect(missing('correct', { action: 'correct', reviewer: 'D' })).toMatch(/real root cause/)
    expect(missing('approve', { action: 'approve', reviewer: ' ' })).toMatch(/your name/)
    expect(missing('approve', { action: 'approve', reviewer: 'D' })).toBeNull()
  })
})

// ---------- the review box ----------

describe('the review box', () => {
  beforeEach(() => {
    reply = (url) =>
      url.endsWith('/review')
        ? { status: 200, body: reviewed(PENDING, 'approved') }
        : { status: 404, body: {} }
  })

  it('approves with the engineer’s name, and remembers the name', async () => {
    const user = userEvent.setup()
    show(<ReviewBox item={PENDING} />)
    const save = screen.getByRole('button', { name: 'Save review' })
    expect(save).toBeDisabled()
    await user.click(screen.getByRole('button', { name: /yes, approve/i }))
    expect(screen.getByText(/Type your name/)).toBeInTheDocument()
    await user.type(screen.getByLabelText('Your name'), 'Deependra')
    await user.click(save)
    expect(posts).toEqual([
      { url: '/api/cases/case-abc123/review', body: { action: 'approve', reviewer: 'Deependra' } },
    ])
    expect(window.localStorage.getItem('ainops.reviewer')).toBe('Deependra')
  })

  it('fills in the remembered name', () => {
    window.localStorage.setItem('ainops.reviewer', 'Praveen')
    show(<ReviewBox item={PENDING} />)
    expect(screen.getByLabelText('Your name')).toHaveValue('Praveen')
  })

  it('a reject needs a reason', async () => {
    const user = userEvent.setup()
    window.localStorage.setItem('ainops.reviewer', 'D')
    show(<ReviewBox item={PENDING} />)
    // A fix typed under "approve" is not sent with a reject.
    await user.click(screen.getByRole('button', { name: /yes, approve/i }))
    await user.type(screen.getByLabelText(/Fix applied/), 'no shutdown')
    await user.click(screen.getByRole('button', { name: /no, reject/i }))
    expect(screen.getByRole('button', { name: 'Save review' })).toBeDisabled()
    expect(screen.getByText('Say why the case is rejected.')).toBeInTheDocument()
    await user.type(screen.getByLabelText('Why is it wrong?'), 'wrong router')
    await user.click(screen.getByRole('button', { name: 'Save review' }))
    expect(posts[0].body).toEqual({ action: 'reject', reviewer: 'D', reason: 'wrong router' })
  })

  it('a correction starts from the AI’s root cause and can say what fixed it', async () => {
    const user = userEvent.setup()
    window.localStorage.setItem('ainops.reviewer', 'D')
    show(<ReviewBox item={PENDING} />)
    await user.click(screen.getByRole('button', { name: /correct it/i }))
    const cause = screen.getByLabelText('The real root cause')
    expect(cause).toHaveValue(PENDING.draft.root_cause)
    await user.clear(cause)
    await user.type(cause, 'Shut in a change window')
    await user.type(screen.getByLabelText(/Fix applied/), 'no shutdown')
    await user.click(screen.getByRole('button', { name: 'Yes' }))
    await user.click(screen.getByRole('button', { name: 'Save review' }))
    expect(posts[0].body).toEqual({
      action: 'correct',
      reviewer: 'D',
      root_cause: 'Shut in a change window',
      fix_applied: 'no shutdown',
      fix_worked: 'yes',
    })
  })

  it('a case without a root cause can only be corrected or rejected', () => {
    show(<ReviewBox item={BY_HAND} />)
    expect(screen.getByRole('button', { name: /yes, approve/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /correct it/i })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(screen.getByLabelText('The real root cause')).toHaveValue('')
  })

  it('shows why the server did not save the review', async () => {
    const user = userEvent.setup()
    reply = () => ({ status: 409, body: { detail: 'this case was already approved by Praveen' } })
    window.localStorage.setItem('ainops.reviewer', 'D')
    show(<ReviewBox item={PENDING} />)
    await user.click(screen.getByRole('button', { name: /yes, approve/i }))
    await user.click(screen.getByRole('button', { name: 'Save review' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Not saved: this case was already approved by Praveen',
    )
  })
})

// ---------- a case ----------

describe('a case', () => {
  it('shows the engineer’s correction next to what the AI said', () => {
    show(<CaseView item={CORRECTED} />)
    expect(screen.getByText('Root cause (engineer)')).toBeInTheDocument()
    expect(screen.getByText(/was shut during a change and not brought back/)).toBeInTheDocument()
    expect(screen.getByText('AINOPS said')).toBeInTheDocument()
    expect(screen.getByText(CORRECTED.draft.root_cause as string)).toBeInTheDocument()
    expect(screen.getByText(/Corrected and approved by Praveen/)).toBeInTheDocument()
    expect(screen.getByText('Fix applied: no shutdown on Fa2/0 (it worked)')).toBeInTheDocument()
  })

  it('shows the proof, the devices, the path and the link to the investigation', () => {
    show(<CaseView item={PENDING} />)
    expect(screen.getByText('Pending review')).toBeInTheDocument()
    const proof = screen.getByText('Proof (from the live devices)').parentElement as HTMLElement
    expect(within(proof).getByText('E6')).toBeInTheDocument()
    expect(within(proof).getByText(/with an address but not up: Fa2\/0/)).toBeInTheDocument()
    expect(screen.getByText('IPLC-RTR-MAA Fa2/0')).toBeInTheDocument()
    expect(
      screen.getByText('CORE-SW-TRV → IPLC-RTR-TRV → IPLC-RTR-MAA → CORE-SW-MAA'),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /See how AINOPS worked it out/ })).toHaveAttribute(
      'href',
      '/investigations/inv-abc123',
    )
  })
})

// ---------- the Cases page ----------

describe('the Cases page', () => {
  beforeEach(() => {
    reply = (url) => {
      if (url === '/api/cases?status=pending')
        return {
          status: 200,
          body: { cases: [PENDING, SECOND], counts: { pending: 2, approved: 1, rejected: 0 } },
        }
      if (url === '/api/cases?status=approved')
        return {
          status: 200,
          body: { cases: [CORRECTED], counts: { pending: 2, approved: 1, rejected: 0 } },
        }
      if (url === '/api/cases/case-second') return { status: 200, body: SECOND }
      if (url.endsWith('/review')) return { status: 200, body: reviewed(PENDING, 'approved') }
      return { status: 404, body: { detail: 'unknown' } }
    }
  })

  it('lists the cases waiting for review with counts and opens the first', async () => {
    show(<CasesPage />, '/cases')
    expect(await screen.findByRole('tab', { name: /Pending review\s*2/ })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(screen.getByRole('tab', { name: /Approved\s*1/ })).toBeInTheDocument()
    const list = screen.getByRole('list', { name: 'pending cases' })
    expect(within(list).getAllByRole('link')).toHaveLength(2)
    expect(screen.getByRole('article', { name: 'Case case-abc123' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Review this case' })).toBeInTheDocument()
  })

  it('after a review it moves on to the next case waiting', async () => {
    const user = userEvent.setup()
    window.localStorage.setItem('ainops.reviewer', 'D')
    show(<CasesPage />, '/cases')
    await user.click(await screen.findByRole('button', { name: /yes, approve/i }))
    await user.click(screen.getByRole('button', { name: 'Save review' }))
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/cases/case-second'))
  })

  it('an approved case has no review box', async () => {
    const user = userEvent.setup()
    show(<CasesPage />, '/cases')
    await user.click(await screen.findByRole('tab', { name: /Approved/ }))
    expect(await screen.findByText('Root cause (engineer)')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Review this case' })).not.toBeInTheDocument()
  })
})

// ---------- under the report on the Investigate page ----------

describe('the case under the report', () => {
  const section = (outcome: 'diagnosed' | 'inconclusive', notSaved: string | null = null) => (
    <CaseSection runId="inv-x" outcome={outcome} caseEvents={1} notSaved={notSaved} />
  )

  it('a pending case is reviewed right there', async () => {
    reply = () => ({ status: 200, body: { case: PENDING, can_make: false } })
    show(section('diagnosed'))
    expect(await screen.findByText('Was this diagnosis right?')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Open the case/ })).toHaveAttribute(
      'href',
      '/cases/case-abc123',
    )
  })

  it('a reviewed case says so and who reviewed it', async () => {
    reply = () => ({ status: 200, body: { case: CORRECTED, can_make: false } })
    show(section('diagnosed'))
    expect(await screen.findByText('Approved')).toBeInTheDocument()
    expect(screen.getByText(/by Praveen, with a corrected root cause/)).toBeInTheDocument()
  })

  it('after an inconclusive reply the engineer can make a case', async () => {
    const user = userEvent.setup()
    reply = (url) =>
      url === '/api/runs/inv-x/case' && posts.length
        ? { status: 200, body: BY_HAND }
        : { status: 200, body: { case: null, can_make: true } }
    show(section('inconclusive'))
    expect(await screen.findByText(/could not find the cause/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Make a case' }))
    expect(posts).toEqual([{ url: '/api/runs/inv-x/case', body: null }])
  })

  it('a case that could not be saved is said plainly', () => {
    reply = () => ({ status: 200, body: { case: null, can_make: false } })
    show(section('diagnosed', 'case not saved: ConnectionError'))
    expect(screen.getByRole('alert')).toHaveTextContent(
      'The case for this diagnosis was not saved (ConnectionError)',
    )
  })
})
