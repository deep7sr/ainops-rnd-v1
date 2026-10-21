"""Cisco IOS 15.2 (c7200) answers, laid out exactly like the real lab's recordings in fixtures/.

`answer` gets one command line as typed at the router prompt and returns what the router prints
(without the echo and the next prompt, which the console adds).
"""

import ipaddress
import random
import re
from collections.abc import Callable

from labsim import network
from labsim.model import Device, Interface
from labsim.state import View

IOS_LINE = (
    "Cisco IOS Software, 7200 Software (C7200-ADVENTERPRISEK9-M), Version 15.2(4)S6, "
    "RELEASE SOFTWARE (fc1)"
)
PLATFORM = "7206VXR"
INVALID = "% Invalid input detected at '^' marker."
NOT_SIMULATED = INVALID + " (labsim does not simulate this command)"

_LONG = {"fa": "FastEthernet", "fastethernet": "FastEthernet", "e": "Ethernet",
         "et": "Ethernet", "eth": "Ethernet", "ethernet": "Ethernet"}  # fmt: skip


def interface_name(device: Device, typed: str) -> Interface | None:
    """Fa2/0, fa 2/0, FastEthernet2/0 -> the interface (None if there is none)."""
    match = re.fullmatch(r"([A-Za-z]+)\s*([\d/]+)", typed.strip())
    if not match:
        return None
    prefix = match[1].lower()
    full = next((v for k, v in _LONG.items() if k == prefix), None)
    if full is None:
        full = next((v for k, v in _LONG.items() if v.lower().startswith(prefix)), None)
    return device.interfaces.get(f"{full}{match[2]}") if full else None


def short(name: str) -> str:
    """FastEthernet2/0 -> Fas 2/0 (how CDP prints interfaces)."""
    for long, abbreviation in (("FastEthernet", "Fas "), ("Ethernet", "Eth ")):
        if name.startswith(long):
            return abbreviation + name[len(long) :]
    return name


def _age(seconds: float) -> str:
    """Route age as IOS prints it: 01:16:23, 1d02h, 1w2d."""
    s = max(0, int(seconds))
    if s < 86400:
        return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"
    if s < 7 * 86400:
        return f"{s // 86400}d{s % 86400 // 3600:02d}h"
    return f"{s // (7 * 86400)}w{s % (7 * 86400) // 86400}d"


def _uptime(seconds: float) -> str:
    minutes = max(0, int(seconds)) // 60
    days, hours, mins = minutes // 1440, minutes % 1440 // 60, minutes % 60
    parts = [(days, "day"), (hours, "hour"), (mins, "minute")]
    shown = [f"{n} {word}{'s' if n != 1 else ''}" for n, word in parts if n] or ["0 minutes"]
    return ", ".join(shown)


# ---------- show version ----------


