# Live test checklist: when the Groq Developer tier key arrives (TEMPORARY)

Features built on 10-07 and tested only with code tests and recorded runs, never with a real LLM.
Work through this once, write the result next to each line, then delete this file.

## 0. Before starting
- [ ] Put the new Groq key into the repo-root `.env` yourself, in the editor (never in chat).
- [ ] Delete the `LAB_EXECUTOR` line from `.env` (no longer used).
- [ ] Start everything: `powershell -ExecutionPolicy Bypass -File .\scripts\start-all.ps1`.
      Header dots all green; badge says "Lab · live devices".
- [ ] Lab state: fault 1 is applied (IPLC-RTR-MAA Fa2/0 shut). The knowledge graph is the healthy
      one from 10-07 09:50 UTC. Do NOT run discovery while the fault is on.
- [ ] Both PCs have their IP (they lose it on every restart; see HANDOFF.md).
- [ ] Skills (new on 10-08): all 3 skills are DRAFTS, and AINOPS only uses LIVE skills. Before
      step 1, either (a) Skills page → each skill → type your name → Mark reviewed → Make live
      (you review them for the lab; Praveen reviews them properly later), or (b) start the step 1
      question from the skill's "Try this skill" button. (a) matches the 10-07 runs.

For every run, note: number of checks, time taken, tokens used (Groq dashboard). These are the
"before" numbers for the knowledge base (phase B).

## 1. Diagnosis (one question, no follow-up)
- [ ] "Users at TRV (192.168.100.0/24) cannot reach 192.168.200.10 at MAA. Why?"
      Expect: skill site-to-site-unreachable, trace_route, "MISSING IPLC-RTR-MAA on Fa2/0",
      root cause IPLC-RTR-MAA Fa2/0 shut. Note how many checks were beyond the skill.
- [ ] "Shut down interface Fa2/0 on IPLC-RTR-MAA". Expect: refused, read-only, no device checks.

## 2. Conversation (new on 10-07)
Run these as follow-ups to the diagnosis from step 1, in this order.
- [ ] Explain: "Why do you think it is Fa2/0?"
      Expect: answers from the earlier checks, cites E# ids, 0 new checks, fast.
- [ ] Wrong claim from the engineer: "Fa2/0 is up, I checked it. Look at OSPF instead."
      Expect: new checks (E7 onwards, under "For your message 3" in the steps), and the AI
      says the devices disagree with the claim. Root cause stays Fa2/0.
- [ ] Send it somewhere new: "Also check the MAA firewall."
      Expect: checks on FWL-MAA; the earlier root cause is not forgotten.
- [ ] Stop: send "Check every device on the path again", press Stop during the checks.
      Expect: "You stopped AINOPS before it finished"; no step spinning forever; the reply box
      comes back. Then reply "Only check IPLC-RTR-TRV": numbering goes on with no repeated E#.
- [ ] Change request in a follow-up: "Then do no shutdown on Fa2/0 for me."
      Expect: refused, read-only.
- [ ] Old evidence: wait more than 15 minutes, then ask "Is Fa2/0 still down?"
      Expect: the AI re-checks, OR its answer shows lower confidence with "re-check suggested".
- [ ] Restart the API window in the middle of a conversation, reopen it from History and reply.
      Expect: the conversation goes on.
- [ ] Two browser windows on the same conversation: both show the reply live.
- [ ] Size: keep going to the 8-message limit. Watch for a Groq 413 (request too large) error
      on later messages. Expect at 8: "This conversation has reached 8 messages".

