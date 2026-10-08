---
name: leased-line-health
description: Use when asked whether the leased line (IPLC) between TRV and MAA is up or healthy, or about errors or flaps on it.
metadata:
  author: drafted by Claude for Praveen to review
  reviewed_by: ""
---
The line is healthy only if all of these pass: the interface is up on both sides, the OSPF
neighbour across it is FULL on both sides, a ping across it gets every reply (losing only the
first one is normal: ARP), and there are no
input errors or recent flaps. Report every check, also when the line is healthy.

1. `get_device_links` on IPLC-RTR-TRV to find the link to MAA: the interface on each router and
   the subnet of the line.
2. `get_interfaces` on IPLC-RTR-TRV and on IPLC-RTR-MAA: the leased-line interface must be up on
   both.
3. `get_interface_detail` on the leased-line interface of both routers: input errors, CRC and when
   it last flapped.
4. `get_ospf_neighbors` on both routers: the neighbour across the line must be FULL.
5. `ping` from IPLC-RTR-TRV to IPLC-RTR-MAA's address on the line (seen in step 1 or 2).
