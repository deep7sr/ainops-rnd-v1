import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { configure, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { RunEvent, SkillCatalog, SkillStatus } from '@/api'
import { deriveInvestigation } from '@/features/investigate/derive'
import { InvestigatePage } from '@/features/investigate/investigate-page'
import { Timeline } from '@/features/investigate/timeline'
import { SkillsView } from './skills-page'

vi.setConfig({ testTimeout: 30_000 })
configure({ asyncUtilTimeout: 5_000 })

function catalog(status: SkillStatus, reviewedBy: string): SkillCatalog {
  return {
    skills: [
      {
        name: 'link-check',
        description: 'Use when one link looks down.',
        intro: '',
        steps: ['`ping` the other end.'],
        tools: ['ping'],
        author: 'Praveen',
        reviewed_by: reviewedBy,
        path: 'link-check/SKILL.md',
        updated_by: 'Praveen',
        updated_at: '2026-10-08T09:00:00Z',
        status,
        reviewed_at: reviewedBy ? '2026-10-08T10:00:00Z' : '',
        usage: { count: 0, last_at: null, recent: [] },
        version: 'v1',
      },
    ],
    problems: [],
    tools_checked: true,
  }
}

let posts: { url: string; body: unknown }[]
let answer: { status: number; body: unknown }

beforeEach(() => {
  window.localStorage.clear()
  posts = []
  answer = { status: 200, body: {} }
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      const respond = (status: number, body: unknown) =>
        Promise.resolve(new Response(JSON.stringify(body), { status }))
      if (init?.method === 'POST') {
        posts.push({ url, body: JSON.parse(String(init.body)) })
        return respond(answer.status, answer.body)
      }
      if (url === '/api/skills/link-check/history')
        return respond(200, [
          {
            id: '20261009T103000123456Z',
            replaced_at: '2026-10-09T10:30:00+00:00',
            saved_by: 'Praveen',
            saved_at: '2026-10-09T09:00:00+00:00',
            reviewed_by: '',
          },
        ])
      if (url.startsWith('/api/skills/link-check/history/'))
        return respond(200, { skill: null, problems: [], markdown: 'old text' })
      if (url === '/api/investigations') return respond(200, [])
      return respond(404, { detail: 'unknown' })
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function Where() {
  const location = useLocation()
  return <p data-testid="where">{location.pathname + location.search}</p>
}

function show(status: SkillStatus, reviewedBy: string) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={['/skills/link-check']}>
        <Routes>
          <Route
            path="/skills/:name"
            element={<SkillsView catalog={catalog(status, reviewedBy)} selected="link-check" />}
          />
          <Route path="*" element={<p>elsewhere</p>} />
        </Routes>
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return screen.getByRole('region', { name: 'Status' })
}

describe('a skill’s status on the Skills page', () => {
  it('a new draft: not used, can be tried and reviewed, cannot go live yet', async () => {
    const panel = show('draft', '')
    expect(panel).toHaveTextContent('AINOPS does not use it yet.')
    expect(panel).toHaveTextContent('Not reviewed yet.')
    expect(within(panel).getByRole('link', { name: 'Try this skill' })).toHaveAttribute(
      'href',
      '/?try=link-check',
    )
    const review = within(panel).getByRole('button', { name: 'Mark reviewed' })
    expect(review).toBeDisabled() // no name yet
    const user = userEvent.setup()
    await user.type(within(panel).getByLabelText('Your name'), 'Sudhir')
    expect(within(panel).getByRole('button', { name: 'Make live' })).toBeDisabled() // not reviewed
    await user.click(review)
    await waitFor(() =>
      expect(posts).toEqual([
        {
          url: '/api/skills/link-check/review',
          body: { reviewer: 'Sudhir', version: 'v1' },
        },
      ]),
    )
    expect(window.localStorage.getItem('ainops.reviewer')).toBe('Sudhir')
  })

  it('a reviewed draft can go live', async () => {
    window.localStorage.setItem('ainops.reviewer', 'Sudhir')
    const panel = show('draft', 'Sudhir')
    expect(panel).toHaveTextContent('Reviewed and ready.')
    expect(panel).toHaveTextContent(/Reviewed by Sudhir on/)
    expect(within(panel).queryByRole('button', { name: 'Mark reviewed' })).not.toBeInTheDocument()
    await userEvent.setup().click(within(panel).getByRole('button', { name: 'Make live' }))
    await waitFor(() =>
      expect(posts).toEqual([
        {
          url: '/api/skills/link-check/status',
          body: { status: 'live', by: 'Sudhir', version: 'v1' },
        },
      ]),
    )
  })

  it('a live skill is used, and can be turned off (no need to try it)', async () => {
    window.localStorage.setItem('ainops.reviewer', 'Praveen')
    const panel = show('live', 'Sudhir')
    expect(panel).toHaveTextContent('AINOPS uses this skill for every question it fits.')
    expect(within(panel).queryByRole('link', { name: 'Try this skill' })).not.toBeInTheDocument()
    expect(within(panel).queryByRole('button', { name: 'Make live' })).not.toBeInTheDocument()
    await userEvent.setup().click(within(panel).getByRole('button', { name: 'Turn off' }))
    await waitFor(() =>
      expect(posts[0]).toEqual({
        url: '/api/skills/link-check/status',
        body: { status: 'off', by: 'Praveen', version: 'v1' },
      }),
    )
  })

  it('an off skill says it is not used and can go live again', () => {
    const panel = show('off', 'Sudhir')
    expect(panel).toHaveTextContent('AINOPS does not use this skill.')
    expect(within(panel).getByRole('button', { name: 'Make live' })).toBeInTheDocument()
  })

  it('says why a change was refused', async () => {
    window.localStorage.setItem('ainops.reviewer', 'Sudhir')
    answer = { status: 409, body: { detail: "'link-check' was changed by someone else" } }
    const panel = show('draft', '')
    await userEvent.setup().click(within(panel).getByRole('button', { name: 'Mark reviewed' }))
    expect(await within(panel).findByRole('alert')).toHaveTextContent(
      'Not changed: ' + "'link-check' was changed by someone else",
    )
  })

  it('History can restore an earlier version, saying it becomes a draft', async () => {
    window.localStorage.setItem('ainops.reviewer', 'Deependra')
    show('live', 'Sudhir')
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'History' }))
    const versions = await screen.findByRole('list', { name: 'Earlier versions' })
    await user.click(within(versions).getByRole('button'))
    expect(await screen.findByText(/becomes a draft that needs a new review/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Restore this version' }))
    await waitFor(() =>
      expect(posts).toEqual([
        {
          url: '/api/skills/link-check/restore',
          body: { entry: '20261009T103000123456Z', by: 'Deependra', version: 'v1' },
        },
      ]),
    )
    expect(await screen.findByRole('list', { name: 'Earlier versions' })).toBeInTheDocument()
  })
})

describe('trying a skill on the Investigate page', () => {
  function ask(path: string) {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/" element={<InvestigatePage />} />
            <Route path="/investigations/:id" element={<p>run</p>} />
          </Routes>
          <Where />
        </MemoryRouter>
      </QueryClientProvider>,
    )
  }

  it('says which skill is being tried and sends it with the question', async () => {
    answer = { status: 200, body: { id: 'inv-1' } }
    ask('/?try=link-check')
    expect(screen.getByRole('status')).toHaveTextContent('Trying the skill Link check')
    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Ask AINOPS about the network'), 'Is the link up?')
    await user.click(screen.getByRole('button', { name: 'Investigate' }))
    await waitFor(() =>
      expect(posts).toEqual([
        {
          url: '/api/investigations',
          body: { question: 'Is the link up?', try_skill: 'link-check' },
        },
      ]),
    )
  })

  it('can stop trying it, and a plain question sends no skill', async () => {
    answer = { status: 200, body: { id: 'inv-2' } }
    ask('/?try=link-check')
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Stop trying this skill' }))
    expect(screen.queryByText(/Trying the skill/)).not.toBeInTheDocument()
    await user.type(screen.getByLabelText('Ask AINOPS about the network'), 'Is the link up?')
    await user.click(screen.getByRole('button', { name: 'Investigate' }))
    await waitFor(() =>
      expect(posts).toEqual([
        { url: '/api/investigations', body: { question: 'Is the link up?' } },
      ]),
    )
  })
})

describe('the skill in an investigation’s timeline', () => {
  const started: RunEvent = { type: 'started', question: 'q', tools: [], at_ms: 0 }

  function opened(status: SkillStatus | undefined, reviewedBy = ''): RunEvent {
    return {
      type: 'skill',
      name: 'link-check',
      description: 'Use when one link looks down.',
      steps: ['`ping` it.'],
      author: 'Praveen',
      reviewed_by: reviewedBy,
      ...(status ? { status } : {}),
      at_ms: 5,
    }
  }

  it.each([
    ['live' as const, 'Live'],
    ['draft' as const, 'Draft · being tried'],
    ['off' as const, 'Off · being tried'],
  ])('a %s skill is shown as "%s"', (status, label) => {
    const view = deriveInvestigation([started, opened(status, 'Sudhir')], [])
    render(<Timeline steps={view.steps} focused={null} />)
    expect(screen.getByText(label)).toBeInTheDocument()
  })

  it('runs from before skills had a status still say whether it was reviewed', () => {
    const view = deriveInvestigation([started, opened(undefined, 'Sudhir')], [])
    render(<Timeline steps={view.steps} focused={null} />)
    expect(screen.getByText('Reviewed by Sudhir')).toBeInTheDocument()
  })
})
