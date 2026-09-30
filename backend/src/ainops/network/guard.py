"""Command guard: the last check before a command is sent to a device. Fails closed.

Commands come only from commands.yaml with validated placeholders, so in normal operation this guard
never refuses anything. It exists for the day someone edits commands.yaml wrongly or a validation
bug lets a bad value through: then nothing that could change a device is ever sent.

A command is sent only if it
- is one line of printable text without shell-like characters,
- starts with a read-only prefix allowed for the platform,
- uses only pipes allowed for the platform,
- contains none of the forbidden words, anywhere.
"""

import re

from ainops.inventory import Platform


class CommandRefusedError(Exception):
    """The guard refused a command. The message names the reason (safe to show and log)."""


ALLOWED_PREFIXES: dict[Platform, tuple[str, ...]] = {
    "cisco_ios": ("show ", "ping "),
    "juniper_junos": ("show ", "ping "),
}
ALLOWED_PIPES: dict[Platform, tuple[str, ...]] = {
    "cisco_ios": ("include", "exclude", "section", "begin", "count"),
    "juniper_junos": ("display json", "match", "except", "count", "last", "no-more"),
}

# Words that could change a device, reveal secrets or leave the CLI. Matched as whole words.
_FORBIDDEN_WORDS = [
    "configure", "conf", "clear", "reload", "debug", "undebug", "write", "copy", "delete", "erase",
    "request", "restart", "commit", "rollback", "set", "edit", "shell", "start", "test", "redirect",
    "tee", "append", "save", "format", "shutdown", "no", "file", "run", "monitor", "traceoptions",
]  # fmt: skip
_FORBIDDEN = re.compile(r"\b(" + "|".join(_FORBIDDEN_WORDS) + r")\b", re.IGNORECASE)
_PRINTABLE = re.compile(r"^[\x20-\x7e]+$")
_SAFE_TOKENS = ("no-more", "no-resolve")


def check_command(command: str, platform: Platform) -> str:
    """Return the command if it may be sent, else raise CommandRefusedError."""
    if not _PRINTABLE.fullmatch(command) or command != command.strip():
        raise CommandRefusedError("command must be one line of printable text")
    if any(char in command for char in ">;`$&\\"):
        raise CommandRefusedError("command contains a forbidden character")

    base, *pipes = command.split("|")
    if not base.startswith(ALLOWED_PREFIXES[platform]):
        raise CommandRefusedError("command does not start with an allowed read-only prefix")
    for part in pipes:
        words = part.strip()
        allowed = ALLOWED_PIPES[platform]
        if not any(words == pipe or words.startswith(pipe + " ") for pipe in allowed):
            raise CommandRefusedError("command uses a pipe that is not allowed")

    # "no-more" and "no-resolve" are harmless Junos options, not the forbidden word "no".
    checked = base + " " + " ".join(part.strip() for part in pipes)
    for token in _SAFE_TOKENS:
        checked = re.sub(rf"(?<![\w-]){token}(?![\w-])", " ", checked)
    found = _FORBIDDEN.search(checked)
    if found:
        raise CommandRefusedError(f"command contains the forbidden word '{found.group(1).lower()}'")
    return command
