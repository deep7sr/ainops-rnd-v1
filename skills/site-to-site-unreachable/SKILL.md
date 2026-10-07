---
name: site-to-site-unreachable
description: Use when users or hosts at one site (TRV or MAA) cannot reach a host or network at the other site.
metadata:
  author: drafted by Claude for Praveen to review
  reviewed_by: ""
---
Follow the traffic the way the routers send it, find where it stops, then find why.

1. `trace_route` from the source host or LAN to the destination IP. Note the device where it
   stops and whether the routes on the way were learned from OSPF.
2. If it stops with no route: `get_ospf_neighbors` on that device, then on each router towards
   the other site (`get_path` shows the order) until one has its neighbour across the leased
   line missing or not FULL.
3. On that router: `get_interfaces`, and look at the interface towards the other site.
   Administratively down means someone shut it; down means a cable or provider problem.
4. If that interface is up, the fault may be on the far side: `get_device_links` to find the
   router at the other end, then `get_interfaces` on it.
5. If the trace arrived: `trace_route` back from the destination side to the source, because
   replies need a way back too.
6. If routing is complete both ways: `ping` the destination from the last router; if it fails,
   `get_arp_table` on that router (no entry for the host = the host is off or not on that LAN).
