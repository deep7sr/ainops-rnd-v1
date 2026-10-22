# Production architecture: where data lives, how the map stays right

**Status:** target design, 2026-10-22. Nothing here is built yet. The user's decision is to design now
and build after the leadership demo, one phase at a time, each with its own plan approved first.
It extends [production-readiness.md](production-readiness.md) (what changes at 1,000+ devices) and
does not repeat its rows.

## Open decisions

1. **Embedding model for pgvector** (phase 5). Recommended: a small local model (for example
   fastembed, ONNX, from PyPI): network data stays inside the company, no cost per call, works
   offline. Alternative: the company Azure OpenAI (`text-embedding-3-small`), better quality but
   every case text leaves for Azure, and it gives 403 from the UST network today.
2. **Where the device list comes from:** NetBox, a CMDB, IPAM, or the topology tool UST already
   bought (production-readiness: "a recently bought tool already stores devices and links as a
   graph"). If that tool has an API, importing from it may replace much of our own discovery.
3. **Accuracy targets for the map**, agreed with Praveen before the pilot (suggestion, not an
   industry standard: at least 99% of links AINOPS reports are real, at least 95% of real links
   found).

## The rule

**PostgreSQL is the system of record. Neo4j holds only the network graph, which can always be
rebuilt from the devices.** Neo4j is never the only copy of anything a person made. Every fact has
one owner, so the two stores cannot drift apart.

Why this split:
- **Neo4j Community Edition** (already chosen for production) is single-instance: no clustering, no
  online backup (only an offline dump), no role-based access ([Neo4j operations
  manual][neo4j-intro]). That is fine for a graph that discovery can rebuild in a few hours. It is
  a weak home for approved cases, reviews and the audit log, which nobody can recreate.
- **PostgreSQL** gives transactions, replication, point-in-time recovery, roles and mature
  backups, and every operations team knows how to run it. With **pgvector** it also does
  meaning-based search, so no separate vector database is needed.
- **Mature tools split the same way.** NetBrain runs a document store for system data (MongoDB), a
  search engine (Elasticsearch), a cache (Redis), a task queue (RabbitMQ) and "Front Servers" near
  the network as the only part that touches devices, each with its own high-availability setup
  ([NetBrain system specification][nb-spec]). AINOPS needs fewer pieces: Postgres covers the
  document store, search and the first queue.

## Where each kind of data goes

| Data | Today | Target store | Why | Backup |
|---|---|---|---|---|
| Topology: sites, devices, interfaces, subnets, `LINK`, `OSPF_PEER`, discovery snapshots | Neo4j (`topology/graph.py`) | **Neo4j** | Graph questions: neighbours, paths, impact | Rediscover; nightly offline `neo4j-admin database dump` for a fast restore |
| Cases and reviews | Neo4j `(:Case)-[:INVOLVES]->(:Device)` (`case_store.py`) | **Postgres** `cases` | Engineer work, cannot be rebuilt | Postgres |
| Investigations, events, conversations | Memory; `logs/investigations/<id>.json` written only when a turn ends; all loaded at start (`api/runs.py`) | **Postgres** `runs`, `run_events` | A crash mid-turn loses the turn today; start-up loads everything into memory | Postgres |
| Audit log | `logs/network-audit.jsonl` (`network/audit.py`) | **Postgres** `audit_log`, append-only | A record of every device command; must not be editable | Postgres, longer retention |
| Devices added on the Inventory page | `lab/inventory.local.yaml` (`inventory_edit.py`) | **Postgres** `inventory_local` (later: synced inventory) | Several API servers cannot share one file | Postgres |
| Skills and their versions | `skills/<name>/SKILL.md`, history in `skills/<name>/history/` (not in git) (`skill_book.py`) | **Postgres** `skills`, `skill_versions`, with git export/import | A skill steers every investigation: history must be complete and shared | Postgres + git export |
| Raw facts per device and configs ("what changed?") | Not kept | **Postgres** `device_facts`, `config_snapshots` | History and diffs; big text fits Postgres well | Postgres |
| Embeddings | None | **Postgres** (pgvector) | Meaning-based search next to the data it describes | Postgres (can be recomputed) |
| Users, roles, LLM usage | None | **Postgres** | SSO roles, cost per run | Postgres |

### What leaves Neo4j

`Case` nodes and `INVOLVES` relationships move to Postgres. The one graph question about cases,
"cases on devices near this one", becomes two steps: the neighbours come from Neo4j, then Postgres
finds the cases with `devices && $names` (array overlap, GIN index). `similar.py` does not use graph
queries today (it scores the approved cases in Python), so it works unchanged on Postgres.
`GraphStore.clear()` then no longer needs to spare cases.

## Postgres schema sketch

Names and columns are a starting point for phase 1, not final.

- **`runs`**: `id`, `kind` (investigation, discovery), `title`, `status` (running, done, stopped,
  failed, interrupted), `started_at`, `ended_at`, `outcome`, `confidence`, `tokens`.
- **`run_events`**: `run_id`, `seq`, `at`, `type`, `body jsonb`. One row per event, written when the
  event happens (append-only). `seq` is the SSE event id, so a viewer that reconnects gets what it
  missed even after an API restart. At start-up, a run still marked `running` becomes
  `interrupted` and the UI says so, instead of the turn silently disappearing. History pages
  through `runs`; nothing is loaded into memory at start.
- **`cases`**: `id`, `run_id` (unique), `status`, `made_by`, `root_cause`, `devices text[]` (GIN
  index), `interfaces text[]`, `created_at`, `updated_at`, `data jsonb` (the whole `cases.Case`).
  The review keeps today's "one review wins" rule: `UPDATE ... WHERE id = $id AND status = $only_if`
  in one statement, like `Neo4jCases.save(only_if=...)` does now.
- **`audit_log`**: `id`, `at`, `source`, `actor`, `device`, `tool`, `command`, `outcome`,
  `duration_ms`, `details jsonb`. The application's database role gets INSERT and SELECT only, no
  UPDATE or DELETE. Never device output or secrets, as today.
- **`inventory_local`**: the fields of `inventory.Device` plus `added_by`, `added_at`. The
  hand-written `lab/inventory.yaml` can stay as a seed until an inventory sync exists.
- **`skills`** and **`skill_versions`**: the full SKILL.md text, status (draft, live, off),
  reviewed by, saved by, saved at. The same rules as `skill_book.py` (read back with the loader's
  checks, one save wins, an edit goes back to draft). Export to and import from git, so skills
  stay reviewable as files.
- **`case_embeddings`**: `case_id`, `model`, `embedding vector(n)`, HNSW index (phase 5).
- **Later:** `users`, `roles`, `llm_usage` (tokens and cost per run and user), `device_facts`,
  `config_snapshots`.

## Topology at 1,000+ devices

### How discovery finds the connections today (no AI)

Discovery is plain code. The AI is not involved in building the map: the same network always
gives the same graph, every link can be explained, and it costs no tokens. The AI only reads the
graph, through the topology MCP server, during an investigation.

For each device in the inventory, 4 at a time, `collect` in `topology/discovery.py` asks the network
MCP server three things:

| Question | Cisco IOS | Junos | Becomes |
|---|---|---|---|
| Interfaces and addresses | `show ip interface` | `show interfaces terse` | `Interface` and `Subnet` nodes |
| Who is cabled to my ports (CDP or LLDP: devices announce themselves to the neighbour on each port) | `show cdp neighbors` | `show lldp neighbors` | `LINK`, port to port |
| Which routers I exchange routes with | `show ip ospf neighbor` | `show ospf neighbor` | `OSPF_PEER` (the neighbours a router normally has) |

`build_links` then makes a link from every CDP/LLDP neighbour that is in the inventory, and from
every pair of interfaces in the same subnet (this finds the lab firewalls, which do not speak CDP).
It reports what looks wrong: neighbours not in the inventory, the two ends of a cable in different
subnets, links that are down, addresses with no known peer. `replace_topology` then wipes and
rewrites the graph.

### How paths are found today

- **Cabling path:** `GraphStore.path()` asks Neo4j for the chain with the fewest links (up to 12).
  It shows which devices are connected, not where traffic goes.
- **Traffic path:** `trace_route` (`network/trace.py`) reads the live routing table of each device
  and follows the route the device itself uses. The graph only answers "which device owns this
  next-hop address?". The live tables have the final word.

This design scales: an investigation touches only the devices on the path, not all 1,000. NetBrain
works the same way in principle: its path analysis follows the routing tables, from the stored
baseline or live from the devices, and it allows manual "fix-up route tables" where data is
missing ([NetBrain A-B path][nb-abpath], [fix-up route table][nb-fixup]).

### What breaks at scale, and the direction

| Problem today | Why it matters | Direction |
|---|---|---|
| `replace_topology` wipes and rebuilds the graph in separate auto-committed statements | Readers see a half-built graph during a rebuild; a crash in the middle leaves it broken | Update one device at a time, each in one transaction; never wipe the whole graph |
| Full rebuild of every device, 4 at a time, by hand | Hours at 1,000 devices (estimate, not measured) | Collectors per region; incremental per site; a schedule (below) |
| The same-subnet rule applies to every subnet shorter than /31, /24 LANs included | On a LAN with 20 routers it invents a link between every pair | Use it only for point-to-point subnets; model a LAN as one shared segment |
| `shortestPath` counts hops | Ignores OSPF cost, VRFs, firewall policy | Weighted paths (OSPF cost on `LINK`); the traffic path stays `trace_route` |
| Every IP address assumed unique | Wrong with VRFs (the same address in several routing tables) | VRF-aware interfaces, subnets and `trace_route` |
| No history of facts | "What changed since yesterday?" cannot be answered | Raw facts and configs per device in Postgres, with `last_seen` |

Gaps by device type, for production:
- **Switches:** MAC address tables (which port each machine is behind), spanning tree, bundled ports
  (port-channels), VLAN trunks.
- **Routers:** BGP, VRFs, HSRP/VRRP (several routers sharing one virtual address, which also
  confuses the subnet rule).
- **Firewalls:** LLDP is often turned off, so links come from subnets or are entered by hand.
- **End hosts:** ARP tables (which address is behind which interface).
- **Load balancers, wireless controllers, SD-WAN, cloud, ISP links:** not covered; vendor APIs or
  an import from another tool.

The graph's size is not the risk: about 1,000 devices with 50 interfaces each is around 50,000
nodes, small for Neo4j. Collecting the data and keeping it right is the hard part.

### Keeping the map current when the infra team changes things

Today the graph changes only when someone runs discovery. Investigations still read the live
devices, and `trace_route` says when the graph disagrees with a device, but the map stays stale.

How mature tools do it:
- **NetBrain** runs a scheduled discovery to find devices (its documentation recommends weekly for
  most networks) and scheduled "benchmark" tasks to refresh device data (hourly to monthly). It
  advises running them off-hours and not letting them overlap: if one is still running when the
  next is due, the next is cancelled ([scheduling][nb-schedule], [frequency][nb-frequency],
  [discovery][nb-discovery]).
- **IP Fabric** takes periodic snapshots of the whole network (any schedule from minutes to
  yearly). A snapshot can take hours, and the next one waits until it finishes. Only a few
  snapshots are kept loaded ([snapshot collection][ipf-collect], [retention][ipf-retention]).

For AINOPS, four ways together:
1. **A nightly baseline per site**, staggered (not all devices at once), never overlapping a run
   that is still going.
2. **Refresh on events**, for the device and its neighbours, within minutes: syslog or SNMP traps
   (link down, OSPF neighbour change, configuration saved), an approved change ticket closing, a
   NetBox webhook.
3. **Refresh on demand:** when an investigation finds the graph disagrees with a device, refresh
   that device.
4. **A weekly sweep for new devices**, only while there is no inventory sync.

The graph is the map, never the evidence: the agent always checks the live devices. A slightly
stale graph slows an investigation down; on its own it does not make a wrong diagnosis. The UI
shows how old each fact is.

AI may help later in a reviewed way: suggesting a missing link ("FWL-TRV probably connects to
CORE-SW-TRV on ge-0/0/1") or explaining discovery findings, for an engineer to confirm. It never
writes the graph.

## Risks

| Risk | What it means | How we reduce it |
|---|---|---|
| Stale graph | Changes between refreshes are not on the map | Refresh on events and on demand; fact age in the UI; live checks remain the evidence |
| Non-atomic rebuild (today's code) | A crash leaves a broken graph; readers see a half-built one | Per-device transactions |
| Load on devices | Polling 1,000 devices uses CPU, login sessions (vty) and TACACS logs | Rate limits per collector, light polls, off-hours full runs, SNMP or streaming telemetry where available |
| Blind spots | CDP/LLDP off, transparent firewalls, load balancers, ISP/SD-WAN/cloud, devices missing from the inventory | Inventory sync, manual link entries, "unknown neighbour" findings |
| False links | The same-subnet rule on shared LANs | Point-to-point subnets only; LAN as a segment |
| Path accuracy | Equal-cost multipath, policy-based routing, VRFs, NAT, MPLS, asymmetric routing | Add them in stages; manual fix-ups like NetBrain; report "path uncertain" instead of guessing |
| Names and addresses | Names that do not match the inventory; the same address in several VRFs | VRF-aware graph; addresses from IPAM |
| Neo4j CE is one server | If it is down there is no map | The graph is rebuildable; restore from the nightly dump; the agent keeps working with the live tools |
| Many vendors | Output parsed wrong | Vendor packs with tests, reviewed by Praveen |
| Two stores drift apart | The same fact in Neo4j and Postgres disagrees | One owner per fact (the rule above); Neo4j holds only derived data |

## How we prove the map is right

No design can promise accuracy in advance. It is measured before production and kept measured
after.

1. **Synthetic scale test.** Extend the simulator (`backend/src/labsim/`) to generate a known
   1,000-device, multi-site network with the hard cases built in: VRFs, equal-cost paths, shared
   LANs, CDP turned off. The simulator knows the truth, so we score: links right, missing and
   invented; IP-to-device lookups; graph path vs `trace_route` vs truth; discovery time; query time.
2. **Change drills in the simulator.** Link down, new device, re-addressing, route change: how long
   until the graph shows each, with scheduled and with event refresh. A silent device must never
   make a link "disappear".
3. **Read-only pilot on one real site.** Compare the graph with the network team's diagrams,
   NetBox or UST's existing graph tool. Praveen reviews every difference.
4. **Self-check in production.** Every `trace_route` compares the live hops with the graph; the
   mismatch rate is a monitored number with an alert threshold.

## pgvector: search by meaning

An embedding model turns a text into a long list of numbers; texts with similar meaning get
similar lists. pgvector stores the lists in Postgres and finds the nearest ones fast, with an HNSW
index. It is a standard choice up to millions of vectors, usually combined with Postgres full-text
search ("hybrid search") ([pgvector in production][pgv-prod], [scaling pgvector][pgv-scale]).

Why AINOPS needs it: `similar.py` scores "similar wording" by counting shared words. "Chennai office
lost the link to Trivandrum" and "MAA users cannot reach TRV" share no words and score zero, though
they are the same problem.

Uses, in order:
1. **Better hints.** A "similar meaning" score replaces the word-overlap score (worth up to 4
   points today). It stays explainable ("similar meaning: 0.82"), and a hint still needs a shared
   device, subnet or kind of problem. Hints stay hints, never evidence.
2. **Search by meaning** on the Cases page.
3. **Picking the right skill** once there are dozens.
4. **Later:** retrieval over vendor documents, runbooks and past tickets (RAG).

Its value is small while there are few cases and grows with the case library, which is why it is
phase 5. The `model` column lets every case be embedded again safely when the model changes.

## Code approach

- **psycopg 3** with `psycopg_pool`, plain SQL (the repo uses plain Cypher with the Neo4j driver
  today, no ORM), and **Alembic** migrations written as raw SQL.
- New stores behind the existing interfaces: a `PostgresCases` class for the `CaseBook` protocol in
  `case_store.py`; a storage layer under `RunRegistry` (`api/runs.py`); `AuditLog`
  (`network/audit.py`) writing to Postgres. `similar.py` scoring is reused as it is.
- **Tests never touch a real database**, as today for Neo4j (`backend/tests/conftest.py` blocks the
  driver): a guard for Postgres connections, fakes in unit tests, and opt-in integration tests
  against a throwaway database.
- **Dev setup on this laptop:** there is no Docker. The `pgserver` package on PyPI bundles Postgres
  and pgvector in a Windows wheel for Python 3.12 ([pgserver][pgserver]). Not tried yet: whether
  Zscaler allows it, and which Postgres version it bundles.

## Production runtime (beyond storage)

Most of this is already in [production-readiness.md](production-readiness.md); here is how it fits
the storage design.
- **API and agent workers are separate processes.** Today the agent runs inside the API process. A
  queue starts as a Postgres table with `SELECT ... FOR UPDATE SKIP LOCKED`; a broker (RabbitMQ,
  like NetBrain) only if that is not enough.
- **Resumable runs:** a LangGraph Postgres checkpointer, so a stopped worker can carry on.
- **Collectors near the network**, like NetBrain's Front Servers: the only part that logs into
  devices.
- **Postgres:** a replica for failover, point-in-time recovery (pgBackRest or the platform's
  managed backups). **Neo4j:** nightly dump, restore tested.
- Structured logs and OpenTelemetry, LLM cost per run, SSO with roles, a vault for device logins.

## Phases after the demo

Each phase gets its own plan, approved before any code.
1. **Postgres foundation and cases:** settings, connection pool, migrations, health check, the
   test guard; cases moved, with a one-off command that copies the existing Neo4j cases.
2. **Runs and events:** append per event, `interrupted` runs, History paging.
3. **Audit log:** append-only table, retention.
4. **Inventory additions, skills and their versions**, with git export/import.
5. **pgvector** with the chosen embedding model, including a measured before/after on hint
   quality.
6. **Topology hardening:** per-device transactions, the subnet rule, the scale test and change
   drills above.
7. **Deployment:** containers, backups, workers, collectors.

## Sources

- [NetBrain system specification 10.1][nb-spec]
- [NetBrain: scheduling benchmark and discovery tasks][nb-schedule]
- [NetBrain R11: task frequency][nb-frequency]
- [NetBrain blog: network discovery][nb-discovery]
- [NetBrain: A-B path][nb-abpath]
- [NetBrain: fix-up route table][nb-fixup]
- [IP Fabric: snapshot collection][ipf-collect]
- [IP Fabric: snapshot retention][ipf-retention]
- [Neo4j operations manual: introduction][neo4j-intro]
- [pgvector in production][pgv-prod]
- [Scaling vector search in Postgres][pgv-scale]
- [pgserver on PyPI][pgserver]

[nb-spec]: https://www.netbraintech.com/docs/ie101/NetBrain_System_Specification.pdf
[nb-schedule]: https://www.netbraintech.com/docs/ie80/help/schedule-tasks.htm
[nb-frequency]: https://www.netbrain.com/docs/R11/help/HTML/frequency.html
[nb-discovery]: https://www.netbrain.com/blog/network-discovery-creates-brain-netbrain/
[nb-abpath]: https://www.netbrain.com/docs/ie101/help/a-b-path.htm
[nb-fixup]: https://www.netbrain.com/docs/12ac1ue0to/help/HTML/fix-up-route-table.html
[ipf-collect]: https://docs.ipfabric.io/7.5/IP_Fabric_Settings/Discovery_and_Snapshots/snapshot_collection/
[ipf-retention]: https://docs.ipfabric.io/7.3/IP_Fabric_Settings/Discovery_and_Snapshots/snapshot_retention/
[neo4j-intro]: https://neo4j.com/docs/operations-manual/current/introduction/
[pgv-prod]: https://bigdataboutique.com/blog/pgvector-in-production
[pgv-scale]: https://clickhouse.com/resources/engineering/scale-vector-search-postgres
[pgserver]: https://pypi.org/project/pgserver
