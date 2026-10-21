# AINOPS handoff — continue on branch `demo/agentic` (written 2026-10-08)

You are continuing work with Deependra (the user) on AINOPS, an agentic network-troubleshooting
platform. Read this whole note before doing anything. Then confirm the state with
`git log --oneline -10`, `git status` and `git stash list`, and wait for the user's direction.

## Update 2026-10-20: new machine, no EVE-NG lab, simulated lab
- Work moved to a corporate laptop (repo `C:\c\dev\ainops-platform`); the lab laptop with EVE-NG
  is away for repair. Setup steps (Zscaler proxy workarounds) in `backend/README.md`, "Set up a
  new machine". gitleaks is not installed yet (GitHub downloads blocked): commits wait for it.
- **Simulated lab** `backend/src/labsim` (see `backend/README.md`, "Simulated lab"): telnet
  consoles on the EVE ports, worked out from a model of the lab and named faults.
  `scripts\start-all.ps1 -Sim` runs AINOPS on it; the UI says "Lab · simulated devices".
  Checked against every live recording; Junos beyond routes/interfaces/zones is unverified.
- Found with it: `parsers.routing_protocols` reads every word after "Passive Interface(s):" as an
  interface name (never seen on the lab: it has no passive interfaces). Not fixed yet.
- Open: cases made while on the simulator go into the same Neo4j as real ones.
- 2026-10-21: AI calls work from this laptop with the user variable `SSL_CERT_FILE` (step 3 of
  "Set up a new machine"). Azure answers 403 (its firewall does not allow the UST network), so
  only the Groq key works here, and it is the free tier (8,000 tokens/min).
- 2026-10-21, first run on the simulator (fault-1, checklist step 1, gpt-oss-120b, "Try this
  skill" site-to-site-unreachable): 15 checks (9 beyond the skill), 8 min 55 s (the free tier's
  token limit spaces the AI calls 30-60 s apart), 85,887 input + 3,083 output tokens. It found
  "MISSING IPLC-RTR-MAA on Fa2/0" on both IPLC routers but blamed CORE-SW-TRV (said it lacks
  OSPF for 10.10.4.0/24: it mixed up IPLC-RTR-TRV's Fa2/0 with CORE-SW-TRV's), with "high"
  confidence; it never checked IPLC-RTR-MAA's interfaces. Case `case-7fd965ec` is pending with
  that wrong root cause: reject or correct it, never approve it.
