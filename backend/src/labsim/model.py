"""The simulated lab as data: devices, interfaces, cables, OSPF settings, and the faults.

Read from two files: lab/inventory.yaml (the same file AINOPS reads: names, platforms, console
ports, login profiles) and labsim/lab.yaml (the network behind them). Both must name the same
devices, so the simulator can never answer for a device AINOPS does not know, or the other way
round.

A fault is a list of changes to this data (shut an interface, change an address, ...). Applying
faults gives a new Lab; the simulator works out every answer from the Lab it currently has.
"""

import copy
import hashlib
import ipaddress
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

LAB_FILE = Path(__file__).with_name("lab.yaml")
REPO_ROOT = Path(__file__).resolve().parents[3]
INVENTORY_FILE = REPO_ROOT / "lab" / "inventory.yaml"

HOST = "host"  # the platform of an end host (PC): answers pings, never forwards


class LabError(ValueError):
    """lab.yaml or a fault does not fit together with the inventory."""


@dataclass
class Interface:
    name: str  # full name: FastEthernet2/0, Ethernet1/0, ge-0/0/1, eth0 (hosts)
    admin_up: bool
    address: ipaddress.IPv4Interface | None
    mac: str  # Cisco dotted form: ca08.50ec.0038

    @property
    def cost(self) -> int:
        """OSPF cost with the default 100 Mbit/s reference: FastEthernet/ge 1, Ethernet 10."""
        return 10 if self.name.startswith("Ethernet") else 1


@dataclass(frozen=True)
class OspfNetwork:
    network: ipaddress.IPv4Address
    wildcard: ipaddress.IPv4Address
    area: str

    @classmethod
    def parse(cls, text: str) -> "OspfNetwork":
        match = re.fullmatch(r"(\S+) (\S+) area (\S+)", text.strip())
        if not match:
            raise LabError(f"OSPF network '{text}' is not 'a.b.c.d wildcard area n'")
        return cls(ipaddress.IPv4Address(match[1]), ipaddress.IPv4Address(match[2]), match[3])

    def matches(self, address: ipaddress.IPv4Address) -> bool:
        keep = ~int(self.wildcard) & 0xFFFFFFFF
        return int(address) & keep == int(self.network) & keep

    def __str__(self) -> str:
        return f"{self.network} {self.wildcard} area {self.area}"


@dataclass
class Ospf:
    process: int
    router_id: str
    networks: list[OspfNetwork]
    passive: set[str] = field(default_factory=set)


@dataclass
class Device:
    name: str
    platform: str  # cisco_ios, juniper_junos or host
    port: int | None  # console port (None for hosts)
    credential_ref: str | None
    interfaces: dict[str, Interface]
    ospf: Ospf | None = None
    zones: dict[str, list[str]] | None = None  # Junos security zones -> units (ge-0/0/1.0)
    gateway: ipaddress.IPv4Address | None = None  # hosts only

    @property
    def is_host(self) -> bool:
        return self.platform == HOST


@dataclass(frozen=True)
class End:
    """One end of a cable: a device (or host) and its interface."""

    device: str
    interface: str


@dataclass(frozen=True)
class Fault:
    name: str
    description: str
    changes: tuple[dict[str, Any], ...]


@dataclass
class Lab:
    devices: dict[str, Device]
    links: list[tuple[End, End]]
    faults: dict[str, Fault]

    def peer(self, device: str, interface: str) -> End | None:
        """The other end of the cable plugged into this interface (None: no cable)."""
        for a, b in self.links:
            if a == End(device, interface):
                return b
            if b == End(device, interface):
                return a
        return None

    def consoles(self) -> list[Device]:
        return [d for d in self.devices.values() if not d.is_host]


# ---------- MAC addresses, as EVE-NG makes them ----------


def _slot_port(name: str) -> tuple[int, int]:
    numbers = [int(n) for n in re.findall(r"\d+", name)]
    return (numbers[-2], numbers[-1]) if len(numbers) >= 2 else (0, numbers[-1] if numbers else 0)


def _mac(platform: str, node: int, mac_id: str, interface: str) -> str:
    if platform == "juniper_junos":  # qemu nodes: 50:00:00:<node>:00:<port + 1>
        return f"5000.{node:04x}.{_slot_port(interface)[1] + 1:04x}"
    slot, port = _slot_port(interface)  # dynamips: ca<node>.<id>.<slot * 0x1c + port>
    return f"ca{node:02x}.{mac_id}.{slot * 0x1C + port:04x}"


def _mac_id(name: str) -> str:
    return hashlib.sha256(name.encode()).hexdigest()[:4]


# ---------- loading ----------


def _end(text: str, names: dict[str, Device]) -> End:
    device, _, interface = str(text).partition(" ")
    if device not in names:
        raise LabError(f"link end '{text}': no device or host named {device}")
    owner = names[device]
    interface = interface.strip() or ("eth0" if owner.is_host else "")
    if interface not in owner.interfaces:
        raise LabError(f"link end '{text}': {device} has no interface '{interface}'")
    return End(device, interface)


