"""The command guard: nothing that could change a device may ever pass."""

import pytest

from ainops.network.guard import CommandRefusedError, check_command
from ainops.network.service import load_commands


@pytest.mark.parametrize(
    ("command", "platform"),
    [
        ("show ip interface", "cisco_ios"),
        ("show ip route", "cisco_ios"),
        ("ping 10.10.4.1", "cisco_ios"),
        ("show ip interface | include Internet", "cisco_ios"),
        ("show interfaces terse | display json", "juniper_junos"),
        ("show arp no-resolve | display json", "juniper_junos"),
        ("show log messages | last 40", "juniper_junos"),
        ("show configuration | display json | no-more", "juniper_junos"),
        ("ping 10.10.6.1 count 5 rapid", "juniper_junos"),
    ],
)
def test_read_only_commands_pass(command: str, platform: str) -> None:
    assert check_command(command, platform) == command  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("command", "reason"),
    [
        ("configure terminal", "prefix"),
        ("conf t", "prefix"),
        ("reload", "prefix"),
        ("clear ip ospf process", "prefix"),
        ("write memory", "prefix"),
        ("copy running-config tftp:", "prefix"),
        ("debug ip ospf adj", "prefix"),
        ("show running-config | redirect flash:x", "pipe"),
        ("show ip route | tee flash:x", "pipe"),
        ("show ip route | append flash:x", "pipe"),
        ("show ip route ; reload", "character"),
        ("show ip route > flash:x", "character"),
        ("show ip route `reload`", "character"),
        ("show ip route\nreload", "printable"),
        (" show ip route", "printable"),
        ("show ip route ", "printable"),
        ("show debug", "forbidden"),
        ("show ip route no", "forbidden"),
        ("ping 10.10.4.1 shutdown", "forbidden"),
        ("SHOW IP ROUTE | INCLUDE X", "prefix"),
    ],
)
def test_dangerous_cisco_commands_are_refused(command: str, reason: str) -> None:
    with pytest.raises(CommandRefusedError):
        check_command(command, "cisco_ios")


@pytest.mark.parametrize(
    "command",
    [
        "request system reboot",
        "set interfaces ge-0/0/0 disable",
        "edit",
        "configure",
        "start shell",
        "file delete /var/log/messages",
        "show log messages | save /tmp/x",
        "show configuration | display set | no-more",  # "set" hides in the pipe
        "show interfaces | no-more | request system reboot",
        "show interfaces terse | display json | no-more-x",
        "monitor traffic interface ge-0/0/0",
        "test policy",
        "show system commit",
        "show interfaces $(reboot)",
        "show route | match x & reboot",
    ],
)
def test_dangerous_junos_commands_are_refused(command: str) -> None:
    with pytest.raises(CommandRefusedError):
        check_command(command, "juniper_junos")


@pytest.mark.parametrize(
    ("command", "platform"),
    [
        # Not read-only prefixes, and no forbidden word: only the prefix check stops these.
        ("telnet 10.10.4.1", "cisco_ios"),
        ("enable", "cisco_ios"),
        ("traceroute 10.10.4.1", "cisco_ios"),
        ("exit", "juniper_junos"),
        ("ssh 10.10.6.2", "juniper_junos"),
    ],
)
def test_prefix_check_alone_refuses_other_commands(command: str, platform: str) -> None:
    with pytest.raises(CommandRefusedError, match="prefix"):
        check_command(command, platform)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("command", "platform"),
    [
        # Pipes that exist but are not allowed, without a forbidden word: only the pipe check.
        ("show ip route | display json", "cisco_ios"),
        ("show ip route | exclude-x", "cisco_ios"),
        ("show route | resolve", "juniper_junos"),
        ("show route | display xml", "juniper_junos"),
    ],
)
def test_pipe_check_alone_refuses_other_pipes(command: str, platform: str) -> None:
    with pytest.raises(CommandRefusedError, match="pipe"):
        check_command(command, platform)  # type: ignore[arg-type]


def test_safe_token_must_be_the_whole_word() -> None:
    # "no-resolvex" is not the safe option "no-resolve": the forbidden "no" must still be seen.
    with pytest.raises(CommandRefusedError, match="forbidden word 'no'"):
        check_command("show arp no-resolvex", "juniper_junos")


def test_no_more_only_counts_as_safe_when_it_is_the_whole_token() -> None:
    # "no-more" is removed before the forbidden-word check, but "no" alone must still be caught.
    with pytest.raises(CommandRefusedError):
        check_command("show interfaces | no-more no", "juniper_junos")


def test_every_command_in_commands_yaml_passes_the_guard() -> None:
    """A wrong edit of commands.yaml is caught here, not on a device."""
    samples = {"interface": "Fa2/0", "destination": "10.10.4.1"}
    for platform, commands in load_commands().items():
        for key, template in commands.items():
            rendered = template.format(**samples)
            assert check_command(rendered, platform) == rendered, (platform, key)  # type: ignore[arg-type]
