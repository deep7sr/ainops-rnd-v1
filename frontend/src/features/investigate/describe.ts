// What a tool call means, as one plain sentence an engineer can read while the agent works:
// "Checking the interfaces of IPLC-RTR-MAA" instead of get_interfaces({"device": "IPLC-RTR-MAA"}).

type Args = Record<string, unknown>

function arg(args: Args, name: string): string {
  const value = args[name]
  return typeof value === 'string' || typeof value === 'number' ? String(value) : '?'
}

const SENTENCES: Record<string, (args: Args) => string> = {
  get_topology_summary: () => 'Reading the network overview from the knowledge graph',
  list_devices: (a) =>
    `Listing the devices${a.site ? ` at ${arg(a, 'site')}` : ''}${a.role ? ` (${arg(a, 'role')})` : ''}`,
  find_device: (a) => `Looking up ${arg(a, 'query')} in the knowledge graph`,
  get_device_links: (a) => `Reading the links of ${arg(a, 'device')} from the knowledge graph`,
  get_path: (a) => `Working out the path from ${arg(a, 'source')} to ${arg(a, 'destination')}`,
  get_device_facts: (a) => `Reading the software version of ${arg(a, 'device')}`,
  get_interfaces: (a) => `Checking the interfaces of ${arg(a, 'device')}`,
  get_interface_detail: (a) =>
    `Checking ${arg(a, 'interface')} on ${arg(a, 'device')} for errors and flaps`,
  trace_route: (a) =>
    `Following the routing tables from ${arg(a, 'source')} to ${arg(a, 'destination')}`,
  get_routes: (a) =>
    `Checking the routing table of ${arg(a, 'device')}${
      a.destination ? ` for ${arg(a, 'destination')}` : ''
    }`,
  get_ospf_neighbors: (a) => `Checking the OSPF neighbours of ${arg(a, 'device')}`,
  get_routing_protocols: (a) => `Checking which routing protocols ${arg(a, 'device')} runs`,
  get_neighbors: (a) => `Checking which devices ${arg(a, 'device')} sees next to it`,
  get_arp_table: (a) => `Reading the ARP table of ${arg(a, 'device')}`,
  get_logs: (a) => `Reading the recent log messages of ${arg(a, 'device')}`,
  ping: (a) => `Pinging ${arg(a, 'destination')} from ${arg(a, 'device')}`,
  get_firewall_policies: (a) => `Reading the firewall policies of ${arg(a, 'device')}`,
  get_firewall_zones: (a) => `Reading the security zones of ${arg(a, 'device')}`,
}

export function describeCall(tool: string, args: Args): string {
  const sentence = SENTENCES[tool]
  return sentence ? sentence(args) : `Running ${tool}`
}

/** A short label for inside a device box on the map (about 26 characters fit). */
export function shortCall(tool: string): string {
  const labels: Record<string, string> = {
    get_interfaces: 'checking interfaces',
    get_interface_detail: 'checking an interface',
    get_routes: 'checking routes',
    trace_route: 'tracing the route',
    get_ospf_neighbors: 'checking OSPF',
    get_routing_protocols: 'checking routing',
    get_neighbors: 'checking neighbours',
    get_arp_table: 'reading ARP table',
    get_logs: 'reading logs',
    ping: 'pinging',
    get_device_facts: 'reading version',
    get_firewall_policies: 'reading policies',
    get_firewall_zones: 'reading zones',
  }
  return labels[tool] ?? tool
}
