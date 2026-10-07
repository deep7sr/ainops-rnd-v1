import type { RunEvent } from '@/api'
import { deriveInvestigation, type Verdict } from './derive'

// The conversation of an investigation, one entry per message the engineer sent and the reply
// to it (backend agent/conversation.py). The page shows earlier replies folded and the latest
// one in full, with the map and the live "Now" line.

/** The question plus up to 7 follow-ups; the server refuses more (MAX_MESSAGES). */
export const MAX_MESSAGES = 8

export interface Turn {
  number: number
  message: string
  /** When the engineer sent it; null for the question (the run's start time). */
  at: string | null
  verdict: Verdict | null
  /** Why the reply ended without a report: stopped by the engineer, or an error. */
  error: string | null
  /** Checks run for this reply (evidence ids), in order. */
  checks: string[]
  ended: 'report' | 'stopped' | 'error' | 'running'
}

export function conversationTurns(events: RunEvent[], deviceNames: string[]): Turn[] {
  const chunks: { message: string | null; at: string | null; events: RunEvent[] }[] = [
    { message: null, at: null, events: [] },
  ]
  for (const event of events) {
    if (event.type === 'message') chunks.push({ message: event.text, at: event.at, events: [] })
    else chunks[chunks.length - 1].events.push(event)
  }
  return chunks.map((chunk, index) => {
    const view = deriveInvestigation(chunk.events, deviceNames)
    const stopped = chunk.events.some((e) => e.type === 'stopped')
    return {
      number: index + 1,
      message: chunk.message ?? view.question ?? '',
      at: chunk.at,
      verdict: view.verdict,
      error: view.error,
      checks: view.steps.flatMap((s) => (s.evidenceId ? [s.evidenceId] : [])),
      ended: view.verdict ? 'report' : stopped ? 'stopped' : view.error ? 'error' : 'running',
    }
  })
}
