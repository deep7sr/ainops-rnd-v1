// One icon per agent tool, so a step can be told apart at a glance: interfaces, routes, logs, a ping.
// Used in the timeline, the "Now" banner and the Tools page. Knowledge-graph tools and device tools
// keep their own colours (see the timeline); the icon says what the tool looks at.

import {
  Activity,
  Cable,
  Cpu,
  EthernetPort,
  Fence,
  ListTree,
  Network,
  Radar,
  Radio,
  Route,
  Router,
  ScanSearch,
  ScrollText,
  Share2,
  ShieldCheck,
  Signpost,
  Split,
  TableProperties,
  Waypoints,
  type LucideIcon,
} from 'lucide-react'

export const TOOL_ICON: Record<string, LucideIcon> = {
  // knowledge graph (topology MCP)
  get_topology_summary: Network,
  list_devices: ListTree,
  find_device: ScanSearch,
  get_device_links: Cable,
  get_path: Route,
  // live devices (network MCP)
  get_device_facts: Cpu,
  get_interfaces: EthernetPort,
  get_interface_detail: Activity,
  get_routes: Signpost,
  trace_route: Waypoints,
  get_ospf_neighbors: Share2,
  get_routing_protocols: Split,
  get_neighbors: Radar,
  get_arp_table: TableProperties,
  get_logs: ScrollText,
  ping: Radio,
  get_firewall_policies: ShieldCheck,
  get_firewall_zones: Fence,
}

/** For a tool added later without an icon of its own. */
export const FALLBACK_TOOL_ICON: LucideIcon = Router
