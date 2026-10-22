import { describe, expect, it } from 'vitest'
import type { Report, RunEvent } from '@/api'
import { deriveInvestigation } from './derive'
import { deriveHud, lastTime } from './hud'

const DEVICES = [
  'ISP-TRV-1',
  'FWL-TRV',
  'CORE-SW-TRV',
  'IPLC-RTR-TRV',
  'IPLC-RTR-MAA',
  'CORE-SW-MAA',
  'FWL-MAA',
  'ISP-MAA-1',
]
const ON_MAP = new Set(DEVICES)

function hudOf(events: RunEvent[]) {
  const view = deriveInvestigation(events, DEVICES)
  return deriveHud(view, view.now, events, ON_MAP)
}

const files = import.meta.glob<{ events: RunEvent[] }>('../../../../fixtures/runs/*.json', {
  eager: true,
  import: 'default',
})
const fault1 = Object.entries(files).find(([path]) =>
  path.endsWith('/fault1-leased-line-shut-run1.json'),
)![1].events

/** The recorded run up to and including its event number `n` (counted from 1). */
const upTo = (n: number) => fault1.slice(0, n)

const names = (list: { device: string }[]) => list.map((s) => s.device)

describe('the HUD of a recorded run (fault 1, Fa2/0 shut on IPLC-RTR-MAA)', () => {
  it('at the end: the counts, the phases and the board', () => {
    const hud = hudOf(fault1)
    expect(hud).toMatchObject({
      loop: null,
      phase: 'report',
      checks: 6,
      topologyCalls: 3,
      networkCalls: 3,
      commands: 3,
      evidence: 6,
      devices: 3,
      blocked: 0,
      tokens: null, // recorded before tokens were counted
    })
    expect([...hud.visited]).toEqual(['understand', 'locate', 'check', 'reason', 'report'])
    expect(hud.suspects.cause).toEqual([{ device: 'IPLC-RTR-MAA', checking: false, note: 'Fa2/0' }])
    expect(names(hud.suspects.healthy)).toEqual(['CORE-SW-TRV', 'IPLC-RTR-TRV'])
    expect(names(hud.suspects.todo)).toEqual(['CORE-SW-MAA']) // on the path, never checked
    expect(hud.suspects.problem).toEqual([])
  })

  it('while a command runs on IPLC-RTR-MAA: act, check live, the device marked as checking', () => {
    const hud = hudOf(upTo(18))
    expect(hud).toMatchObject({ loop: 'act', phase: 'check', observed: null, commands: 3 })
    expect(hud.suspects.todo).toEqual([
      { device: 'IPLC-RTR-MAA', checking: true, note: null },
      { device: 'CORE-SW-MAA', checking: false, note: null },
    ])
  })

  it('when its result is back: the AI thinks, the problem is on the board', () => {
    const hud = hudOf(upTo(19))
    expect(hud).toMatchObject({ loop: 'think', phase: 'reason', observed: 'E6' })
    expect(hud.suspects.problem).toEqual([
      { device: 'IPLC-RTR-MAA', checking: false, note: 'Fa2/0 is administratively down (shut)' },
    ])
    expect(lastTime(upTo(19))).toEqual({ ms: 54594, index: 18 })
  })

  it('locating in the knowledge graph', () => {
    const hud = hudOf(upTo(9))
    expect(hud).toMatchObject({ loop: 'act', phase: 'locate', running: 'topology' })
    expect(hud.lastCall).toEqual({ key: 'E3', server: 'topology' })
    expect(hudOf(upTo(10)).running).toBeNull() // its result is back
  })

  it('reading the question', () => {
    const hud = hudOf(upTo(1))
    expect(hud).toMatchObject({ loop: 'think', phase: 'understand', observed: null, checks: 0 })
    expect([...hud.visited]).toEqual(['understand'])
  })
})

const started: RunEvent = { type: 'started', question: 'Why?', tools: [], at_ms: 0 }

function call(id: string, tool: string, server: string, device?: string): RunEvent {
  return {
    type: 'tool_call',
    id,
    tool,
    server,
    args: device ? { device } : {},
    at_ms: 1,
  }
}

function result(
  id: string,
  tool: string,
  server: string,
  extra: Partial<Extract<RunEvent, { type: 'tool_result' }>> = {},
): RunEvent {
  return {
    type: 'tool_result',
    id,
    tool,
    server,
    device: null,
    ok: true,
    summary: 'done',
    data: null,
    evidence: null,
    duration_ms: 1,
    at_ms: 2,
    ...extra,
  }
}

