import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import type { SkillCatalog } from '@/api'
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
      usage: NEVER,
    },
  ],
  problems: [{ folder: 'broken-one', problems: ['`get_routez` is not a tool'] }],
  tools_checked: true,
}

function show(selected?: string, data: SkillCatalog = catalog) {
  return render(
    <MemoryRouter>
      <SkillsView catalog={data} selected={selected} />
    </MemoryRouter>,
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
    expect(rows[0]).toHaveTextContent('Reviewed')
    expect(rows[0]).toHaveTextContent(/2 steps · used 7× · last/)
    expect(rows[1]).toHaveTextContent('Draft')
    expect(rows[1]).toHaveTextContent('1 step · not used yet')
    expect(rows[2]).toHaveTextContent('Needs fixing')
    expect(rows[2]).toHaveTextContent('`get_routez` is not a tool')
  })

  it('opens the skill in the link with its sentence, steps, tools and file', () => {
    show('link-check')
    const article = screen.getByRole('article')
    expect(within(article).getByText('Reviewed by Praveen')).toBeInTheDocument()
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
    expect(screen.getByText('Draft · not reviewed')).toBeInTheDocument()
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
    expect(screen.getByRole('button', { name: /Reviewed/ })).toHaveTextContent('Reviewed1')
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
