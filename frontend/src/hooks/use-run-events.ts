import { useEffect, useState } from 'react'
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
 */
export function useRunEvents(runId: string | null): RunState {
  const [state, setState] = useState<RunState>({ events: [], done: false, error: null })

  useEffect(() => {
    if (!runId) return
    // Reset for the new run, then stream its events.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setState({ events: [], done: false, error: null })
    const source = new EventSource(`/api/runs/${runId}/events`)
    source.onmessage = (message: MessageEvent<string>) => {
      const event = JSON.parse(message.data) as RunEvent
      if (event.type === 'end') {
        source.close()
        setState((current) => ({ ...current, done: true }))
        return
      }
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
  }, [runId])

  return state
}
