"""The simulated consoles: one telnet port per device, like EVE-NG's node consoles.

Netmiko (and a person with PuTTY or `telnet`) connects exactly as to the lab laptop:
- Cisco: a Dynamips greeting, RETURN gives the user EXEC prompt `NAME>` (no login, as in the lab);
  `enable` gives `NAME#` (no password, as in the lab).
- Junos: RETURN gives `login:`, then `Password:` (the .env login of the device's credential_ref).
  root lands in the shell (`root@NAME:~ # `) and `cli` starts the CLI (`root@NAME> `).
Typed characters are echoed (Netmiko waits for the echo of each command). Telnet option
negotiation from the client is read and ignored.

Only 127.0.0.1 by default: the simulator is for this laptop.
"""

import asyncio
import contextlib
import os
import time
from collections.abc import Callable
from dataclasses import dataclass

from labsim import cisco, junos
from labsim.model import Device
from labsim.state import Simulator

IAC, SB, SE = 255, 250, 240
Credentials = Callable[[str], tuple[str, str] | None]
Log = Callable[[str], None]


def env_credentials(credential_ref: str) -> tuple[str, str] | None:
    """The login AINOPS uses for this device (AINOPS_CRED_<REF>_USERNAME / _PASSWORD in .env)."""
    prefix = "AINOPS_CRED_" + credential_ref.upper().replace("-", "_")
    username = os.environ.get(prefix + "_USERNAME", "")
    return (username, os.environ.get(prefix + "_PASSWORD", "")) if username else None


class TelnetText:
    """Turns the client's bytes into text, dropping telnet commands (IAC ...)."""

    def __init__(self) -> None:
        self._pending = b""

    def feed(self, data: bytes) -> str:
        data = self._pending + data
        self._pending = b""
        out = bytearray()
        i = 0
        while i < len(data):
            byte = data[i]
            if byte != IAC:
                out.append(byte)
                i += 1
                continue
            if i + 1 >= len(data):
                self._pending = data[i:]
                break
            command = data[i + 1]
            if command == IAC:
                out.append(IAC)
                i += 2
            elif command == SB:
                end = data.find(bytes([IAC, SE]), i + 2)
                if end < 0:
                    self._pending = data[i:]
                    break
                i = end + 2
            elif command in (251, 252, 253, 254):  # WILL WONT DO DONT <option>
                if i + 2 >= len(data):
                    self._pending = data[i:]
                    break
                i += 3
            else:
                i += 2  # NOP, AYT ...
        return out.decode("latin-1")


@dataclass
class Session:
    """One telnet connection to one console."""

    state: str  # idle, login, password, shell, cli (Junos) / idle, exec (Cisco)
    privileged: bool = False
    username: str = ""


