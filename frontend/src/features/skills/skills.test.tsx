import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { RunEvent } from '@/api'
import { deriveInvestigation } from '@/features/investigate/derive'
import { NowBanner } from '@/features/investigate/now-banner'
import { Timeline } from '@/features/investigate/timeline'

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
