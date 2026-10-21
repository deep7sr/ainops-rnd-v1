# Agent self-correction (backtracking): parked, come back to it

Written 2026-10-21. The user asked: "if our agent took a wrong path or decision, is it intelligent
to see this and correct its trajectory by backtracking?" Decision: stay on the UI work for now and
come back to this.

## What it does today

- **Re-plans after every result.** The agent is a think -> act -> observe loop with every earlier
  result in its context, so a result that contradicts its expectation can change its direction.
  This is the model's own judgment: nothing makes sure it happens.
- **One code check sends it back.** If the root cause blames something none of the cited checks
  shows, code sends it back once to check that device (`RECHECK` in `agent/prompts.py`,
  `not_shown` in `agent/report.py`, the "recheck" step in the UI).
- **Code sets the confidence**, not the AI (`agent/report.py`).
- **The engineer can steer it:** Stop, then a follow-up message.

## Where it fell short

2026-10-21, simulator, fault-1: the OSPF check said "MISSING neighbour IPLC-RTR-MAA", the agent
never checked IPLC-RTR-MAA, blamed CORE-SW-TRV, and said "high". The recheck rule (added after)
lowers the confidence and sends it back only because the blamed item was not shown. A wrong root
cause that some real problem elsewhere does show would still pass. A language model does not
reliably notice its own mistakes; code that spots a specific gap and sends it back with a precise
instruction does.

## Proposed (not started)

1. **Open leads must be followed.** When a check points at a device ("MISSING neighbour X", a
   route that stops at Y) that was never checked live, code sends the agent back before it may
   answer: "E7 points at IPLC-RTR-MAA but you never checked it." This alone would have caught the
   10-21 run.
2. **Hypotheses with a status.** The agent keeps an explicit list (open / ruled out by E# /
   confirmed by E#); code checks that every confirmed one rests on live evidence and that no open
   one is silently dropped. (The "hypotheses panel" parked on 2026-10-12.)
3. **Self-check before the report.** Code runs the audit's checks (C1-C5 in
   `docs/diagnosis-audit.md`) plus path coverage (devices on the path neither checked nor
   explained) and sends back one list of gaps. At most two rounds, so it cannot loop or burn
   tokens.
4. **Halfway checkpoint.** At about 70% of the tool budget with no explanation, ask the agent to
   list what it knows and its remaining suspects, then pick the most likely.
5. **Measure every change** with the evaluation set (`backend/src/evals`). Needs a model that can
   finish runs (Groq Developer tier or Azure).

## Why it matters for the UI

With explicit hypotheses, the UI's suspect board shows the agent's own suspects, and a change of
mind becomes visible (a suspect struck out, the AI marker turning back to another device, a
"re-checking" step). Honest, and more convincing than an agent that never doubts itself.