class Console:
    def __init__(
        self,
        simulator: Simulator,
        device: Device,
        *,
        speed: float = 1.0,
        credentials: Credentials = env_credentials,
        log: Log = print,
    ) -> None:
        self.simulator = simulator
        self.device = device
        self.speed = speed  # 1.0: about as slow as the real lab; 0: instant (tests)
        self.credentials = credentials
        self.log = log

    @property
    def junos(self) -> bool:
        return self.device.platform == "juniper_junos"

    # ---------- prompts ----------

    def prompt(self, session: Session) -> str:
        name = self.device.name
        if self.junos:
            if session.state == "shell":
                return f"{session.username}@{name}:~ # "
            return f"{session.username}@{name}> "
        return f"{name}{'#' if session.privileged else '>'}"

    def greeting(self) -> str:
        if self.junos:
            return ""
        node = (self.device.port or 32768) - 32768  # EVE-NG: console port = 32768 + node id
        return (
            f'Connected to Dynamips VM "{self.device.name}" (ID {node}, type c7200) - '
            "Console port\r\nPress ENTER to get the prompt.\r\n"
        )

    # ---------- one line ----------

    async def _pause(self, text: str, timeouts: int) -> None:
        delay = self.speed * (0.3 + len(text) / 8000 + 2 * timeouts)
        if delay > 0:
            await asyncio.sleep(delay)

    async def line(self, session: Session, typed: str) -> str:
        """What the console prints after the user pressed RETURN on `typed` (echo excluded)."""
        command = " ".join(typed.split())
        if self.junos:
            return await self._junos_line(session, command, typed)
        return await self._cisco_line(session, command)

    async def _cisco_line(self, session: Session, command: str) -> str:
        if session.state == "idle":
            session.state = "exec"
            return "\r\n" + self.prompt(session)
        lowered = command.lower()
        if not command:
            return "\r\n" + self.prompt(session)
        if lowered in ("en", "ena", "enable"):
            session.privileged = True
            return "\r\n" + self.prompt(session)
        if lowered in ("disable",):
            session.privileged = False
            return "\r\n" + self.prompt(session)
        if lowered in ("exit", "logout", "quit"):
            session.state, session.privileged = "idle", False
            return (
                f"\r\n\r\n\r\n{self.device.name} con0 is now available\r\n\r\n\r\n\r\n\r\n\r\n"
                "Press RETURN to get started.\r\n\r\n\r\n"
            )
        if lowered.startswith(("terminal length", "terminal width", "term len", "term width")):
            return "\r\n" + self.prompt(session)
        if lowered.startswith(("conf", "configure")):
            text = (
                "% labsim: typed configuration is not simulated yet (use `labsim fault`)"
                if session.privileged
                else cisco.INVALID
            )
            return "\r\n" + text.replace("\n", "\r\n") + "\r\n" + self.prompt(session)
        started = time.monotonic()
        view = self.simulator.view()
        # The device as it is now (with the faults), not the one this console was started with.
        device = view.lab.devices[self.device.name]
        text, timeouts = cisco.answer(view, device, command, session.privileged)
        await self._pause(text, timeouts)
        self.log(f"{self.device.name}: {command} ({int((time.monotonic() - started) * 1000)} ms)")
        body = text.replace("\n", "\r\n")
        return "\r\n" + (body + "\r\n" if body else "") + self.prompt(session)

    async def _junos_line(self, session: Session, command: str, typed: str) -> str:
        name = self.device.name
        if session.state == "idle":
            session.state = "login"
            return f"\r\n\r\n{name} (ttyu0)\r\n\r\nlogin: "
        if session.state == "login":
            if not command:
                return "\r\nlogin: "
            session.username, session.state = command, "password"
            return "\r\nPassword:"
        if session.state == "password":
            expected = self.credentials(self.device.credential_ref or "")
            if expected is None or (session.username, typed) != expected:
                session.state, session.username = "login", ""
                await asyncio.sleep(self.speed * 1.0)
                self.log(f"{name}: login failed")
                return "\r\nLogin incorrect\r\nlogin: "
            self.log(f"{name}: login ok")
            session.state = "shell" if session.username == "root" else "cli"
            banner = f"--- JUNOS {junos.VERSION} Kernel 64-bit  JNPR-12.1-20211116.0e9f8d2_buil"
            return f"\r\n\r\n{banner}\r\n" + self.prompt(session)
        if session.state == "shell":
            if command == "cli":
                session.state = "cli"
                return "\r\n" + self.prompt(session)
            if command in ("exit", "logout"):
                session.state, session.username = "login", ""
                return "\r\n\r\nlogin: "
            text = f"sh: {command.split()[0]}: not found" if command else ""
            return "\r\n" + (text + "\r\n" if text else "") + self.prompt(session)
        # cli
        if not command:
            return "\r\n" + self.prompt(session)
        if command in ("exit", "quit"):
            session.state = "shell" if session.username == "root" else "login"
            if session.state == "login":
                session.username = ""
                return "\r\n\r\nlogin: "
            return "\r\n" + self.prompt(session)
        if command.startswith(("configure", "edit")):
            text = "error: labsim: typed configuration is not simulated yet (use `labsim fault`)"
            return "\r\n" + text + "\r\n\r\n" + self.prompt(session)
        started = time.monotonic()
        view = self.simulator.view()
        text, timeouts = junos.answer(view, view.lab.devices[self.device.name], command)
        await self._pause(text, timeouts)
        if not command.startswith("set cli"):
            self.log(f"{name}: {command} ({int((time.monotonic() - started) * 1000)} ms)")
        return "\r\n" + text.replace("\n", "\r\n") + "\r\n\r\n" + self.prompt(session)

    # ---------- the connection ----------

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        session = Session(state="idle")
        decoder = TelnetText()
        typed = ""
        skip_lf = False
        writer.write(self.greeting().encode())
        try:
            while True:
                data = await reader.read(1024)
                if not data:
                    break
                for char in decoder.feed(data):
                    if skip_lf and char in "\n\x00":
                        skip_lf = False
                        continue
                    skip_lf = False
                    if char in "\r\n":
                        skip_lf = char == "\r"
                        reply = await self.line(session, typed)
                        typed = ""
                        writer.write(reply.encode("latin-1", errors="replace"))
                        await writer.drain()
                    elif char in "\x08\x7f":
                        if typed:
                            typed = typed[:-1]
                            writer.write(b"\x08 \x08")
                    elif char.isprintable():
                        typed += char
                        if session.state != "password":
                            writer.write(char.encode("latin-1", errors="replace"))
                await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()


async def start(
    simulator: Simulator,
    *,
    host: str = "127.0.0.1",
    speed: float = 1.0,
    credentials: Credentials = env_credentials,
    log: Log = print,
    ports: dict[str, int] | None = None,
) -> list[asyncio.Server]:
    """One telnet server per device console. `ports` overrides inventory ports (tests use 0)."""
    servers = []
    for device in simulator.base.consoles():
        console = Console(simulator, device, speed=speed, credentials=credentials, log=log)
        port = (ports or {}).get(device.name, device.port or 0)
        servers.append(await asyncio.start_server(console.handle, host, port))
    return servers
