"""The evaluation cases (cases.yaml), read and checked before anything runs."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from ainops.agent.report import blamed

CASES_FILE = Path(__file__).with_name("cases.yaml")
Outcome = Literal["diagnosed", "no_fault_found", "refused"]
OUTCOMES = ("diagnosed", "no_fault_found", "refused")


class CaseError(ValueError):
    """cases.yaml is wrong: the message says which case and what."""


@dataclass(frozen=True)
class Expect:
    outcome: Outcome
    blame: tuple[str, ...] = ()
    forbid: tuple[str, ...] = ()
    max_checks: int | None = None


@dataclass(frozen=True)
class Case:
    name: str
    question: str
    expect: Expect
    faults: tuple[str, ...] = ()
    try_skill: str | None = None


def _expect(name: str, raw: dict[str, Any], devices: set[str]) -> Expect:
    outcome = raw.get("outcome")
    if outcome not in OUTCOMES:
        raise CaseError(f"{name}: expect.outcome must be one of {', '.join(OUTCOMES)}")
    blame = tuple(str(b) for b in raw.get("blame", []))
    if outcome == "diagnosed" and not blame:
        raise CaseError(f"{name}: a diagnosed case needs expect.blame")
    if outcome != "diagnosed" and blame:
        raise CaseError(f"{name}: only a diagnosed case blames something")
    for item in blame:
        device, _ = blamed(item)
        if device not in devices:
            raise CaseError(f"{name}: blames '{item}', but {device or '(nothing)'} is no device")
    forbid = tuple(str(p) for p in raw.get("forbid", []))
    for pattern in forbid:
        try:
            re.compile(pattern)
        except re.error as error:
            raise CaseError(f"{name}: forbid pattern {pattern!r}: {error}") from error
    max_checks = raw.get("max_checks")
    return Expect(outcome, blame, forbid, None if max_checks is None else int(max_checks))


def load_cases(devices: set[str], faults: set[str], path: Path = CASES_FILE) -> list[Case]:
    """`devices` and `faults`: the names that exist (inventory, simulator), to catch typos."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cases: list[Case] = []
    for entry in raw.get("cases", []):
        name = str(entry.get("name") or "")
        if not name or any(c.name == name for c in cases):
            raise CaseError(f"case names must be given and unique: {name!r}")
        unknown = [f for f in entry.get("faults", []) if f not in faults]
        if unknown:
            raise CaseError(f"{name}: no simulator fault named {', '.join(unknown)}")
        if not str(entry.get("question") or "").strip():
            raise CaseError(f"{name}: no question")
        cases.append(
            Case(
                name=name,
                question=str(entry["question"]).strip(),
                expect=_expect(name, entry.get("expect") or {}, devices),
                faults=tuple(entry.get("faults", [])),
                try_skill=entry.get("try_skill"),
            )
        )
    return cases
