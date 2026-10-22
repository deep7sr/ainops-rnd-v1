import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { RunEvent } from '@/api'
import { deriveInvestigation, type ActiveSkill } from './derive'
import { NowBanner } from './now-banner'
import { SuspectBoard } from './suspect-board'
import { Timeline } from './timeline'

afterEach(() => vi.useRealTimers())

const BOARD = {
  todo: [{ device: 'CORE-SW-MAA', checking: false, note: null }],
  healthy: [
    { device: 'CORE-SW-TRV', checking: false, note: null },
    { device: 'IPLC-RTR-TRV', checking: false, note: null },
  ],
  problem: [{ device: 'IPLC-RTR-MAA', checking: true, note: 'Fa2/0 is administratively down' }],
  cause: [],
}

describe('the suspect board', () => {
  it('puts each device in its column, with the problem seen', () => {
    render(<SuspectBoard board={BOARD} roles={new Map()} onSelect={() => {}} />)
    const column = (name: string) => screen.getByRole('group', { name })
    expect(within(column('Not checked yet')).getByRole('button')).toHaveTextContent('CORE-SW-MAA')
    expect(
      within(column('Checked, no problem found'))
        .getAllByRole('button')
        .map((b) => b.textContent),
    ).toEqual(['CORE-SW-TRV', 'IPLC-RTR-TRV'])
    expect(within(column('Problem seen')).getByRole('button')).toHaveTextContent(
      'IPLC-RTR-MAA(being checked now)Fa2/0 is administratively down',
    )
    expect(column('Root cause')).toHaveTextContent('Root cause0None')
  })

  it('opens what was found on a device', async () => {
    const onSelect = vi.fn()
    render(<SuspectBoard board={BOARD} roles={new Map()} onSelect={onSelect} />)
    await userEvent.click(screen.getByRole('button', { name: /IPLC-RTR-TRV/ }))
    expect(onSelect).toHaveBeenCalledWith('IPLC-RTR-TRV')
  })
})

const started: RunEvent = { type: 'started', question: 'Why?', tools: [], at_ms: 0 }
const call = (id: string, why = ''): RunEvent => ({
  type: 'tool_call',
  id,
  tool: 'get_interfaces',
  server: 'network',
  args: { device: 'IPLC-RTR-MAA' },
  why,
  skill_step: 2,
  at_ms: 1,
})

describe('the Now line', () => {
  it('types the why out; screen readers get it whole at once', () => {
    vi.useFakeTimers()
    const why = 'Check interface status on MAA side of leased line'
    const view = deriveInvestigation([started, call('E1', why)], ['IPLC-RTR-MAA'])
    render(<NowBanner now={view.now} stepCount={1} />)
    const typed = () => screen.getByText(why, { selector: '.sr-only' }).previousElementSibling!
    expect(screen.getByText(why, { selector: '.sr-only' })).toBeInTheDocument()
    act(() => vi.advanceTimersByTime(100))
    expect(typed().textContent).toBe(why.slice(0, 10))
    act(() => vi.advanceTimersByTime(1000))
    expect(typed().textContent).toBe(why)
    expect(vi.getTimerCount()).toBe(0) // done typing: nothing keeps running
  })

  it('shows how far the skill got as a rail', () => {
    const skill: ActiveSkill = {
      name: 'link-check',
      description: '',
      steps: ['a', 'b', 'c', 'd'],
      author: '',
      reviewedBy: '',
    }
    const opened: RunEvent = { type: 'skill', ...skill, reviewed_by: '', at_ms: 1 }
    const view = deriveInvestigation([started, opened, call('E1')], ['IPLC-RTR-MAA'])
    const { container } = render(
      <NowBanner now={view.now} stepCount={1} skill={skill} skillReached={3} />,
    )
    const rail = [...container.querySelectorAll('.h-1.w-5')].map((s) =>
      s.classList.contains('animate-pulse')
        ? 'now'
        : s.classList.contains('bg-border')
          ? 'todo'
          : 'done',
    )
    // The running check carries out step 2; the reply already got to step 3 before.
    expect(rail).toEqual(['done', 'now', 'done', 'todo'])
  })
})

describe('the timeline line', () => {
  it('is drawn down from a step that is done, not from one still running', () => {
    const result: RunEvent = {
      type: 'tool_result',
      id: 'E1',
      tool: 'get_interfaces',
      server: 'network',
      device: 'IPLC-RTR-MAA',
      ok: true,
      summary: 'done',
      data: null,
      evidence: null,
      duration_ms: 5,
      at_ms: 2,
    }
    // E2 and E3 were asked for together: E2 still runs while E3 is shown under it.
    const view = deriveInvestigation(
      [started, call('E1'), result, call('E2'), call('E3')],
      ['IPLC-RTR-MAA'],
    )
    const { container } = render(<Timeline steps={view.steps} focused={null} />)
    const lines = [...container.querySelectorAll('.origin-top')].map(
      (line) => (line as HTMLElement).style.transform,
    )
    expect(lines).toEqual(['none', 'scaleY(0)'])
  })
})