def _inventory(path: Path) -> dict[str, dict[str, Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {entry["name"]: entry for entry in data.get("devices") or []}


def load_lab(lab_file: Path = LAB_FILE, inventory_file: Path = INVENTORY_FILE) -> Lab:
    raw = yaml.safe_load(lab_file.read_text(encoding="utf-8"))
    inventory = _inventory(inventory_file)
    modelled = set(raw.get("devices") or {})
    if modelled != set(inventory):
        missing = sorted(set(inventory) - modelled)
        extra = sorted(modelled - set(inventory))
        raise LabError(
            f"lab.yaml and the inventory must name the same devices (not in lab.yaml: "
            f"{missing or '-'}; not in the inventory: {extra or '-'})"
        )

    devices: dict[str, Device] = {}
    for name, spec in raw["devices"].items():
        entry = inventory[name]
        platform = entry["platform"]
        node = int(spec["node"])
        mac_id = str(spec.get("mac_id") or _mac_id(name))
        interfaces = {}
        for if_name, if_spec in (spec.get("interfaces") or {}).items():
            if_spec = if_spec or {}
            address = if_spec.get("address")
            interfaces[if_name] = Interface(
                name=if_name,
                admin_up=if_spec.get("admin", "up") != "down",
                address=ipaddress.IPv4Interface(address) if address else None,
                mac=_mac(platform, node, mac_id, if_name),
            )
        ospf = None
        if spec.get("ospf"):
            o = spec["ospf"]
            ospf = Ospf(
                process=int(o["process"]),
                router_id=str(o["router_id"]),
                networks=[OspfNetwork.parse(n) for n in o.get("networks") or []],
                passive=set(o.get("passive") or []),
            )
        zones = spec.get("zones")
        devices[name] = Device(
            name=name,
            platform=platform,
            port=int(entry["port"]),
            credential_ref=entry.get("credential_ref"),
            interfaces=interfaces,
            ospf=ospf,
            zones={z: list(units or []) for z, units in zones.items()} if zones else None,
        )

    for name, spec in (raw.get("hosts") or {}).items():
        if name in devices:
            raise LabError(f"host {name} has the name of a device")
        gateway = spec.get("gateway")
        devices[name] = Device(
            name=name,
            platform=HOST,
            port=None,
            credential_ref=None,
            interfaces={
                "eth0": Interface(
                    "eth0", True, ipaddress.IPv4Interface(spec["address"]), str(spec["mac"])
                )
            },
            gateway=ipaddress.IPv4Address(gateway) if gateway else None,
        )

    links: list[tuple[End, End]] = []
    used: set[End] = set()
    for pair in raw.get("links") or []:
        a, b = (_end(text, devices) for text in pair)
        for end in (a, b):
            if end in used:
                raise LabError(f"{end.device} {end.interface} has more than one cable")
            used.add(end)
        links.append((a, b))

    faults = {
        name: Fault(name, str(spec.get("description", "")), tuple(spec.get("changes") or []))
        for name, spec in (raw.get("faults") or {}).items()
    }
    lab = Lab(devices, links, faults)
    for fault in faults.values():
        apply_faults(lab, [fault.name])  # a fault that does not fit the lab fails at load time
    return lab


# ---------- faults ----------


def _change(lab: Lab, change: dict[str, Any], fault: str) -> None:
    where = f"fault {fault}: change {change!r}"
    device = lab.devices.get(str(change.get("device")))
    if device is None or device.is_host:
        raise LabError(f"{where}: no device named {change.get('device')!r}")
    if "interface" in change:
        interface = device.interfaces.get(str(change["interface"]))
        if interface is None:
            raise LabError(f"{where}: {device.name} has no interface {change['interface']!r}")
        if "admin" in change:
            if change["admin"] not in ("up", "down"):
                raise LabError(f"{where}: admin must be up or down")
            interface.admin_up = change["admin"] == "up"
        elif "address" in change:
            interface.address = ipaddress.IPv4Interface(str(change["address"]))
        else:
            raise LabError(f"{where}: an interface change needs admin or address")
        return
    if device.ospf is None:
        raise LabError(f"{where}: {device.name} does not run OSPF")
    if "ospf_passive" in change:
        if change["ospf_passive"] not in device.interfaces:
            raise LabError(f"{where}: {device.name} has no interface {change['ospf_passive']!r}")
        device.ospf.passive.add(str(change["ospf_passive"]))
    elif "ospf_remove_network" in change:
        network = OspfNetwork.parse(str(change["ospf_remove_network"]))
        if network not in device.ospf.networks:
            raise LabError(f"{where}: {device.name} has no OSPF network '{network}'")
        device.ospf.networks.remove(network)
    else:
        raise LabError(f"{where}: unknown kind of change")


def apply_faults(lab: Lab, names: list[str]) -> Lab:
    """A copy of the lab with these faults applied, in order (the original is not changed)."""
    changed = copy.deepcopy(lab)
    for name in names:
        fault = lab.faults.get(name)
        if fault is None:
            raise LabError(f"no fault named {name!r} (known: {', '.join(sorted(lab.faults))})")
        for change in fault.changes:
            _change(changed, change, name)
    return changed
