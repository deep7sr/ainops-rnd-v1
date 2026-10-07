import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { RunEvent, SkillCatalog } from '@/api'
import { deriveInvestigation } from '@/features/investigate/derive'
import { NowBanner } from '@/features/investigate/now-banner'
import { Timeline } from '@/features/investigate/timeline'
import { SkillsView } from './skills-page'

// An investigation that follows an expert skill, as the backend streams it (runner.py).

const STEPS = [
  '`get_interfaces` on the router.\nAdmin down means shut.',
  '`ping` the other end.',
  '`get_logs` on both routers.',
]

const started: RunEvent = { type: 'started', question: 'Is the link up?', tools: [], at_ms: 0 }
const opened: RunEvent = {
  type: 'skill',
  name: 'link-check',
  description: 'Use when one link looks down.',
  steps: STEPS,
  author: 'Praveen',
  reviewed_by: '',
  why: 'The question is about one link',
  at_ms: 5,
}

function check(id: string, tool: string, skillStep: number | null | undefined): RunEvent {
  return {
    type: 'tool_call',
    id,
    tool,
    server: 'network',
    args: { device: 'IPLC-RTR-MAA' },
    why: 'Following the skill',
    skill_step: skillStep,
    at_ms: 10,
  }
}

const NAMES = ['IPLC-RTR-MAA']

describe('following a skill', () => {
  it('shows the skill as a step and tags every check after it with its skill step', () => {
    const view = deriveInvestigation(
      [
        started,
        check('E1', 'get_device_facts', 1),
        opened,
        check('E2', 'get_interfaces', 1),
        check('E3', 'get_logs', 0),
      ],
      NAMES,
    )
    expect(view.skill?.name).toBe('link-check')
    expect(view.steps.map((s) => [s.kind, s.skillStep])).toEqual([
      ['tool', null], // before the skill was opened: no tag, whatever the model said
      ['skill', null],
      ['tool', 1],
      ['tool', 0],
    ])
  })

  it('the Now line names the skill and the step being done', () => {
    const view = deriveInvestigation([started, opened, check('E1', 'ping', 2)], NAMES)
    render(<NowBanner now={view.now} stepCount={view.steps.length} skill={view.skill} />)
    expect(screen.getByText(/Following skill/)).toHaveTextContent(
      'Following skill link-check · step 2 of 3: ping the other end.',
    )
  })

  it('the Now line says when the agent goes beyond the skill', () => {
    const view = deriveInvestigation([started, opened, check('E1', 'get_logs', 0)], NAMES)
    render(<NowBanner now={view.now} stepCount={view.steps.length} skill={view.skill} />)
    expect(screen.getByText(/Following skill/)).toHaveTextContent(
      'Following skill link-check · going beyond its steps',
    )
  })

  it('the finished line names the skill used', () => {
    const report: RunEvent = {
      type: 'report',
      report: {
        outcome: 'no_fault_found',
        summary: 'The link is up.',
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
      skills_used: ['link-check'],
      at_ms: 900,
    }
    const view = deriveInvestigation([started, opened, report], NAMES)
    render(<NowBanner now={view.now} stepCount={view.steps.length} skill={view.skill} />)
    expect(screen.getByText(/2 checks in/)).toHaveTextContent('· skill link-check')
  })

  it('the timeline lists the skill steps, its review state and the tag on each check', () => {
    const view = deriveInvestigation(
      [started, opened, check('E1', 'get_interfaces', 1), check('E2', 'get_logs', 0)],
      NAMES,
    )
    render(<Timeline steps={view.steps} focused={null} />)
    expect(screen.getByText('Using the expert skill "link-check"')).toBeInTheDocument()
    expect(screen.getByText('Draft · not reviewed')).toBeInTheDocument()
    const steps = screen.getByRole('list', { name: 'Steps of the skill' })
    expect(within(steps).getAllByRole('listitem')).toHaveLength(3)
    expect(within(steps).getByText('get_interfaces').tagName).toBe('CODE')
    expect(screen.getByText('Skill step 1')).toBeInTheDocument()
    expect(screen.getByText('Beyond the skill')).toBeInTheDocument()
  })

  it('a malformed skill event never breaks the page', () => {
    const junk = [
      { ...opened, name: 42 },
      { ...opened, steps: 'not a list' },
      { ...opened, steps: [1, null, 'only this'] },
    ] as unknown as RunEvent[]
    for (const event of junk) {
      const view = deriveInvestigation([started, event, check('E1', 'ping', 1)], NAMES)
      expect(() => render(<Timeline steps={view.steps} focused={null} />)).not.toThrow()
    }
    const view = deriveInvestigation([started, junk[2]], NAMES)
    expect(view.skill?.steps).toEqual(['only this'])
  })
})

describe('Skills page', () => {
  const catalog: SkillCatalog = {
    skills: [
      {
        name: 'link-check',
        description: 'Use when one link looks down.',
        intro: 'Check both sides.',
        steps: STEPS,
        tools: ['get_interfaces', 'ping', 'get_logs'],
        author: 'Praveen',
        reviewed_by: 'Praveen',
        path: 'link-check/SKILL.md',
      },
      {
        name: 'draft-one',
        description: 'Use for drafts.',
        intro: '',
        steps: ['`ping` it.'],
        tools: ['ping'],
        author: 'drafted by Claude',
        reviewed_by: '',
        path: 'draft-one/SKILL.md',
      },
    ],
    problems: [{ folder: 'broken', problems: ['`get_routez` is not a tool'] }],
    tools_checked: true,
  }

  it('shows each skill with its steps and whether it was reviewed', () => {
    render(<SkillsView catalog={catalog} />)
    expect(screen.getByRole('heading', { name: 'link-check' })).toBeInTheDocument()
    expect(screen.getByText('Reviewed by Praveen')).toBeInTheDocument()
    expect(screen.getByText('Draft · not reviewed')).toBeInTheDocument()
    const steps = screen.getByRole('list', { name: 'Steps of link-check' })
    expect(within(steps).getAllByRole('listitem')).toHaveLength(3)
    expect(within(steps).getByText('Admin down means shut.')).toBeInTheDocument()
  })

  it('lists the skills left out and what to fix', () => {
    render(<SkillsView catalog={catalog} />)
    const problems = screen.getByRole('region', { name: 'Skills that need fixing' })
    expect(problems).toHaveTextContent('skills/broken')
    expect(problems).toHaveTextContent('`get_routez` is not a tool')
  })

  it('says when tool names could not be checked', () => {
    render(<SkillsView catalog={{ ...catalog, problems: [], tools_checked: false }} />)
    expect(screen.getByRole('status')).toHaveTextContent('could not be checked')
  })
})
