# Diagnosis audit, 2026-10-21

Why: two wrong answers in one day on the simulated lab. The fault-1 run blamed CORE-SW-TRV, and
the firewall run gave the security-zone fix the wrong way round. Instead of waiting for the next
one, we looked at everything the AI's answer depends on.

How it was checked (no AI calls unless said):
1. **What the tools tell the AI.** Every network tool run against a private simulator under each
   of the 6 faults, reading the summaries and warnings (`ainops.network.service`).
2. **What the AI is told.** The system prompt (`agent/prompts.py`) and the 3 draft skills.
3. **How the answer is judged.** `agent/report.py`, plus a replay of the 22 saved reports.
4. **Two live runs** on the simulator with gpt-oss-120b (Groq free tier): the firewall question
   and fault-1.

Already fixed on 2026-10-21 (uncommitted):
- confidence is low when nothing cited shows what is blamed;
- that case is sent back to the AI once, to check before answering;
- the firewall check names each port's cable;
- the prompt says to blame only what a check of that device shows, and to base direction fixes
  on the cabling.

## Findings

Severity: **high** = can give a wrong answer with nothing to warn the engineer; **medium** =
misleading or weakens the checks; **low** = noise.

### A. The AI cannot see the cause (blind spots)

| # | Sev | Finding | Evidence | Proposed fix |
|---|---|---|---|---|
| A1 | high | **A wrong address on one end of a cable** is invisible. Every interface shows "up"; nothing says the two ends are in different subnets. | faults `leased-line-wrong-ip`, `isp-maa-1-wrong-subnet`: get_interfaces "all addressed interfaces up" | get_interfaces compares each addressed port with the other end of its cable (graph): "Fa2/0 10.10.40.2/24 is not in the subnet of the other end IPLC-RTR-TRV Fa2/0 10.10.4.1/24" (problem) |
| A2 | high | **OSPF passive** cannot be read: the parser takes every word after "Passive Interface(s):" (gives `Routing, Information, Sources:, …, 192.168.100.1`), and the summary never mentions passive. | fault `leased-line-ospf-passive` | fix `parsers.routing_protocols`; summary "passive: Fa2/0"; problem when a passive port is one where an OSPF neighbour is expected |
| A3 | high | **A network missing from OSPF** is not flagged: an addressed, up interface whose subnet is in no `network` statement. | fault `maa-lan-not-announced` | get_routing_protocols reads the device's interfaces (as the firewall check does) and lists "up but not in OSPF: E1/0 192.168.200.1/24" |
| A4 | medium | **Cisco logs can never be read**: `show logging` needs enable, so every get_logs call on a router fails with "% Invalid input" (a wasted call; the skills ask for it). | all Cisco devices, every fault | **decision**: allow enable for this one read-only command (lab: no enable password; production: a read-only privilege level), or keep it off and make the tool say "not available: needs privileged mode" and take it out of the skills |
| A5 | medium | **Knowledge-graph answers look live.** find_device and get_device_links return port statuses from the last discovery ("up") without saying so in the summary or the field name. In the fault-1 re-run the AI looked up IPLC-RTR-MAA there instead of checking it live. | live run inv-aabe2eda, E13 | name the field `status_at_discovery` and end each summary with "(as of discovery <time>, not live)" |
| A6 | medium | **No guidance for firewall questions.** The prompt only describes reachability, and there is no firewall skill. The second firewall run never read the zones and answered "all up". | live run inv-b732a5dc | prompt line: for a firewall, get_firewall_zones then get_firewall_policies; draft skill `firewall-health` for Praveen |

### B. Misleading wording in the tool answers

| # | Sev | Finding | Proposed fix |
|---|---|---|---|
| B1 | medium | "no OSPF neighbours" is a **problem** on a device that does not run OSPF (the vSRX). The AI reported it as a fault. | a problem only when the graph expects neighbours there; otherwise info "OSPF has no neighbours here (none expected)" |
| B2 | medium | **A ping to a firewall fails even when the lab is healthy** (vSRX in no zone). "no replies" is a problem, so the AI may blame the cable. | when the target belongs to a firewall (graph): "10.10.7.2 is FWL-MAA's, a firewall: it may drop pings; a failed ping alone does not prove the path is down" |
| B3 | medium | Firewall policies: "2 policies; none deny traffic", while their zones have no interfaces. This suggests traffic passes. | "the zones of these policies have no interfaces: they apply to no traffic; traffic no policy permits is dropped" |
| B4 | low | "1 OSPF neighbour(s), all FULL; MISSING …" contradicts itself. | "1 OSPF neighbour FULL; MISSING …" |
| B5 | low | get_neighbors on the vSRX: "no neighbours seen" reads like "isolated" (LLDP is off). | "no CDP/LLDP neighbours seen (this does not mean the cables are down)" |
| B6 | low | get_routes refuses `192.168.200.0/24` (only plain addresses): one wasted call per run. | accept a prefix and use its network address |

