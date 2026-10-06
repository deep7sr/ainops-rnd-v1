"""The knowledge graph in Neo4j: sites, devices, interfaces, subnets and the links between them.

Model (what you see in Neo4j Browser):

    (:Site)<-[:LOCATED_AT]-(:Device)-[:HAS_INTERFACE]->(:Interface)-[:IN_SUBNET]->(:Subnet)
    (:Device)-[:LINK {a_interface, b_interface, subnet, sources}]->(:Device)
    (:Discovery {at, ...})   one node per discovery run, the newest is the current snapshot

The graph is written only by the discovery job (plain code). The agent reads it through the
topology MCP server. Paths are computed on LINK relationships: the physical/logical path between
two devices, which the agent then checks hop by hop with the live network tools.
"""

import ipaddress
from dataclasses import dataclass, field
from typing import Any

from neo4j import Driver, GraphDatabase

from ainops.inventory import Inventory

SCHEMA = [
    "CREATE CONSTRAINT site_code IF NOT EXISTS FOR (s:Site) REQUIRE s.code IS UNIQUE",
    "CREATE CONSTRAINT device_name IF NOT EXISTS FOR (d:Device) REQUIRE d.name IS UNIQUE",
    "CREATE CONSTRAINT interface_key IF NOT EXISTS FOR (i:Interface) REQUIRE i.key IS UNIQUE",
    "CREATE CONSTRAINT subnet_cidr IF NOT EXISTS FOR (n:Subnet) REQUIRE n.cidr IS UNIQUE",
]


@dataclass
class InterfaceFact:
    device: str
    name: str
    status: str
    ipv4: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.device}:{self.name}"

    def subnets(self) -> list[str]:
        return [str(ipaddress.ip_interface(a).network) for a in self.ipv4]


@dataclass
class LinkFact:
    a: str
    a_interface: str
    b: str
    b_interface: str
    subnet: str | None
    sources: list[str]  # how it was found: "cdp", "lldp", "subnet"

    @property
    def key(self) -> str:
        ends = sorted([(self.a, self.a_interface), (self.b, self.b_interface)])
        return "|".join(f"{d}:{i}" for d, i in ends)


