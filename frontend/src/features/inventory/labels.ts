import type { DeviceStatus } from '@/api'

// Plain words for what the inventory holds (backend inventory_view.py).

const PLATFORMS: Record<string, string> = {
  cisco_ios: 'Cisco IOS',
  juniper_junos: 'Juniper Junos',
}

export function platformName(platform: string): string {
  return PLATFORMS[platform] ?? platform
}

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : 'unknown')

/** One sentence about a device's status, for the panel. */
export function statusSentence(status: DeviceStatus): string {
  if (status.state === 'reached') return `Answered the last discovery (${when(status.at)}).`
  if (status.state === 'not_reached') {
    return (
      `Did not answer the last discovery (${when(status.at)})` +
      (status.error ? `: ${status.error}` : '') +
      `. Last seen ${when(status.last_seen)}; its last known state is shown.`
    )
  }
  return 'No discovery has reached it yet: run discovery to add it to the knowledge graph.'
}