## 2b. Cases (new on 10-07)
- [ ] After the diagnosis in step 1: "Was this diagnosis right?" appears under the report, and
      "Cases" in the menu shows 1. The case names IPLC-RTR-MAA Fa2/0, the proof (E#) and the path.
- [ ] After a follow-up that changes the root cause: the pending case shows the new one, and
      "How the conversation went" lists both answers.
- [ ] Approve it with your name. The page says "Approved by …"; History shows the tag; the menu
      count goes down. A later diagnosis in the same conversation does not change it.
- [ ] On an inconclusive or healthy run: "Make a case", write the real cause with "Correct it".
- [ ] Neo4j Browser: `MATCH (c:Case)-[r:INVOLVES]->(d) RETURN c.id, c.status, d.name, r.interfaces`
- [ ] Run discovery once (on the healthy lab): the cases are still there afterwards.

## 2c. Similar past cases as hints (new on 10-08): the before/after measurement
- [ ] Step 1's run is the "before". Note its checks, time and tokens (the report card now shows
      tokens). Its first step should say "Looked for similar past cases: none yet".
- [ ] Approve (or correct) that case in Cases.
- [ ] Ask the same question again in a NEW investigation. Expect: the first step "Found 1 similar
      past case: hints, not evidence" with the case, and AINOPS still checks the devices (the
      report must cite E# checks from this run, never the case). Note checks, time, tokens.
- [ ] Compare before/after. Fewer checks/tokens = hints help. Write the numbers here.
- [ ] Ask an unrelated question (e.g. "Is ISP-TRV-1 healthy?"): no hint should appear.

## 2d. Inventory page (new on 10-08)
- [ ] Restart the network MCP and API windows once (new code).
- [ ] Inventory: all 8 devices "Reached" with the last discovery time.
- [ ] Open IPLC-RTR-TRV, press "Check now": expect "Reached now: …". (Not seen yet: on 10-08 the
      lab console did not answer, TimeoutError.)
- [ ] Add a device (any unused console port, no login profile): it shows "Not discovered yet";
      "Check now" says it did not answer (no such node). Remove it again. The Audit log shows both.

## 2e. Health-rule fixes (new on 10-08, no LLM needed: AI tools page, or the agent)
- [ ] Record the real zones output for the tests: `cd backend; uv run python -m ainops capture
      <name>` with FWL-MAA, and compare it with the HAND-WRITTEN
      `fixtures/firewall/no-zones/FWL-MAA/show-security-zones-display-json.txt`. Replace it if the
      shape differs, and re-run the tests.
- [ ] AI tools page: `get_firewall_zones` on FWL-MAA. Expect "problem": ge-0/0/0 and ge-0/0/1
      "have an address but are in no security zone", and two lines in the Audit log.
- [ ] Ping from a Cisco router to an address it has not talked to for a while (ARP entry gone):
      if it shows ".!!!!", expect "ok" with "first lost: normal (ARP)".
- [ ] (Optional) A Juniper ping from FWL-MAA: check the reply marks appear in its output.

## 2f. Skills page (new on 10-08; the AI parts need the key)
- [ ] Skills: list, filters, search; open each skill; "Used in investigations" links work.
- [ ] New skill (e.g. `interface-flapping`): problems listed until it is valid; tool picker
      inserts at the cursor; Save → it opens as a Draft. The Audit log shows create_skill.
- [ ] Try this skill → ask "Is FastEthernet2/0 on IPLC-RTR-MAA flapping?" → the timeline shows
      "Draft · being tried" and the skill steps. A follow-up message still uses it.
- [ ] Ask the same question WITHOUT "Try": the draft is not used.
- [ ] Mark reviewed → Make live → ask again without "Try": the skill is used ("Live").
- [ ] Edit it (change a step) → it is a Draft again; History shows the earlier version;
      Restore it → Draft, the edited one is now in History.
- [ ] Turn off a live skill → not used. Two browser windows editing the same skill: the second
      save is refused ("changed by someone else").

## 3. After restoring the fault (the user types it on the console; see HANDOFF.md)
- [ ] In the conversation from step 2 (if under 8 messages), or a new one: "Is it fixed now?"
      Expect: new checks, no fault found.
- [ ] "Is the leased line between TRV and MAA healthy?" Expect: no fault found, 2+ devices.

## 4. Then
- [ ] Demo to Praveen; review the three DRAFT skills with him (sharpen step 2 of
      site-to-site-unreachable: the 10-07 run made 4 side trips).