def show_version(view: View, device: Device) -> str:
    fast = sum(1 for n in device.interfaces if n.startswith("FastEthernet"))
    ethernet = sum(1 for n in device.interfaces if n.startswith("Ethernet"))
    board = 4279256517 + sum(device.name.encode())
    lines = [
        IOS_LINE,
        "Technical Support: http://www.cisco.com/techsupport",
        "Copyright (c) 1986-2014 by Cisco Systems, Inc.",
        "Compiled Thu 26-Jun-14 14:09 by prod_rel_team",
        "",
        "ROM: ROMMON Emulation Microcode",
        "BOOTLDR: 7200 Software (C7200-ADVENTERPRISEK9-M), Version 15.2(4)S6, RELEASE SOFTWARE "
        "(fc1)",
        "",
        f"{device.name} uptime is {_uptime(view.now - view.started)}",
        "System returned to ROM by unknown reload cause - suspect boot_data[BOOT_COUNT] 0x0, "
        "BOOT_COUNT 0, BOOTDATA 19",
        'System image file is "tftp://255.255.255.255/unknown"',
        "Last reload reason: unknown reload cause - suspect boot_data[BOOT_COUNT] 0x0, "
        "BOOT_COUNT 0, BOOTDATA 19",
        "",
        "",
        "",
        "Cisco 7206VXR (NPE400) processor (revision A) with 491520K/32768K bytes of memory.",
        f"Processor board ID {board}",
        "R7000 CPU at 150MHz, Implementation 39, Rev 2.1, 256KB L2 Cache",
        "6 slot VXR midplane, Version 2.1",
        "",
        "Last reset from power-on",
        "",
        "PCI bus mb0_mb1 (Slots 0, 1, 3 and 5) has a capacity of 600 bandwidth points.",
        "Current configuration on bus mb0_mb1 has a total of 600 bandwidth points. ",
        "This configuration is within the PCI bus capacity and is supported. ",
        "",
        "PCI bus mb2 (Slots 2, 4, 6) has a capacity of 600 bandwidth points.",
        "Current configuration on bus mb2 has a total of 200 bandwidth points ",
        "This configuration is within the PCI bus capacity and is supported. ",
        "",
        'Please refer to the following document "Cisco 7200 Series Port Adaptor',
        'Hardware Configuration Guidelines" on Cisco.com <http://www.cisco.com>',
        "for c7200 bandwidth points oversubscription and usage guidelines.",
        "",
        "",
    ]
    if fast:
        lines.append(f"{fast} FastEthernet interface{'s' if fast != 1 else ''}")
    if ethernet:
        lines.append(f"{ethernet} Ethernet interface{'s' if ethernet != 1 else ''}")
    lines += [
        "509K bytes of NVRAM.",
        "",
        "8192K bytes of Flash internal SIMM (Sector size 256K).",
        "Configuration register is 0x2102",
        "",
    ]
    return "\n".join(lines)


# ---------- interfaces ----------

_IP_BLOCK = """\
  Broadcast address is 255.255.255.255
  Address determined by non-volatile memory
  MTU is 1500 bytes
  Helper address is not set
  Directed broadcast forwarding is disabled
{multicast}  Outgoing access list is not set
  Inbound  access list is not set
  Proxy ARP is enabled
  Local Proxy ARP is disabled
  Security level is default
  Split horizon is enabled
  ICMP redirects are always sent
  ICMP unreachables are always sent
  ICMP mask replies are never sent
  IP fast switching is enabled
  IP Flow switching is disabled
  IP CEF switching is enabled
  IP CEF switching turbo vector
  IP CEF turbo switching turbo vector
  Associated unicast routing topologies:
        Topology "base", operation state is {topology}
  IP multicast fast switching is enabled
  IP multicast distributed fast switching is disabled
  IP route-cache flags are Fast, CEF
  Router Discovery is disabled
  IP output packet accounting is disabled
  IP access violation accounting is disabled
  TCP/IP header compression is disabled
  RTP/IP header compression is disabled
  Probe proxy name replies are disabled
  Policy routing is disabled
  Network address translation is disabled
  BGP Policy Mapping is disabled
  Input features: MCI Check
  WCCP Redirect outbound is disabled
  WCCP Redirect inbound is disabled
  WCCP Redirect exclude is disabled
"""


def _status_line(interface: Interface) -> str:
    if interface.admin_up:
        return f"{interface.name} is up, line protocol is up"
    return f"{interface.name} is administratively down, line protocol is down"


def show_ip_interface(view: View, device: Device) -> str:
    talking = {
        name
        for name in network.ospf_interfaces(device)
        if device.ospf is not None and name not in device.ospf.passive
    }
    out = []
    for interface in device.interfaces.values():
        out.append(_status_line(interface) + "\n")
        if interface.address is None:
            out.append("  Internet protocol processing disabled\n")
            continue
        out.append(f"  Internet address is {interface.address.with_prefixlen}\n")
        multicast = (
            "  Multicast reserved groups joined: 224.0.0.5 224.0.0.6\n"
            if interface.name in talking
            else ""
        )
        topology = "UP" if interface.admin_up else "DOWN"
        out.append(_IP_BLOCK.format(multicast=multicast, topology=topology))
    return "".join(out).rstrip("\n")


