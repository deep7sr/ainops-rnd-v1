# From POC to production: what changes

**Status:** notes, 2026-10-08. The POC on branch `demo/agentic` is built and tested on the 8-device
EVE-NG lab (two sites, TRV and MAA). This file lists what we know must change before AINOPS runs
on a real network of 1,000+ devices across many locations. Nothing here is built yet: it is the
starting list for the production design, to be refined after the leadership go-ahead and after a
synthetic scale test gives real numbers.

## What carries over unchanged

These design choices do not depend on network size and should stay:

- **The agent navigates, it does not read everything.** It finds the device in the knowledge
  graph, works out the path, and checks only the devices on it. The work grows with the problem,
  not with the network.
- **`trace_route` is walked by code**, hop by hop through the routing tables. A long path is still
  one tool call for the LLM.
- **One MCP server per system** AINOPS connects to (devices, topology, later vendor controllers such
  as Mist or Zscaler, or the vendors' own MCP servers).
- **Read-only by design.** Commands come only from a reviewed allowlist; the LLM never writes one.
- **Evidence and confidence.** Every fact in a report cites a check (E#); citations are verified and
  the confidence is computed by code.
- **Engineer-approved knowledge.** Skills, cases and hints are reviewed by people; hints are never
  evidence.
- **The Neo4j knowledge graph** itself (millions of nodes are normal for it), if Neo4j is allowed at
  UST (open question; a recently bought tool already stores devices and links as a graph).

## What must change

| Area | In the POC | Why it breaks at scale | Production direction |
|---|---|---|---|
| Routing tables | `get_routes` runs the whole table (`show ip route`, `show route`). Results are cut at 6,000 characters for the LLM. | Core and internet routers hold up to hundreds of thousands of routes: huge outputs, and data silently lost to the cut. | Ask for one destination (`show ip route <ip>`, `show route <ip>`); filter in code before the LLM sees anything. Never truncate without saying so. |
| Device access | Telnet to EVE-NG consoles; one session per device. | Real devices are reached by SSH on management networks, behind jump hosts and firewalls, in many regions. | Collectors near each region; SSH; connection pools with concurrency limits; structured APIs (NETCONF/RESTCONF, vendor APIs) where they exist. |
| Credentials | `.env` on the laptop (`AINOPS_CRED_<REF>_*`). | Not acceptable for production. | Vault (likely CyberArk); device login through TACACS with AD accounts, read-only command authorisation on the TACACS side as a second safety layer. |
| Inventory | Hand-written `lab/inventory.yaml`. | Nobody keeps 1,000+ devices in a file. | Sync from the source of truth (NetBox, CMDB, IPAM). The POC's Inventory page becomes a view of that, plus local additions. |
| Discovery | All devices each run, 4 at a time; interfaces, links and OSPF neighbours rebuilt fully. | Hours per run; some devices are always unreachable. | Incremental discovery per site on a schedule; store only changes; keep last-known state for silent devices (the POC already does this). |
| IP addresses and VRFs | `owner_of_ip` reads every interface per lookup; assumes every IP address is unique. Similar cases guess /24 subnets. | Slow; and wrong with VRFs, where the same address exists in several routing tables. | An address index in the graph; VRF awareness in the graph, `trace_route`, health rules and cases; real prefixes from IPAM. |
| The agent's instructions | The prompt names the two-site lab (TRV, MAA, leased line, OSPF). | Wrong for any other network. | Built from the inventory: sites, roles, WAN types. |
| WAN and design patterns | Skills cover one pattern: leased line with OSPF. | Real networks mix MPLS, SD-WAN, internet VPN, cloud, BGP. | More skills per pattern, written and reviewed by network SMEs. |
| Skill editing | Anyone who can open the Skills page can write, review, make live or change a skill (the person types their name; the author may review their own skill). Skills are files in `skills/` on the API's machine; replaced versions in `skills/<name>/history/`. | A skill's text goes into the AI's instructions: without logins, anyone can steer every investigation. Several API servers would not share one folder. | SSO and roles (writer, reviewer); a second person approves before a skill goes live; skills in shared storage or a database, with git export/import; history kept with the skill. |
| Vendors | Cisco IOS and Juniper (vSRX), parsed by hand. | NX-OS, IOS-XR, Arista, FortiGate, Palo Alto and more (next: FortiGate, Palo Alto). | Vendor "packs" (commands, parsers, health rules) as plugins, managed in the GUI by admins with import/export (Praveen, 10-06); ready-made parser libraries; vendor MCP servers where they exist. |
| Health rules | Written for the lab's Cisco IOS and Juniper vSRX. Losing only the first ping is treated as normal (ARP) when the reply marks show it (verified on Cisco output only). "Address but in no security zone" is a Junos SRX rule; it judges whole ports (a port counts as zoned if any of its units is in a zone) and costs a second command per zone check. | Other firewalls (Palo Alto, FortiGate) need their own rule; ports with many VLAN units can hide an unzoned unit; extra commands add up. | Rules per vendor pack, reviewed by network SMEs; judge per unit; reuse the interfaces result when the agent read it a few seconds earlier. |
| Network map | Hand-placed TRV and MAA columns; draws every device. | Unreadable at 1,000 devices. | Site overview, drill-down per site, and only the devices that matter to the question. |
| Run history | The API loads every saved investigation into memory at start. | Slow start, memory grows with every run. | A database (Postgres) with paging and retention. |
| Concurrency | One API process; one session per device, one check at a time. | Many engineers on one outage queue on the same devices and hit LLM rate limits. | A job queue and workers; reuse of outputs a few seconds old; per-user limits. |
| Similar cases | Loads all approved cases for every reply. | Fine for hundreds, slow for tens of thousands. | Search through the graph by device and subnet first; consider text similarity later. |
| Users and permissions | No login; reviewers type their name. | Anyone could add devices or approve cases. | SAML SSO; roles (engineer, reviewer, admin); four-eyes approval for cases and skills; per-site visibility. |
| LLM | Groq (developer tier) or company Azure OpenAI; tokens counted per reply since 10-08. | Cost grows with network size and output size. | Company LLM gateway; cost per run on screen; cheaper model for simple steps; budgets per user. |
| Operations | Laptop, `scripts/start-all.ps1`. | Not a service. | On-prem deployment, monitoring, backups (Neo4j, Postgres), log retention, security review of a tool that logs into devices. |

## Open questions that only a pilot will answer

- How accurate AINOPS is on a real, messy network, compared with a clean lab and deliberate faults.
- Tokens and cost per investigation at real scale.
- How quickly the case library grows into useful hints (lab fault drills and a "record a past
  incident" form can seed it).

## Suggested first steps when production work starts

1. Synthetic scale test: generate a 1,000-device, multi-site network with simulated devices and
   measure discovery time, graph lookups, map rendering and tokens per investigation. This shows
   which rows above hurt first.
2. Fix the rows that affect correctness first: targeted route lookups, VRF-aware addresses, the
   prompt from the inventory.
3. Then access and security (collectors, vault, TACACS, SSO), then scale (incremental discovery,
   database, queue).