- 2026-10-21, confidence rule (uncommitted, `agent/report.py`): a diagnosis is "low" when no
  cited root-cause check of the blamed device names the blamed interface ("nothing cited for
  the root cause shows X: check it directly"). Replayed on the 22 saved reports: only the run
  above (high -> low) and inv-e0df4b94 (cited only "2 links", medium -> low) change. Open: one
  shown item is enough, so a long list of blamed items (inv-d49e1fb5) stays high; a diagnosis
  with an empty `affected` is not checked.
- 2026-10-21, also uncommitted: a root cause nothing cited shows is sent back once to be checked
  (runner.py, "recheck" step in the UI); get_firewall_zones names each port's cable (graph);
  prompt rules on blaming and on direction fixes. Then an audit of everything a diagnosis
  depends on: **`docs/diagnosis-audit.md`** (findings A1-E4, suggested order). Live re-runs:
  the firewall question came back "answered / high" without reading the zones (finding C1);
  fault-1 died on the free tier (413, 8,069 > 8,000 tokens/min at check 15).
- 2026-10-21, also uncommitted: **evaluation set** `backend/src/evals` (`uv run python -m evals`,
  backend/README.md "Evaluation set"): 10 cases in `cases.yaml`, scored by code, refuses the live
  lab, restores faults. Only the plumbing was run: its first case found finding C6 (null list ->
  Groq 400), then the free tier's daily cap (200,000 tokens) stopped it. A full pass needs the
  Groq Dev tier or Azure.

## Working agreement (the user's rules: follow them exactly)
- For every task, propose a short plan and WAIT for "yes" before writing code. If the plan has to
  change while building (e.g. for safety), say so plainly in the result.
- Ship tests with every change. For safety code, run mutation checks: break each protection,
  confirm that a test fails, then restore. Add a test for every mutation that is missed.
- End every task with an honest **verified / not verified** list.
- The user is a junior developer and new to networking. Explain in plain language, and translate
  network terms.
- Secrets live only in the repo-root `.env`. Never print them, and tell the user never to paste
  them in chat. Read them without printing them.
- Commit only when the user says so (local commits; they push or merge themselves). Push
  `demo/agentic` only when the user OKs it. An approved plan that names separate commits counts.
- Do NOT keep servers running yourself with `run_in_background`: they get killed. The user runs
  `scripts\start-all.ps1`, which opens one window per piece.
- Never change lab devices yourself. AINOPS is read-only. The user types device commands. Your
  scripts only run read-only show/ping commands.
- Lab-only shortcuts are fine for the POC, but record each one in
  `docs/production-readiness.md` (the user's request, 10-08).
- Tests never touch the real Neo4j: `backend/tests/conftest.py` blocks `neo4j.GraphDatabase.driver`
  for every test (a test once wrote a made-up case into the real graph). Use fakes.

## People
- **Praveen:** network SME. Built the EVE-NG lab and an earlier POC. Not a developer. Gave feedback
  on 10-06 (memory `praveen-meeting-2026-10-06`). Worries about scale.
- **Siddharth:** director/architect. Wants advanced visuals that show what the AI is doing, and why.
- **Sudhir:** architect.
- **Sreekutty:** PM.
- **Shinu:** may help with company LLM access.

## Architecture (POC)
- **Backend:** Python 3.12, uv, package `ainops` in `backend/`.
  - **Network MCP** (:8101): 13 read-only tools. Commands come only from `network/commands.yaml`,
    with guard/redact/audit. Netmiko over the EVE-NG consoles. Always live (no replay mode).
    Reads the inventory again when an inventory file changes.
  - **Topology MCP** (:8102): answers from the Neo4j knowledge graph.
  - **API** (:8000): FastAPI + SSE. The agent runs inside the API process.
  - **Agent:** LangChain `create_agent` + `AinopsMiddleware`: tool budget 16 per reply; no invented
    IPs; evidence ids E#; a required `reason` per tool call, optional `skill_step`; confidence by
    code; tokens counted per reply.
- **Frontend:** Vite + React 19 + TS + Tailwind v4 + shadcn, in `frontend/` (:5173). Menu:
  - *Troubleshoot:* Investigate (conversation, live Now line, map, timeline, report, review box),
    Inventory, Cases (count of cases waiting), History.
  - *Behind the scenes:* Network map (was "Knowledge graph"), Skills, AI tools (was "MCP tools"),
    Audit log.
- **Neo4j** (:7687), bolt. Holds the network graph and the cases.

### Built and committed (all local, not pushed)
- **18faf76 and earlier:** trace_route, skills, discovery keeps silent devices (`stale_since`),
  expected OSPF neighbours (`OSPF_PEER`), Now line, live map, device panel.
- **ff4f3a4 live-only:** no replay mode; `LiveExecutor` always; recorded outputs are test data
  only (`backend/tests/replay.py`); `uv run python -m ainops capture <name>` for new test data.
- **2160385 conversation:** an investigation is a conversation of up to 8 messages; the engineer
  replies under the report ("ask why, correct it, tell it where to look") and can press Stop.
  `agent/conversation.py` rebuilds the turns from the saved events (works after a restart); the
  LLM gets a recap of earlier replies (report + checks with one-line summaries, not raw output).
  Evidence ids continue across turns; a root cause on checks older than 15 min gets one level
  lower confidence. SSE events are numbered (`?after=` / Last-Event-ID).
- **c944a8a menu:** the two groups above.
- **7a46eab cases (knowledge base phase A):** after a reply that finds a root cause, code (no LLM)
  drafts the conversation's case (`cases.py`); the engineer approves / corrects / rejects it under
  the report or on the Cases page. The AI's draft is never changed by a review. Stored in Neo4j as
  `(:Case)-[:INVOLVES {interfaces}]->(:Device)` (`case_store.py`, one review wins). "Make a case"
  for inconclusive/healthy replies.
- **640c284 hints (phase B):** before every reply, code scores the APPROVED cases (`similar.py`:
  shared device 3, subnet 2, kind of problem 2, site 1, wording up to 4; a device/subnet/problem
  link is required; max 3; never the conversation's own case or one already offered) and shows
  them as a dashed "similar past cases" step and in the prompt. Hints are never evidence: no E#,
  citing one is removed, their IPs are not usable. Tokens per reply on the report card and case.
- **b800490 docs/production-readiness.md:** what must change for 1,000+ devices (targeted route
  lookups, collectors/SSH/vault/TACACS, inventory sync, incremental discovery, VRFs, vendor packs,
  map, database, queue, SSO/roles). Keep it up to date.
- **fb5e761 + 1ea0c8b Inventory page:** status from the last discovery (reached / not reached
  since / not discovered yet), filters, device panel with "Check now" (`get_device_facts`).
  Add/remove devices: `lab/inventory.local.yaml` (gitignored, written atomically); never a
  password (a `.env` login profile is picked by name); only page-added devices can be removed;
  every change is audited. No "test before saving": that would need a tool that connects to any
  address, which the AI could call.
- **b057c43 ping:** losing only the first ping (".!!!!") is ok, with "first lost: normal (ARP)"
  in the summary. The parser keeps the reply marks (`replies`) only when they agree with the counts.
- **dc26fb1 firewall zones:** `get_firewall_zones` also reads the interfaces and flags traffic
  ports (ge-/xe-/et-/ae/reth/irb/vlan/st0) with an address but no unit in any zone (problem: "the
  firewall drops its traffic"). Both lab vSRX will show red; that is a true finding. Test input
  `fixtures/firewall/no-zones`: interfaces are live (10-07), the zones file is HAND-WRITTEN.
- **1b853e4 / 955ec64 / cdc38e4 Skills page:** list + opened skill at `/skills/<name>` (search,
  filters, "Used in investigations" from the saved runs); New skill / Edit form with live preview
  and tool picker (`skill_book.py`: form → SKILL.md → read back with the loader's rules; tool names
  must be checkable; one-save-wins `version`; replaced file kept in `skills/<name>/history/`,
  gitignored; History panel with Restore); status **draft / live / off** in the SKILL.md metadata:
  ONLY LIVE skills are offered to the agent (`SkillLibrary.for_agent`); a draft can be tried with
  "Try this skill" (`/?try=<name>` → `try_skill`, kept for the conversation's follow-ups); only a
  reviewed skill can go live; any edit/restore → draft + not reviewed. All changes audited
  (source "skills"). Unquoted YAML `status: off` (read as false) counts as off.
  **The 3 lab skills are drafts: AINOPS uses no skill until they are made live** (checklist step 0).

### Samples (backend output the frontend tests read; rewrite with `AINOPS_WRITE_SAMPLES=1 pytest -k samples`)
`fixtures/routes/samples`, `fixtures/cases/samples` (incl. `hints-event.json`),
`fixtures/inventory/samples`. Recorded live runs: `fixtures/runs`.

### Decisions made by the user
- **No replay mode:** "answering from saved outputs is fake diagnosis".
- **"Shorten older results for the model" was removed:** revisit only with a measured comparison.
  (The conversation recap of EARLIER replies is a different thing, told to the user; measure it once
  the Groq key works.)
- **No full Admin section** (login/roles/approval) in the POC; production work.
- **Conversation before cases** ("AINOPS should hold a conversation like I have with you").
- **Cases:** one per conversation; auto-draft only after "diagnosed"; reviewer types their name.
- **Hints:** looked up by code at the start of each reply (not an AI tool); max 3; tokens shown on
  the report card.
- **Scale:** lab-sized shortcuts are fine for the POC; note them in the production doc.
- **Inventory:** status from discovery + Check now (no polling); unreached devices may be saved;
  add and remove only (no edit yet).
- **Skills (10-08):** editable on the page (add + edit, no delete); draft / live / off with
  "Try this skill"; only reviewed skills go live; an edit sends a skill back to draft. Industry
  check: NetBrain/Kentik/Azure SRE Agent author runbooks in the UI; we keep SKILL.md files.

## How to run (Windows; Git Bash for tools, PowerShell for the user)
- User: `cd C:\c\dev\ainops-platform` then
  `powershell -ExecutionPolicy Bypass -File .\scripts\start-all.ps1`.
  Pieces can be restarted individually:
  - `cd backend; uv run python -m ainops mcp-network`
  - `cd backend; uv run python -m ainops api`
- **The user still has to:** delete the `LAB_EXECUTOR` line from `.env` (harmless if left), and
  restart the network MCP and API windows to run the new code.
- Tests, always as Python modules (Smart App Control blocks the .exe):
  - `cd backend && uv run python -m pytest -q` (413 tests on 10-08)
  - `uv run python -m mypy src tests` (SAC blocked mypy's compiled DLL on 10-08; it was reinstalled
    as pure Python with `uv pip install --reinstall --no-binary mypy "mypy==2.3.1"`)
  - `uv run python -m ruff check .`
  - `cd frontend && npx vitest run && npx tsc -b && npx eslint src` (140 tests on 10-08)
- Discovery: `cd backend && uv run python -m ainops discover` (needs both MCP servers + Neo4j).
- Real investigation via the API: POST `/api/investigations {"question": ...}`, then poll
  `/api/runs/<id>`; follow-up: POST `/api/runs/<id>/messages {"text": ...}`.
  Page: `http://localhost:5173/investigations/<id>`.
- **Edits:** write multi-line edit scripts to a file in the scratchpad with the Write tool and run
  them (Bash heredocs with quotes sometimes fail to parse). Write files with `newline="\n"`.
- **UI checks without touching the user's servers:** start a temporary API on :8010 (with
  `LOGS_DIR` pointing to a scratch folder; for cases, a small launcher that swaps `app.cases` for
  an in-memory book) and `vite preview` on :4180 (with `AINOPS_API_URL`), take headless Chrome
  screenshots (`MSYS_NO_PATHCONV=1`, `--virtual-time-budget=8000`; headless Chrome never lays out
  narrower than 512 px), then stop both with `taskkill //F //T` on the port's PID. Run each Chrome
  command directly (a shell function wrapping Chrome produced no files).

## The lab (EVE-NG, laptop on the phone hotspot: EVE at 172.20.10.3)
| AINOPS name (alias) | EVE label | Console port | Platform |
|---|---|---|---|
| ISP-TRV-1 | ISP-Router (TRV) | 32770 | Cisco c7200 IOS 15.2 |
| FWL-TRV | vSRX-NG (TRV) | 32771 | Juniper vSRX |
| CORE-SW-TRV | core-sw (TRV) | 32769 | Cisco |
| IPLC-RTR-TRV (TRV-P2P) | P2P-Router (left) | 32775 | Cisco |
| IPLC-RTR-MAA (MAA-P2P) | P2P-Router (right) | 32776 | Cisco |
| CORE-SW-MAA | core-sw (MAA) | 32774 | Cisco |
| FWL-MAA | vSRX-NG (MAA) | 32773 | Juniper vSRX |
| ISP-MAA-1 | ISP-Router (MAA) | 32772 | Cisco |
| TRV PC / MAA PC | Tiny Core Linux | 32777 / 32778 (VNC) | 192.168.100.10 / 192.168.200.10 |

- **Path:** TRV LAN 192.168.100.0/24 – CORE-SW-TRV – IPLC-RTR-TRV – leased line 10.10.4.0/24 (OSPF)
  – IPLC-RTR-MAA – CORE-SW-MAA – MAA LAN 192.168.200.0/24. No working internet backup path
  (ISP-TRV-1 Fa0/0 shut; both vSRX have NO interfaces in any security zone; no backup routes).
- **FAULT 1 was applied on 10-07** (IPLC-RTR-MAA Fa2/0 shut) and kept for the next AI run. Restore
  on that console: `enable` / `configure terminal` / `interface FastEthernet2/0` / `no shutdown` /
  `end`. The user types it: close the "AINOPS - network MCP" window first, restart it afterwards.
- **On 10-08 12:16 UTC the lab did not answer** (IPLC-RTR-TRV console: TimeoutError). Probably the
  lab or the hotspot was down. Check before assuming anything about the fault state.
- **The knowledge graph** was rebuilt on the healthy lab at 09:50 UTC on 10-07 (all 8 reached, 7
  links, 6 expected OSPF neighbours). Don't run discovery while the fault is applied unless meant.
- **PCs lose their IP on every restart:** `sudo ifconfig eth0 192.168.100.10 netmask
  255.255.255.0 up` + `sudo route add default gw 192.168.100.1` (MAA: .200.x).
- **The EVE drawing sometimes shows links missing that actually work.** Check the devices.
- **Cisco ping "4/5, first lost" is normal (ARP),** but the health check marks it as a problem.

## Live results so far
- `inv-6d798971` (10-07), leased line healthy: right skill, 8 checks, correct answer.
- `inv-0f7c7f5b` (10-07), fault 1: right skill and trace_route, missed the missing OSPF neighbour
  (before 18faf76), then Groq 413.
- `inv-94755ad9` (10-07), fault 1 after the OSPF fix: saw "MISSING IPLC-RTR-MAA on Fa2/0", stopped
  on Groq's DAILY limit one check before the root cause.
- Nothing since 10-07 has been tried with a real LLM: conversation, cases, hints, tokens and the
  Inventory "Check now" success path all wait for the Groq Developer key.

## Next steps (plan first, wait for "yes" each time)
1. **When the Groq Developer key arrives:** work through `LIVE-TEST-CHECKLIST.md` (repo root,
   untracked, temporary). It covers the fault-1 diagnosis, the conversation tests, cases, the
   before/after hint measurement and the Inventory page. Then demo to Praveen.
2. **Market check (10-08):** the user asked whether the direction is right. Answer: yes. Cisco
   Deep Network Troubleshooting, NetBrain 12.3, Forward AI, Kentik AI Advisor and Datadog Bits AI
   SRE all use the same design (read-only tools, network model, runbooks, evidence + confidence,
   human approval). Gaps proposed, in this order (none agreed yet beyond the health fixes, DONE):
   a. **Scorecard moved up:** 5-10 lab fault drills with known answers, scored like the NIKA
      benchmark (detected / right device / right cause), per model (ours: gpt-oss-120b, untested).
   b. **"What changed?":** save configs at discovery + a read-only diff tool (Kentik does this).
   c. **Hypotheses panel** (Cisco and Datadog test hypotheses explicitly; Siddharth's "why").
   d. **Freshness of map facts** shown in the UI (IP Fabric warns about this).
   Research note: FaulT-Bench (2026) found agents turn harmless conditions into root causes on a
   healthy network when the ticket is wrong: add "nothing is wrong" tests to the scorecard.
3. **Record a past incident** (offered, not agreed): an engineer types a real past incident as an
   approved case, to give AINOPS knowledge on day one. Also lab fault drills to seed cases.
4. **Skill suggestions from repeating cases** (3+ similar approved cases → "add a skill" with a
   draft built from the checks that found the cause).
5. **Code fast path before the AI** for common symptoms (saves tokens).
6. **"Normal state" for interfaces/routes,** extending the OSPF idea.
7. **Scorecard:** approved cases re-run as AI tests over time (see 2a).
8. **Other ideas offered** (not agreed): cheaper model for simple steps, cost per run on screen,
   short cache, path watching, change timeline (needs Cisco enable for logs), impact analysis,
   fix with rollback, ticket integration, synthetic 1,000-device scale test.

## Smaller backlog
- The Now line still says "choosing the first check" when a follow-up starts.
- On narrow screens the conversation scrolls inside a short box (it did before the conversation).
- The Add device form and the Remove confirmation have no screenshots yet (tests only).
- `GraphStore.clear()` now spares cases but is untested (unused).
- Crash-prevention layers (error boundaries, zod validation of events, fuzz tests).
- get_logs needs Cisco enable mode (a decision).
- 5 git stashes of old live recordings (`stash@{0..4}`): can be dropped once the user agrees.
  Fault-1 data worth keeping is already in `fixtures/routes`, `fixtures/ospf` and `fixtures/runs`.
- Scale items are listed in `docs/production-readiness.md`, not here.

## Memory
`C:\Users\291223\.claude\projects\C--c-dev-ainops-platform\memory\` has `agentic-redesign.md`
(running state), `praveen-meeting-2026-10-06.md`, `windows-dev-quirks.md` and others. Keep them
updated.