def show_interfaces(view: View, device: Device, interface: Interface) -> str:
    fast = interface.name.startswith("FastEthernet")
    seconds = int(view.now - view.started)
    packets_in = seconds // 10 * 3 if interface.admin_up else 0
    packets_out = seconds // 10 * 3 + (seconds // 60 if interface.admin_up else 0)
    lines = [
        _status_line(interface) + " ",
        f"  Hardware is {'DEC21140' if fast else 'AmdP2'}, address is {interface.mac} "
        f"(bia {interface.mac})",
    ]
    if interface.address is not None:
        lines.append(f"  Internet address is {interface.address.with_prefixlen}")
    lines += [
        f"  MTU 1500 bytes, BW {'100000' if fast else '10000'} Kbit/sec, "
        f"DLY {'100' if fast else '1000'} usec, ",
        "     reliability 255/255, txload 1/255, rxload 1/255",
        "  Encapsulation ARPA, loopback not set",
        "  Keepalive set (10 sec)",
        "  Full-duplex, 100Mb/s, 100BaseTX/FX" if fast else "  Half-duplex, 10Mb/s",
        "  ARP type: ARPA, ARP Timeout 04:00:00",
        "  Last input 00:00:02, output 00:00:03, output hang never"
        if interface.admin_up
        else "  Last input never, output never, output hang never",
        '  Last clearing of "show interface" counters never',
        "  Input queue: 0/75/0/0 (size/max/drops/flushes); Total output drops: 0",
        "  Queueing strategy: fifo",
        "  Output queue: 0/40 (size/max)",
        "  5 minute input rate 0 bits/sec, 0 packets/sec",
        "  5 minute output rate 0 bits/sec, 0 packets/sec",
        f"     {packets_in} packets input, {packets_in * 92} bytes",
        f"     Received {packets_in} broadcasts (0 IP multicasts)",
        "     0 runts, 0 giants, 0 throttles",
        "     0 input errors, 0 CRC, 0 frame, 0 overrun, 0 ignored",
        "     0 watchdog",
        "     0 input packets with dribble condition detected",
        f"     {packets_out} packets output, {packets_out * 96} bytes, 0 underruns",
        "     0 output errors, 0 collisions, 1 interface resets",
        "     0 unknown protocol drops",
        "     0 babbles, 0 late collision, 0 deferred",
        "     0 lost carrier, 0 no carrier",
        "     0 output buffer failures, 0 output buffers swapped out",
    ]
    return "\n".join(lines)


# ---------- routing ----------

# One quoted string per line: IOS ends some lines with a space, which a multi-line string would
# lose to the trailing-whitespace commit hook.
_ROUTE_CODES = "\n".join(
    [
        "Codes: L - local, C - connected, S - static, R - RIP, M - mobile, B - BGP",
        "       D - EIGRP, EX - EIGRP external, O - OSPF, IA - OSPF inter area ",
        "       N1 - OSPF NSSA external type 1, N2 - OSPF NSSA external type 2",
        "       E1 - OSPF external type 1, E2 - OSPF external type 2",
        "       i - IS-IS, su - IS-IS summary, L1 - IS-IS level-1, L2 - IS-IS level-2",
        "       ia - IS-IS inter area, * - candidate default, U - per-user static route",
        "       o - ODR, P - periodic downloaded static route, H - NHRP, l - LISP",
        "       + - replicated route, % - next hop override",
        "",
        "Gateway of last resort is not set",
        "",
        "",
    ]
)


def _classful(prefix: ipaddress.IPv4Network) -> ipaddress.IPv4Network:
    first = int(prefix.network_address) >> 24
    length = 8 if first < 128 else 16 if first < 192 else 24
    return ipaddress.IPv4Network(f"{prefix.network_address}/{length}", strict=False)


def _route_text(route: network.Route, age: str) -> list[str]:
    if route.code in ("C", "L"):
        return [f"{route.prefix} is directly connected, {route.hops[0].interface}"]
    texts = []
    for hop in route.hops:
        texts.append(f"[{route.distance}/{route.metric}] via {hop.address}, {age}, {hop.interface}")
    return [f"{route.prefix} {texts[0]}", *texts[1:]]