const REPORT: Report = {
  outcome: 'answered',
  summary: 'x',
  root_cause: null,
  root_cause_evidence: [],
  affected: [],
  findings: [],
  next_steps: [],
  limitations: [],
}

function report(tokens?: { input: number; output: number }): RunEvent {
  return {
    type: 'report',
    report: REPORT,
    confidence: 'low',
    confidence_reasons: [],
    tool_calls: 0,
    tokens,
    at_ms: 9,
  }
}

const thought = (input: number, output: number): RunEvent => ({
  type: 'thought',
  text: '',
  tools: [],
  tokens: { input, output },
  at_ms: 3,
})

describe('the AI tokens', () => {
  it('count up with each thought, and every reply of the conversation adds up', () => {
    expect(hudOf([started, thought(100, 10)]).tokens).toBe(110)
    expect(hudOf([started, thought(100, 10), thought(300, 20)]).tokens).toBe(320)
    const second: RunEvent[] = [
      started,
      thought(100, 10),
      report({ input: 400, output: 30 }), // the report has the reply's total
      { type: 'message', turn: 2, text: 'And MAA?', at: '' },
      thought(50, 5),
    ]
    expect(hudOf(second).tokens).toBe(430 + 55)
  })

  it('a follow-up that has not thought yet adds nothing', () => {
    const events: RunEvent[] = [
      started,
      report({ input: 400, output: 30 }),
      { type: 'message', turn: 2, text: 'And MAA?', at: '' },
    ]
    expect(hudOf(events).tokens).toBe(430)
  })

  it('are unknown in runs recorded before they were counted', () => {
    expect(hudOf([started, report()]).tokens).toBeNull()
  })
})

describe('what the counters count', () => {
  it('a command the tool or the guard turned down never reached a device', () => {
    const hud = hudOf([
      started,
      call('E1', 'get_routes', 'network', 'IPLC-RTR-TRV'),
      result('E1', 'get_routes', 'network', {
        ok: false,
        failure: 'request',
        summary: 'not a valid address',
      }),
      call('E2', 'run_show', 'network', 'IPLC-RTR-TRV'),
      result('E2', 'run_show', 'network', {
        ok: false,
        failure: 'blocked',
        summary: 'the safety check refused the command',
      }),
      call('E3', 'get_interfaces', 'network', 'IPLC-RTR-TRV'),
    ])
    expect(hud).toMatchObject({ checks: 3, networkCalls: 3, commands: 1, evidence: 0, blocked: 1 })
    expect(hud).toMatchObject({ running: 'network', guardStopped: false })
    expect(hud.lastCall).toEqual({ key: 'E3', server: 'network' })
  })

  it('a refusal by a safety rule is blocked; the check limit is not', () => {
    const refused = (rule: 'address' | 'budget'): RunEvent => ({
      type: 'refused',
      tool: 'ping',
      args: { device: 'IPLC-RTR-TRV' },
      reason: rule,
      rule,
      at_ms: 1,
    })
    expect(hudOf([started, refused('address'), refused('budget')]).blocked).toBe(1)
    // The guard lights while the latest step is one it stopped.
    expect(hudOf([started, refused('address')]).guardStopped).toBe(true)
    expect(hudOf([started, refused('address'), refused('budget')]).guardStopped).toBe(false)
  })

  it('the clock starts again with each reply', () => {
    const events: RunEvent[] = [
      started,
      thought(1, 1),
      { type: 'message', turn: 2, text: 'And MAA?', at: '' },
    ]
    expect(lastTime(events.slice(0, 2))).toEqual({ ms: 3, index: 1 })
    expect(lastTime(events)).toEqual({ ms: 0, index: 2 })
    expect(lastTime([])).toEqual({ ms: 0, index: -1 })
  })
})

