import { act, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AgentHud } from './agent-hud'
import type { Hud } from './hud'

// The agent at work: what it says, and what moves only when something really happened.

const HUD: Hud = {
  loop: 'think',
  observed: 'E3',
  phase: 'reason',
  visited: new Set(['understand', 'locate', 'reason']),
  checks: 3,
  devices: 0,
  commands: 0,
  evidence: 3,
  topologyCalls: 3,
  networkCalls: 0,
  blocked: 0,
  running: null,
  lastCall: { key: 'E3', server: 'topology' },
  guardStopped: false,
  tokens: 21400,
  suspects: { todo: [], healthy: [], problem: [], cause: [] },
}

function show(
  hud: Partial<Hud> = {},
  running = true,
  clock: { ms: number; arrivedAt: number | null } = { ms: 0, arrivedAt: null },
) {
  return render(
    <AgentHud hud={{ ...HUD, ...hud }} running={running} clock={clock} deviceCount={8} />,
  )
}

const loopSays = () =>
  screen.getByRole('img', { name: /The agent's loop/ }).getAttribute('aria-label')
const strip = () => screen.getByRole('img', { name: /Behind the scenes/ })

afterEach(() => vi.useRealTimers())

describe('the agent at work', () => {
  it('names the phase it is in and the ones it went through', () => {
    show()
    const current = screen.getByRole('listitem', { current: 'step' })
    expect(current).toHaveTextContent('Reason')
    const phase = (name: string) =>
      screen.getAllByRole('listitem').find((li) => li.textContent?.startsWith(name))
    expect(phase('Locate')).toHaveTextContent('Locate (been through)')
    expect(phase('Verify')).toHaveTextContent(/^Verify$/)
    expect(current).toHaveTextContent(/^Reason$/)
  })

  it('counts what it did', () => {
    show({ devices: 2, commands: 4, evidence: 5, checks: 6 })
    expect(loopSays()).toBe("The agent's loop: thinking, 6 checks so far")
    expect(screen.getByText('Devices').closest('div')).toHaveTextContent('2')
    expect(screen.getByText('Commands').closest('div')).toHaveTextContent('4')
    expect(screen.getByText('Evidence').closest('div')).toHaveTextContent('5')
    expect(screen.getByText('AI tokens').closest('div')).toHaveTextContent('21.4k')
  })

  it('says nothing about tokens in runs recorded before they were counted', () => {
    show({ tokens: null })
    expect(screen.getByText('AI tokens').closest('div')).toHaveTextContent('–')
  })

  it('shows the system behind it, with its counts', () => {
    show({ topologyCalls: 1, networkCalls: 4, blocked: 2 })
    expect(strip()).toHaveAccessibleName(
      'Behind the scenes: the AI agent called the topology MCP server 1 time, which reads the knowledge graph, and the network MCP server 4 times, which runs read-only commands on the devices behind a safety guard (2 blocked).',
    )
    expect(strip()).toHaveTextContent('2 blocked')
    expect(strip()).toHaveTextContent('8 devices')
  })

  it('lights the guard red while the latest step is one it stopped', () => {
    show({ guardStopped: true, blocked: 1 })
    expect(screen.getByText('Guard').parentElement?.querySelector('rect')).toHaveClass(
      'stroke-status-critical',
    )
  })

  it('lights the servers a tool runs on', () => {
    show({ running: 'network', loop: 'act' })
    expect(screen.getByText('Network MCP').parentElement?.querySelector('rect')).toHaveClass(
      'stroke-primary',
    )
    expect(screen.getByText('Topology MCP').parentElement?.querySelector('rect')).toHaveClass(
      'stroke-border',
    )
  })

  it('sends a pulse along the wire for a new call only', () => {
    const view = show()
    expect(strip().querySelector('circle')).toBeNull() // the call that was there on opening
    view.rerender(
      <AgentHud
        hud={{
          ...HUD,
          loop: 'act',
          running: 'network',
          lastCall: { key: 'E4', server: 'network' },
        }}
        running
        clock={{ ms: 0, arrivedAt: null }}
        deviceCount={8}
      />,
    )
    expect(strip().querySelector('circle')).not.toBeNull()
  })

  it('observes for a moment when a result comes back, then thinks', () => {
    vi.useFakeTimers()
    const view = show({ loop: 'act', observed: null, running: 'network' })
    view.rerender(
      <AgentHud
        hud={{ ...HUD, observed: 'E4' }}
        running
        clock={{ ms: 0, arrivedAt: null }}
        deviceCount={8}
      />,
    )
    expect(loopSays()).toMatch(/reading a result/)
    act(() => vi.advanceTimersByTime(1600))
    expect(loopSays()).toMatch(/thinking/)
  })

  it('a finished run opened later keeps no timers going', () => {
    vi.useFakeTimers()
    show({ loop: null, phase: 'report' }, false, { ms: 82_297, arrivedAt: performance.now() })
    expect(vi.getTimerCount()).toBe(0)
  })

  it('does not observe the result that was there when the page opened', () => {
    show()
    expect(loopSays()).toMatch(/thinking/)
  })

  it('the clock goes on while the reply runs, and stops with it', () => {
    vi.useFakeTimers()
    const arrivedAt = performance.now()
    const view = show({}, true, { ms: 61_000, arrivedAt })
    const time = () => screen.getByText('Time').closest('div')
    expect(time()).toHaveTextContent('1:01')
    act(() => vi.advanceTimersByTime(3000))
    expect(time()).toHaveTextContent('1:04')
    view.rerender(
      <AgentHud
        hud={{ ...HUD, loop: null, phase: 'report' }}
        running={false}
        clock={{ ms: 82_297, arrivedAt }}
        deviceCount={8}
      />,
    )
    expect(time()).toHaveTextContent('1:22')
    expect(screen.getByText('finished')).toBeInTheDocument()
  })
})