def show_ip_route(view: View, device: Device) -> str:
    age = _age(view.now - view.changed)
    groups: dict[ipaddress.IPv4Network, list[network.Route]] = {}
    for route in network.routes(view.lab, device.name):
        groups.setdefault(_classful(route.prefix), []).append(route)
    lines = []
    for major in sorted(groups, key=lambda n: int(n.network_address)):
        entries = groups[major]
        if len(entries) == 1 and entries[0].prefix.prefixlen == major.prefixlen:
            width = 6
        else:
            width = 9
            masks = {r.prefix.prefixlen for r in entries}
            if len(masks) > 1:
                lines.append(
                    f"      {major} is variably subnetted, {len(entries)} subnets, "
                    f"{len(masks)} masks"
                )
            else:
                lines.append(
                    f"      {major.network_address}/{masks.pop()} is subnetted, "
                    f"{len(entries)} subnet{'s' if len(entries) != 1 else ''}"
                )
        for route in entries:
            first, *more = _route_text(route, age)
            lines.append(f"{route.code:<{width}}{first}")
            indent = " " * (width + len(str(route.prefix)) + 1)
            lines.extend(indent + text for text in more)
    return _ROUTE_CODES + "\n".join(lines)


def show_ip_ospf_neighbor(view: View, device: Device) -> str:
    if device.ospf is None:
        return ""
    rows = network.adjacencies(view.lab, device.name)
    if not rows:
        return ""
    rng = random.Random()
    lines = ["", "Neighbor ID     Pri   State           Dead Time   Address         Interface"]
    for row in sorted(rows, key=lambda r: r.interface, reverse=True):
        dead = f"00:00:{rng.randint(30, 39):02d}"
        lines.append(
            f"{row.peer_router_id:<15} {1:>3}   {'FULL/' + row.peer_role:<15} {dead:<11} "
            f"{row.peer_address!s:<15} {row.interface}"
        )
    return "\n".join(lines)


def show_ip_protocols(view: View, device: Device) -> str:
    lines = ["*** IP Routing is NSF aware ***", ""]
    if device.ospf is None:
        return "\n".join(lines)
    ospf = device.ospf
    lines += [
        f'Routing Protocol is "ospf {ospf.process}"',
        "  Outgoing update filter list for all interfaces is not set",
        "  Incoming update filter list for all interfaces is not set",
        f"  Router ID {ospf.router_id}",
        "  Number of areas in this router is 1. 1 normal 0 stub 0 nssa",
        f"  Maximum path: {network.MAX_PATHS}",
        "  Routing for Networks:",
        *(f"    {n}" for n in ospf.networks),
    ]
    if ospf.passive:
        lines += ["  Passive Interface(s):", *(f"    {p}" for p in sorted(ospf.passive))]
    lines += ["  Routing Information Sources:", "    Gateway         Distance      Last Update"]
    sources = sorted(
        {
            view.lab.devices[r].ospf.router_id  # type: ignore[union-attr]
            for r in network._shortest(view.lab, device.name)[0]
            if r != device.name
        },
        key=lambda rid: int(ipaddress.IPv4Address(rid)),
    )
    age = _age(view.now - view.changed)
    lines += [f"    {rid:<15}{110:>9}      {age}" for rid in sources]
    lines.append("  Distance: (default is 110)")
    return "\n".join(lines)


# ---------- neighbours, ARP ----------


def show_cdp_neighbors(view: View, device: Device) -> str:
    lines = [
        "Capability Codes: R - Router, T - Trans Bridge, B - Source Route Bridge",
        "                  S - Switch, H - Host, I - IGMP, r - Repeater, P - Phone, ",
        "                  D - Remote, C - CVTA, M - Two-port Mac Relay ",
        "",
        "Device ID        Local Intrfce     Holdtme    Capability  Platform  Port ID",
    ]
    rng = random.Random()
    for local, end in sorted(network.cdp_neighbors(view.lab, device.name), reverse=True):
        lines.append(
            f"{end.device:<17}{short(local):<18}{rng.randint(120, 179):<18}R    {PLATFORM}   "
            f"{short(end.interface)}"
        )
    return "\n".join(lines)