describe('the phases', () => {
  it('after a recheck the agent verifies', () => {
    const hud = hudOf([
      started,
      call('E1', 'get_interfaces', 'network', 'IPLC-RTR-TRV'),
      result('E1', 'get_interfaces', 'network'),
      { type: 'recheck', blamed: ['IPLC-RTR-MAA'], at_ms: 3 },
    ])
    expect(hud.phase).toBe('verify')
    expect([...hud.visited]).toEqual(['understand', 'check', 'reason', 'verify'])
    expect(hud.observed).toBe('E1') // a recheck is not a result: nothing new came back
  })

  it('it was verifying once it checks again after a recheck', () => {
    const hud = hudOf([
      started,
      call('E1', 'get_interfaces', 'network', 'IPLC-RTR-TRV'),
      result('E1', 'get_interfaces', 'network'),
      { type: 'recheck', blamed: ['IPLC-RTR-MAA'], at_ms: 3 },
      call('E2', 'get_interfaces', 'network', 'IPLC-RTR-MAA'),
    ])
    expect(hud.phase).toBe('check')
    expect(hud.visited.has('verify')).toBe(true)
  })

  it('reasoning starts when the first result is back', () => {
    const hud = hudOf([
      started,
      call('E1', 'get_path', 'topology'),
      result('E1', 'get_path', 'topology'),
    ])
    expect(hud.phase).toBe('reason')
    expect([...hud.visited]).toEqual(['understand', 'locate', 'reason'])
  })

  it('two checks still running: no result read yet', () => {
    const hud = hudOf([
      started,
      call('E1', 'get_interfaces', 'network', 'IPLC-RTR-TRV'),
      call('E2', 'get_interfaces', 'network', 'IPLC-RTR-MAA'),
    ])
    expect([...hud.visited]).toEqual(['understand', 'check'])
  })

  it('an answer without any check was still reasoned', () => {
    expect([...hudOf([started, report()]).visited]).toEqual(['understand', 'reason', 'report'])
  })

  it('before its first tool the agent is still on the question', () => {
    const hints: RunEvent = { type: 'hints', cases: [], looked_at: 0, at_ms: 1 }
    expect(hudOf([started, hints]).phase).toBe('understand')
  })

  it('stopped: no phase now, the ones it went through stay', () => {
    const hud = hudOf([
      started,
      call('E1', 'get_path', 'topology'),
      result('E1', 'get_path', 'topology'),
      { type: 'error', message: 'boom' },
    ])
    expect(hud).toMatchObject({ phase: null, loop: null, observed: null })
    expect([...hud.visited]).toEqual(['understand', 'locate'])
  })

  it('a follow-up starts its phases again', () => {
    const hud = hudOf([
      started,
      call('E1', 'get_path', 'topology'),
      result('E1', 'get_path', 'topology'),
      report(),
      { type: 'message', turn: 2, text: 'And MAA?', at: '' },
    ])
    expect(hud.phase).toBe('understand')
    expect([...hud.visited]).toEqual(['understand'])
  })
})

describe('the suspect board', () => {
  it('a device that did not answer is a problem; one that rejected the command was checked', () => {
    const hud = hudOf([
      started,
      call('E1', 'get_interfaces', 'network', 'FWL-MAA'),
      result('E1', 'get_interfaces', 'network', {
        ok: false,
        failure: 'unreachable',
        summary: 'FWL-MAA did not answer on the console',
      }),
      call('E2', 'get_interfaces', 'network', 'FWL-TRV'),
      result('E2', 'get_interfaces', 'network', {
        ok: false,
        failure: 'rejected',
        summary: 'FWL-TRV rejected the command',
      }),
    ])
    expect(hud.suspects.problem).toEqual([
      { device: 'FWL-MAA', checking: false, note: 'Did not answer' },
    ])
    expect(names(hud.suspects.healthy)).toEqual(['FWL-TRV'])
  })

  it('a device checked again keeps its place while the check runs', () => {
    const problem = {
      health: {
        status: 'problem' as const,
        issues: [{ text: 'Fa2/0 is down', interface: 'Fa2/0' }],
      },
    }
    const hud = hudOf([
      started,
      call('E1', 'get_interfaces', 'network', 'IPLC-RTR-MAA'),
      result('E1', 'get_interfaces', 'network', problem),
      call('E2', 'get_ospf_neighbors', 'network', 'IPLC-RTR-MAA'),
    ])
    expect(hud.suspects.problem).toEqual([
      { device: 'IPLC-RTR-MAA', checking: true, note: 'Fa2/0 is down' },
    ])
    expect(hud.suspects.todo).toEqual([])
  })

  it('only devices on the map', () => {
    const hud = hudOf([
      started,
      call('E1', 'get_interfaces', 'network', 'LAPTOP-7'),
      result('E1', 'get_interfaces', 'network'),
    ])
    expect(Object.values(hud.suspects).flat()).toEqual([])
  })
})
