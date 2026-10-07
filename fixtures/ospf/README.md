# OSPF neighbour tables for the expected-neighbour tests

`show ip ospf neighbor` from the live lab, 2026-10-07, laid out like `fixtures/lab`.

| Folder | State |
|---|---|
| healthy | both leased-line routers FULL with each other and with their core router |
| fault1 | IPLC-RTR-MAA Fa2/0 shut: IPLC-RTR-TRV has lost its neighbour across the leased line |