def show_arp(view: View, device: Device) -> str:
    lines = ["Protocol  Address          Age (min)  Hardware Addr   Type   Interface"]
    for address, mac, interface, learned in network.arp_table(view.lab, device.name, view.cache):
        age = "-" if learned is None else str(int((view.now - learned) // 60))
        lines.append(f"Internet  {address!s:<17}{age:>8}   {mac}  ARPA   {interface}")
    return "\n".join(lines)


# ---------- ping ----------


def ping_text(destination: ipaddress.IPv4Address, result: network.PingResult) -> str:
    sent, received = len(result.marks), result.marks.count("!")
    summary = f"Success rate is {100 * received // sent} percent ({received}/{sent})"
    if result.rtts_ms:
        rtts = [round(r) for r in result.rtts_ms]
        summary += (
            f", round-trip min/avg/max = {min(rtts)}/{round(sum(rtts) / len(rtts))}/{max(rtts)} ms"
        )
    return "\n".join(
        [
            "Type escape sequence to abort.",
            f"Sending {sent}, 100-byte ICMP Echos to {destination}, timeout is 2 seconds:",
            result.marks,
            summary,
        ]
    )


# ---------- the command line ----------


def _filter(text: str, pipe: str) -> str | None:
    """IOS output modifiers: include, exclude, begin, section, count (None: not one of them)."""
    match = re.fullmatch(r"(include|exclude|begin|section|count)\s+(.+)", pipe.strip())
    if not match:
        return None
    kind, pattern = match[1], match[2]
    lines = text.split("\n")
    try:
        regex = re.compile(pattern)
    except re.error:
        regex = re.compile(re.escape(pattern))
    if kind in ("include", "section"):
        return "\n".join(line for line in lines if regex.search(line))
    if kind == "exclude":
        return "\n".join(line for line in lines if not regex.search(line))
    if kind == "begin":
        for i, line in enumerate(lines):
            if regex.search(line):
                return "\n".join(lines[i:])
        return ""
    return f"Number of lines which match regexp = {sum(1 for x in lines if regex.search(x))}"


Answer = Callable[[View, Device], str]

_SHOW: list[tuple[str, Answer]] = [
    (r"sh(ow?)? ver(s(i(on?)?)?)?", show_version),
    (r"sh(ow?)? ip int(e(r(f(a(ce?)?)?)?)?)?", show_ip_interface),
    (r"sh(ow?)? ip ro(u(te?)?)?", show_ip_route),
    (r"sh(ow?)? ip ospf nei(g(h(b(or?)?)?)?)?", show_ip_ospf_neighbor),
    (r"sh(ow?)? ip proto(c(o(ls?)?)?)?", show_ip_protocols),
    (r"sh(ow?)? cdp nei(g(h(b(o(rs?)?)?)?)?)?", show_cdp_neighbors),
    (r"sh(ow?)? arp", show_arp),
]


def answer(view: View, device: Device, line: str, privileged: bool) -> tuple[str, int]:
    """What the router prints for `line` (one command, maybe with a | modifier), and how many
    ping packets timed out (the console waits 2 s for each, like the real router)."""
    command, *pipes = [part.strip() for part in line.split("|")]
    lowered = " ".join(command.split()).lower()
    timeouts = 0
    text: str | None = None
    for pattern, render in _SHOW:
        if re.fullmatch(pattern, lowered):
            text = render(view, device)
            break
    if text is None:
        detail = re.fullmatch(r"sh(ow?)? int(e(r(f(a(c(es?)?)?)?)?)?)? (?P<name>.+)", lowered)
        ping = re.fullmatch(r"ping (\d+\.\d+\.\d+\.\d+)", lowered)
        if detail:
            interface = interface_name(device, detail["name"])
            text = show_interfaces(view, device, interface) if interface else INVALID
        elif re.fullmatch(r"sh(ow?)? log(g(i(ng?)?)?)?", lowered):
            # The lab consoles are in user EXEC: like the real routers, show logging needs enable.
            text = NOT_SIMULATED if privileged else INVALID
        elif ping:
            destination = ipaddress.IPv4Address(ping[1])
            result = network.ping(view.lab, device.name, destination, view.cache)
            text, timeouts = ping_text(destination, result), result.marks.count(".")
        elif lowered.startswith(("show ", "sh ", "ping ")):
            text = NOT_SIMULATED
        else:
            text = INVALID
    for pipe in pipes:
        filtered = _filter(text, pipe)
        if filtered is None:
            return INVALID, 0
        text = filtered
    return text, timeouts