### C. How the answer is judged

| # | Sev | Finding | Evidence | Proposed fix |
|---|---|---|---|---|
| C1 | high | **Outcome "answered" skips every check**: it is always "high, no network evidence needed", even after network checks. A firewall status question came back "answered / high" with the real problem missed. | inv-b732a5dc | "answered" only when no network check ran; otherwise it is judged like no_fault_found (or sent back to choose an outcome) |
| C2 | high | **Knowledge-graph lookups count as checks.** "Healthy" (no_fault_found, medium) can rest on discovery-time data, and a graph record can "show" a blamed port. | inv-e1a5d6ed: "leased line healthy" with one router checked live | only live checks count for confidence and for showing what is blamed |
| C3 | medium | **"diagnosed" that blames nothing** is not checked, and it opens a case. | inv-8681fb00: diagnosed, root cause "the line is healthy" | diagnosed with empty `affected` → low, sent back once to name what is at fault or change the outcome |
| C4 | medium | **One shown item is enough**, so a long list of blamed items, most of them unshown, stays high. | inv-d49e1fb5: 6 items, 1 shown, high | at most medium while any blamed item is unshown, listing them |
| C6 | high | **An answer with `null` for a list crashes the run.** gpt-oss sent `"affected": null`; Groq checks the answer against the Report schema and rejects it (400 "expected array, but got null"), so the engineer gets an error instead of the refusal. Found by the evaluation set's first run. | eval 2026-10-21 11:13, change-request-refused | let the list fields accept null and read it as empty |
| C5 | medium | **Findings are not checked**: a finding can name one device and cite another device's check (fault-1: "Fa2/0 on CORE-SW-TRV (10.10.4.1)" cited IPLC-RTR-TRV's check). | inv-7fd965ec | flag a finding whose named device none of its cited checks is about (heuristic: needs care) |

### D. Skills (drafts: Praveen reviews)

| # | Sev | Finding | Proposed fix |
|---|---|---|---|
| D1 | medium | site-to-site-unreachable has no step for "both ends up but the neighbour is missing" (wrong address, passive, area). In the re-run the AI never ran get_interfaces on IPLC-RTR-MAA. | after step 4: compare the two ends' addresses, then get_routing_protocols on both (or open ospf-neighbour-down) |
| D2 | low | ospf-neighbour-down step 6 asks for get_logs, which always fails on Cisco (A4). | follows the A4 decision |

### E. Process and environment

| # | Sev | Finding | Proposed fix |
|---|---|---|---|
| E1 | high | **Wrong answers are only found by chance**: someone runs a question and reads the answer. | **built 2026-10-21**: `backend/src/evals` (10 cases, scored by code; backend/README.md "Evaluation set"). Not run in full yet: needs E2. |
| E2 | high | **The free Groq tier cannot finish a fault-1 investigation**: "413 Request too large … Limit 8000, Requested 8069" at check 15 (also on 10-07); slow (30-60 s between steps) on shorter ones. It also stops at **200,000 tokens a day** (429, reached on 2026-10-21 after a few runs), while one pass of the evaluation set needs about 0.5-0.9 million. The model's mistakes also differ run to run. | Groq Dev tier, or Azure gpt-5.1 (needs the UST network allowed by its firewall). Not a code fix. |
| E3 | medium | A discovery run during a fault writes the wrong addresses into the graph (OSPF neighbours are protected, addresses are not), so A1's comparison would then see nothing. | discovery reports "address changed on a cabled port" as a finding, and the UI asks before replacing the graph |
| E4 | low | Cases made on the simulator go into the same Neo4j. Two are pending with wrong root causes (case-7fd965ec, the firewall case). | correct them in Cases; keep simulator cases apart later |

## Suggested order

1. **E1 evaluation set first**, so every later fix is measured, not guessed. It needs a model that
   can finish a run (E2).
2. **Tool blind spots and wording**: A1-A3, A5, A6 (prompt line), B1-B6.
3. **Judging**: C1-C4 (C5 later; it is a text heuristic).
4. **Skills** D1-D2 with Praveen; the A4 decision with Praveen.
