// Words for the Skills page.

const ACRONYMS = new Set([
  'acl',
  'arp',
  'bgp',
  'dhcp',
  'dns',
  'ip',
  'iplc',
  'isp',
  'lan',
  'mpls',
  'nat',
  'ospf',
  'qos',
  'sd',
  'stp',
  'vlan',
  'vpn',
  'vrf',
  'wan',
])

/** "ospf-neighbour-down" -> "OSPF neighbour down": the name as a person would write it. */
export function skillTitle(name: string): string {
  const words = name.split('-').filter(Boolean)
  return words
    .map((word, index) => {
      if (ACRONYMS.has(word)) return word.toUpperCase()
      return index === 0 ? word.charAt(0).toUpperCase() + word.slice(1) : word
    })
    .join(' ')
}

const OUTCOMES: Record<string, string> = {
  diagnosed: 'Root cause found',
  no_fault_found: 'No fault found',
  inconclusive: 'Inconclusive',
  refused: 'Refused',
  answered: 'Answered',
  stopped: 'Stopped',
  error: 'Error',
}

/** How an investigation ended, in words (null: still running). */
export function outcomeLabel(outcome: string | null): string {
  if (outcome === null) return 'Running'
  return OUTCOMES[outcome] ?? outcome.replaceAll('_', ' ')
}

/** "2026-10-07T09:50:00Z" -> "7 Oct 2026" in the viewer's locale. */
export function shortDate(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}
