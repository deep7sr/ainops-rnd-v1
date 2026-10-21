import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import type { RunEvent } from '@/api'
import { deriveInvestigation, touchesNetwork } from './derive'
import { Timeline } from './timeline'

// AINOPS's check before answering (backend runner.py, report.not_shown): the root cause blamed
// something no cited check showed, so the AI was sent back once to check it.

const DEVICES = ['CORE-SW-TRV', 'IPLC-RTR-MAA']
const started: RunEvent = { type: 'started', question: 'Why?', tools: [], at_ms: 0 }
const recheck: RunEvent = { type: 'recheck', blamed: ['CORE-SW-TRV Fa2/0'], at_ms: 9000 }

describe('the check before answering', () => {
  it('is a step of its own, never a network check or evidence', () => {
    const view = deriveInvestigation([started, recheck], DEVICES)
    expect(view.steps).toHaveLength(1)
    const [step] = view.steps
    expect(step.kind).toBe('recheck')
    expect(step.evidenceId).toBeNull()
    expect(step.device).toBeNull() // nothing lights up on the map
    expect(touchesNetwork(view.steps)).toBe(false)
    expect(step.sentence).toBe('AINOPS check: no check showed CORE-SW-TRV Fa2/0')
  })

  it('the timeline says what was not shown and that the AI was sent back', () => {
    const view = deriveInvestigation([started, recheck], DEVICES)
    render(
      <MemoryRouter>
        <Timeline steps={view.steps} focused={null} />
      </MemoryRouter>,
    )
    expect(screen.getByText('AINOPS check: no check showed CORE-SW-TRV Fa2/0')).toBeInTheDocument()
    expect(screen.getByText(/sent back to check it on that device/)).toBeInTheDocument()
  })
})
