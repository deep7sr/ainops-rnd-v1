import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { SkillCatalog, SkillHistoryEntry } from '@/api'
import { outcomeLabel, skillTitle } from './labels'
import { SkillsView } from './skills-page'

const NEVER = { count: 0, last_at: null, recent: [] }

const catalog: SkillCatalog = {
  skills: [
    {
      name: 'link-check',
      description: 'Use when one link looks down.',
      intro: 'Check both sides.',
      steps: ['`get_interfaces` on the router.\nAdmin down means shut.', '`ping` the other end.'],
      tools: ['get_interfaces', 'ping'],
      author: 'Praveen',
      reviewed_by: 'Praveen',
      path: 'link-check/SKILL.md',
      updated_by: '',
      updated_at: '',
      status: 'live',
      reviewed_at: '2026-10-06T10:00:00Z',
      version: 'v1',
      usage: {
        count: 7,
        last_at: '2026-10-07T09:00:00Z',
        recent: [
          {
            id: 'inv-2',
            title: 'Is the link up?',
            started_at: '2026-10-07T09:00:00Z',
            outcome: 'no_fault_found',
          },
          {
            id: 'inv-1',
            title: 'Why is MAA down?',
            started_at: '2026-10-05T09:00:00Z',
            outcome: null,
          },
        ],
      },
    },
    {
      name: 'ospf-neighbour-down',
      description: 'Use when two routers stop exchanging routes.',
      intro: '',
      steps: ['`get_ospf_neighbors` on both.'],
      tools: ['get_ospf_neighbors'],
      author: 'drafted by Claude',
      reviewed_by: '',
      path: 'ospf-neighbour-down/SKILL.md',
      updated_by: '',
      updated_at: '',
      status: 'draft',
      reviewed_at: '',
      version: 'v2',
      usage: NEVER,
    },
  ],
  problems: [{ folder: 'broken-one', problems: ['`get_routez` is not a tool'] }],
  tools_checked: true,
}

function show(selected?: string, data: SkillCatalog = catalog) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <SkillsView catalog={data} selected={selected} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function listed() {
  return within(screen.getByRole('list', { name: 'Skills' }))
    .getAllByRole('link')
    .map((link) => link.querySelector('span span')?.textContent)
}

describe('Skills page', () => {
  it('lists every skill, the broken ones too, and opens the first', () => {
    show()
    expect(listed()).toEqual(['Link check', 'OSPF neighbour down', 'Broken one'])
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Link check')
    const first = screen.getAllByRole('link', { current: true })
    expect(first).toHaveLength(1)
    expect(first[0]).toHaveAttribute('href', '/skills/link-check')
  })

  it('each row says the status, the number of steps and how often it was used', () => {
    show()
    const rows = within(screen.getByRole('list', { name: 'Skills' })).getAllByRole('listitem')
    expect(rows[0]).toHaveTextContent('Live')
    expect(rows[0]).toHaveTextContent(/2 steps · used 7× · last/)
    expect(rows[1]).toHaveTextContent('Draft')
    expect(rows[1]).toHaveTextContent('1 step · not used yet')
    expect(rows[2]).toHaveTextContent('Needs fixing')
    expect(rows[2]).toHaveTextContent('`get_routez` is not a tool')
  })

  it('opens the skill in the link with its sentence, steps, tools and file', () => {
    show('link-check')
    const article = screen.getByRole('article')
    expect(within(article).getByText('Live')).toBeInTheDocument()
    expect(within(article).getByRole('region', { name: 'Status' })).toHaveTextContent(
      /AINOPS uses this skill for every question it fits\.Reviewed by Praveen on/,
    )
    expect(within(article).getByRole('region', { name: 'When AINOPS uses it' })).toHaveTextContent(
      'Use when one link looks down.',
    )
    const steps = within(article).getByRole('list', { name: 'Steps of link-check' })
    expect(within(steps).getAllByRole('listitem')).toHaveLength(2)
    expect(within(steps).getByText('Admin down means shut.')).toBeInTheDocument()
    expect(within(article).getByRole('region', { name: 'Tools it uses' })).toHaveTextContent(
      'get_interfacesping',
    )
    expect(article).toHaveTextContent('skills/link-check/SKILL.md')
  })

  it('lists the investigations that used it, linked, with how they ended', () => {
    show('link-check')
    const used = screen.getByRole('region', { name: 'Used in investigations' })
    expect(used).toHaveTextContent('Used in investigations(7)')
    const links = within(used).getAllByRole('link')
    expect(links.map((l) => l.getAttribute('href'))).toEqual([
      '/investigations/inv-2',
      '/investigations/inv-1',
    ])
    expect(links[0]).toHaveTextContent('No fault found')
    expect(links[1]).toHaveTextContent('Running')
    expect(used).toHaveTextContent('The latest 2 are listed')
  })

  it('says when a skill was never used', () => {
    show('ospf-neighbour-down')
    expect(screen.getByRole('region', { name: 'Used in investigations' })).toHaveTextContent(
      'Not used yet.',
    )
    expect(screen.getByRole('region', { name: 'Status' })).toHaveTextContent('Not reviewed yet.')
  })

  it('a broken skill shows what to fix and where', () => {
    show('broken-one')
    expect(screen.getByRole('region', { name: 'What to fix' })).toHaveTextContent(
      '`get_routez` is not a tool',
    )
    expect(screen.getByText(/skills\/broken-one\/SKILL.md/)).toBeInTheDocument()
  })

  it('says so when the link names no skill', () => {
    show('no-such-skill')
    expect(screen.getByRole('alert')).toHaveTextContent('There is no skill named "no-such-skill"')
  })

  it('filters by status and searches names, sentences and tools', async () => {
    const user = userEvent.setup()
    show()
    await user.click(screen.getByRole('button', { name: /Drafts/ }))
    expect(listed()).toEqual(['OSPF neighbour down'])
    await user.click(screen.getByRole('button', { name: /Need fixing/ }))
    expect(listed()).toEqual(['Broken one'])
    await user.click(screen.getByRole('button', { name: /All/ }))
    await user.type(screen.getByRole('searchbox', { name: 'Search skills' }), 'ping')
    expect(listed()).toEqual(['Link check'])
    await user.clear(screen.getByRole('searchbox', { name: 'Search skills' }))
    await user.type(screen.getByRole('searchbox', { name: 'Search skills' }), 'zzz')
    expect(screen.getByText('No skill matches.')).toBeInTheDocument()
  })

  it('the filters show their counts', () => {
    show()
    expect(screen.getByRole('button', { name: /All/ })).toHaveTextContent('All3')
    expect(screen.getByRole('button', { name: /Live/ })).toHaveTextContent('Live1')
    expect(screen.getByRole('button', { name: /Off/ })).toHaveTextContent('Off0')
    expect(screen.getByRole('button', { name: /Drafts/ })).toHaveTextContent('Drafts1')
    expect(screen.getByRole('button', { name: /Need fixing/ })).toHaveTextContent('Need fixing1')
  })

  it('says when tool names could not be checked', () => {
    show(undefined, { ...catalog, tools_checked: false })
    expect(screen.getByRole('status')).toHaveTextContent('could not be checked')
  })

  it('explains what a skill is when there is none', () => {
    show(undefined, { skills: [], problems: [], tools_checked: true })
    expect(screen.getByText(/No skills yet/)).toBeInTheDocument()
  })
})

