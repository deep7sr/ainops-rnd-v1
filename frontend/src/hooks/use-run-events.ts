import { useCallback, useEffect, useRef, useState } from 'react'
import type { RunEvent } from '@/api'

export interface RunState {
  events: RunEvent[]
  done: boolean
  error: string | null
}

/**
 * Follows one background run (an investigation or a discovery) as Server-Sent Events.
 * The server first replays every earlier event, then streams new ones, so opening an old
 * investigation or reconnecting shows the same steps as watching it live.
 *
 * An investigation is a conversation: after the engineer sends a follow-up, `resume()` listens
 * again for the reply. Events are numbered, so a resumed or reconnected stream only brings the
 * ones not received yet (the browser sends Last-Event-ID by itself when it reconnects).
 */
export function useRunEvents(runId: string | null): RunState & { resume: () => void } {
  const [state, setState] = useState<RunState>({ events: [], done: false, error: null })
  const [listening, setListening] = useState(0) // bumped by resume()
  const received = useRef({ runId: null as string | null, count: 0 })

  useEffect(() => {
    if (!runId) return
    if (received.current.runId !== runId) {
      // A new run: start over.
      received.current = { runId, count: 0 }
      setState({ events: [], done: false, error: null })
    }
    const source = new EventSource(`/api/runs/${runId}/events?after=${received.current.count}`)
    source.onmessage = (message: MessageEvent<string>) => {
      const event = JSON.parse(message.data) as RunEvent
      if (event.type === 'end') {
        source.close()
        setState((current) => ({ ...current, done: true }))
        return
      }
      received.current.count += 1
      setState((current) => ({ ...current, events: [...current.events, event] }))
    }
    source.onerror = () => {
      // EventSource reconnects by itself; only a closed stream is final.
      if (source.readyState === EventSource.CLOSED) {
        setState((current) =>
          current.done ? current : { ...current, error: 'Lost the connection to the server.' },
        )
      }
    }
    return () => source.close()
  }, [runId, listening])

  const resume = useCallback(() => {
    setState((current) => ({ ...current, done: false, error: null }))
    setListening((n) => n + 1)
  }, [])

  return { ...state, resume }
}
