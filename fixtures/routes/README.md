# Routing tables for the trace_route tests

`show ip route` (Cisco) and `show route | display json` (Juniper) outputs, one folder per scenario,
laid out like `fixtures/lab` so the replay executor can read them.

| File | Where it comes from |
|---|---|
| healthy/CORE-SW-TRV, healthy/IPLC-RTR-TRV | live lab, 2026-10-05 (healthy) |
| healthy/CORE-SW-MAA | live lab, 2026-10-05/06 |
| healthy/FWL-MAA | live lab, 2026-10-06 |
| fault1/IPLC-RTR-TRV | live lab, 2026-10-05, IPLC-RTR-MAA Fa2/0 shut (fault 1) |
| healthy/IPLC-RTR-MAA | **rebuilt** from its interface addresses in the same format: never recorded |
| fault1/CORE-SW-TRV | **rebuilt**: the healthy table without the three routes learned over the leased line |

Replace the rebuilt files with live recordings when the lab is up.
