---
name: ospf-neighbour-down
description: Use when an OSPF neighbour is missing or not FULL on a router, or a router is missing the routes to the other site.
metadata:
  author: drafted by Claude for Praveen to review
  reviewed_by: ""
---
Routers learn the other site's networks from their OSPF neighbours. A neighbour that is missing
or stuck before FULL means those routes are not exchanged.

1. `get_ospf_neighbors` on the router: which neighbour is missing or not FULL, and on which
   interface.
2. `get_interfaces` on the router: is the interface towards that neighbour up? Administratively
   down means someone shut it; down means a link problem.
3. If it is up: `get_interface_detail` on it, for errors or recent flaps.
4. `get_device_links` to find the router at the other end, then `get_interfaces` and
   `get_ospf_neighbors` on it: the fault may be on that side.
5. If the interfaces are up on both sides: `get_routing_protocols` on both routers (Cisco only):
   same OSPF area, the link's network included, and the interface not passive.
6. `get_logs` on both routers, for OSPF or link changes and when they happened.