describe('skill words', () => {
  it('writes a skill name as a title, with network acronyms in capitals', () => {
    expect(skillTitle('site-to-site-unreachable')).toBe('Site to site unreachable')
    expect(skillTitle('ospf-neighbour-down')).toBe('OSPF neighbour down')
    expect(skillTitle('bgp-peer-flap')).toBe('BGP peer flap')
  })

  it('names how an investigation ended', () => {
    expect(outcomeLabel('diagnosed')).toBe('Root cause found')
    expect(outcomeLabel(null)).toBe('Running')
    expect(outcomeLabel('something_new')).toBe('something new')
  })
})

describe('editing and history from the Skills page', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('an opened skill links to its editor', () => {
    show('link-check')
    expect(screen.getByRole('link', { name: 'Edit' })).toHaveAttribute(
      'href',
      '/skills/link-check/edit',
    )
  })

  it('a broken skill cannot be edited on the page', () => {
    show('broken-one')
    expect(screen.queryByRole('link', { name: 'Edit' })).not.toBeInTheDocument()
  })

  it('History lists the replaced versions and opens one', async () => {
    const entry: SkillHistoryEntry = {
      id: '20261009T103000123456Z',
      replaced_at: '2026-10-09T10:30:00+00:00',
      saved_by: 'Praveen',
      saved_at: '2026-10-09T09:00:00+00:00',
      reviewed_by: 'Sudhir',
    }
    const old = { ...catalog.skills[0], intro: 'The old intro.' }
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        const respond = (body: unknown) => Promise.resolve(new Response(JSON.stringify(body)))
        if (url === '/api/skills/link-check/history') return respond([entry])
        if (url === `/api/skills/link-check/history/${entry.id}`)
          return respond({ skill: old, problems: [], markdown: '' })
        return Promise.resolve(new Response('{}', { status: 404 }))
      }),
    )
    const user = userEvent.setup()
    show('link-check')
    await user.click(screen.getByRole('button', { name: 'History' }))
    const versions = await screen.findByRole('list', { name: 'Earlier versions' })
    expect(versions).toHaveTextContent('saved by Praveen · reviewed by Sudhir')
    await user.click(within(versions).getByRole('button'))
    expect(await screen.findByText('The old intro.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'All versions' }))
    expect(await screen.findByRole('list', { name: 'Earlier versions' })).toBeInTheDocument()
  })

  it('says when a skill has no earlier versions', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(new Response('[]'))),
    )
    const user = userEvent.setup()
    show('link-check')
    await user.click(screen.getByRole('button', { name: 'History' }))
    expect(await screen.findByText(/No earlier versions/)).toBeInTheDocument()
  })
})
