# Routing tables for the trace_route tests

`show ip route` (Cisco) and `show route | display json` (Juniper) outputs, one folder per scenario,
laid out like `fixtures/lab` so the replay executor can read them.

| File | Where it comes from |
|---|---|
| healthy/CORE-SW-TRV, healthy/IPLC-RTR-TRV | live lab, 2026-10-05 (healthy) |
| healthy/CORE-SW-MAA | live lab, 2026-10-05/06 |
| healthy/FWL-MAA | live lab, 2026-10-06 |
| fault1/IPLC-RTR-TRV | live lab, 2026-10-05, IPLC-RTR-MAA Fa2/0 shut (fault 1) |
| healthy/IPLC-RTR-MAA | live lab, 2026-10-07 (the earlier rebuilt table matched it route for route) |
| fault1/CORE-SW-TRV | live lab, 2026-10-07, fault 1 (the earlier rebuilt table matched it route for route) |

Every file is now a live recording.