class GraphStore:
    def __init__(self, uri: str, user: str, password: str) -> None:
        # Neo4j sends a warning for every query that mentions a label not created yet (an empty
        # graph before the first discovery): harmless, so they are switched off.
        self.driver: Driver = GraphDatabase.driver(
            uri, auth=(user, password), notifications_min_severity="OFF"
        )

    def close(self) -> None:
        self.driver.close()

    def _read(self, query: str, **params: Any) -> list[dict[str, Any]]:
        records, _, _ = self.driver.execute_query(query, params, routing_="r")
        return [record.data() for record in records]

    def _write(self, query: str, **params: Any) -> None:
        self.driver.execute_query(query, params)

    # ---------- written by discovery ----------

    def replace_topology(
        self,
        inventory: Inventory,
        interfaces: list[InterfaceFact],
        links: list[LinkFact],
        run: dict[str, Any],
    ) -> None:
        """Make the graph match one discovery run (devices from the inventory, the rest found)."""
        for statement in SCHEMA:
            self._write(statement)
        self._write("MATCH (n) WHERE n:Interface OR n:Subnet DETACH DELETE n")
        self._write("MATCH ()-[l:LINK]->() DELETE l")
        self._write(
            "UNWIND $sites AS s MERGE (site:Site {code: s.code}) SET site.name = s.name",
            sites=[{"code": c, "name": n} for c, n in inventory.sites.items()],
        )
        # Two statements on purpose: after a MATCH that finds nothing, a WITH has no rows and the
        # rest of the query would silently never run.
        self._write(
            "MATCH (d:Device) WHERE NOT d.name IN $names DETACH DELETE d",
            names=[d.name for d in inventory.devices],
        )
        self._write(
            """
            UNWIND $devices AS x
            MERGE (d:Device {name: x.name})
            SET d += x
            WITH d, x
            MATCH (s:Site {code: x.site})
            MERGE (d)-[:LOCATED_AT]->(s)
            """,
            devices=[
                {
                    "name": d.name,
                    "site": d.site,
                    "role": d.role,
                    "platform": d.platform,
                    "description": d.description,
                    "aliases": list(d.aliases),
                }
                for d in inventory.devices
            ],
        )
        self._write(
            """
            UNWIND $interfaces AS x
            MATCH (d:Device {name: x.device})
            CREATE (i:Interface {key: x.key, device: x.device, name: x.name, status: x.status,
                                 ipv4: x.ipv4})
            CREATE (d)-[:HAS_INTERFACE]->(i)
            WITH i, x
            UNWIND x.subnets AS cidr
            MERGE (n:Subnet {cidr: cidr})
            CREATE (i)-[:IN_SUBNET]->(n)
            """,
            interfaces=[
                {
                    "key": i.key,
                    "device": i.device,
                    "name": i.name,
                    "status": i.status,
                    "ipv4": i.ipv4,
                    "subnets": i.subnets(),
                }
                for i in interfaces
            ],
        )
        self._write(
            """
            UNWIND $links AS x
            MATCH (a:Device {name: x.a}), (b:Device {name: x.b})
            CREATE (a)-[:LINK {key: x.key, a_interface: x.a_interface, b_interface: x.b_interface,
                               subnet: x.subnet, sources: x.sources}]->(b)
            """,
            links=[
                {
                    "key": link.key,
                    "a": link.a,
                    "a_interface": link.a_interface,
                    "b": link.b,
                    "b_interface": link.b_interface,
                    "subnet": link.subnet,
                    "sources": link.sources,
                }
                for link in links
            ],
        )
        self._write("CREATE (r:Discovery) SET r = $run", run=run)

    def clear(self) -> None:
        self._write("MATCH (n) DETACH DELETE n")

    # ---------- read by the topology tools and the UI ----------

    def last_discovery(self) -> dict[str, Any] | None:
        rows = self._read("MATCH (r:Discovery) RETURN r ORDER BY r.at DESC LIMIT 1")
        return dict(rows[0]["r"]) if rows else None

    def devices(self, site: str | None = None, role: str | None = None) -> list[dict[str, Any]]:
        return self._read(
            """
            MATCH (d:Device)
            WHERE ($site IS NULL OR toUpper(d.site) = toUpper($site))
              AND ($role IS NULL OR toLower(d.role) CONTAINS toLower($role))
            RETURN d.name AS name, d.site AS site, d.role AS role, d.platform AS platform,
                   d.description AS description, d.aliases AS aliases
            ORDER BY d.site, d.name
            """,
            site=site,
            role=role,
        )

    def device(self, name: str) -> dict[str, Any] | None:
        rows = self._read(
            """
            MATCH (d:Device)
            WHERE toUpper(d.name) = toUpper($name)
               OR any(a IN coalesce(d.aliases, []) WHERE toUpper(a) = toUpper($name))
            OPTIONAL MATCH (d)-[:HAS_INTERFACE]->(i:Interface)
            WITH d, i ORDER BY i.name
            RETURN d.name AS name, d.site AS site, d.role AS role, d.platform AS platform,
                   d.description AS description, d.aliases AS aliases,
                   [x IN collect(i) WHERE x IS NOT NULL |
                    {name: x.name, status: x.status, ipv4: x.ipv4}] AS interfaces
            """,
            name=name.strip(),
        )
        return rows[0] if rows else None

    def owner_of_ip(self, address: str) -> list[dict[str, Any]]:
        """Interfaces that own this IP, or whose subnet contains it (e.g. a LAN host)."""
        rows = self._read(
            "MATCH (d:Device)-[:HAS_INTERFACE]->(i:Interface) "
            "RETURN d.name AS device, d.site AS site, i.name AS interface, i.ipv4 AS ipv4, "
            "i.status AS status"
        )
        return owners_of_ip(rows, address)

    def links(self, device: str | None = None) -> list[dict[str, Any]]:
        rows = self._read(
            """
            MATCH (a:Device)-[l:LINK]->(b:Device)
            WHERE $device IS NULL OR toUpper(a.name) = toUpper($device)
               OR toUpper(b.name) = toUpper($device)
            OPTIONAL MATCH (a)-[:HAS_INTERFACE]->(ai:Interface {name: l.a_interface})
            OPTIONAL MATCH (b)-[:HAS_INTERFACE]->(bi:Interface {name: l.b_interface})
            RETURN l.key AS key, a.name AS a, l.a_interface AS a_interface, ai.status AS a_status,
                   b.name AS b, l.b_interface AS b_interface, bi.status AS b_status,
                   l.subnet AS subnet, l.sources AS sources, a.site AS a_site, b.site AS b_site
            ORDER BY a, b
            """,
            device=device,
        )
        return rows

    def path(self, source: str, destination: str) -> list[dict[str, Any]]:
        """Shortest chain of links from one device to another (each hop with its interfaces)."""
        rows = self._read(
            """
            MATCH (s:Device), (t:Device)
            WHERE toUpper(s.name) = toUpper($source) AND toUpper(t.name) = toUpper($destination)
            MATCH p = shortestPath((s)-[:LINK*..12]-(t))
            RETURN [n IN nodes(p) | n.name] AS devices,
                   [r IN relationships(p) | {from: startNode(r).name, to: endNode(r).name,
                     from_interface: r.a_interface, to_interface: r.b_interface,
                     subnet: r.subnet}] AS links
            """,
            source=source,
            destination=destination,
        )
        if not rows:
            return []
        devices: list[str] = rows[0]["devices"]
        hops = []
        for index, link in enumerate(rows[0]["links"]):
            here, there = devices[index], devices[index + 1]
            forward = link["from"] == here
            hops.append(
                {
                    "from": here,
                    "from_interface": link["from_interface"] if forward else link["to_interface"],
                    "to": there,
                    "to_interface": link["to_interface"] if forward else link["from_interface"],
                    "subnet": link["subnet"],
                }
            )
        return hops

    def snapshot(self) -> dict[str, Any]:
        """Everything the UI map needs in one call."""
        devices = self._read(
            """
            MATCH (d:Device)
            OPTIONAL MATCH (d)-[:HAS_INTERFACE]->(i:Interface)
            WITH d, i ORDER BY i.name
            RETURN d.name AS name, d.site AS site, d.role AS role, d.platform AS platform,
                   d.description AS description,
                   [x IN collect(i) WHERE x IS NOT NULL |
                    {name: x.name, status: x.status, ipv4: x.ipv4}] AS interfaces
            ORDER BY d.site, d.name
            """
        )
        return {
            "devices": devices,
            "links": self.links(),
            "discovery": self.last_discovery(),
        }


def owners_of_ip(interfaces: list[dict[str, Any]], address: str) -> list[dict[str, Any]]:
    """The interfaces that own `address`, or else those whose subnet contains it.

    `interfaces` rows have device, site, interface, ipv4 (a list of "a.b.c.d/len") and status.
    """
    ip = ipaddress.ip_address(address)
    exact, containing = [], []
    for row in interfaces:
        for cidr in row["ipv4"] or []:
            iface = ipaddress.ip_interface(cidr)
            if iface.ip == ip:
                exact.append({**row, "match": "owns this address", "subnet": str(iface.network)})
            elif ip in iface.network:
                containing.append(
                    {
                        **row,
                        "match": "address is in this interface's subnet",
                        "subnet": str(iface.network),
                    }
                )
    return exact or containing
