"""Writing expert skills from the Skills page: new skills, edits, and the versions they replace.

A skill is still a skills/<name>/SKILL.md file in the Agent Skills format (agent/skills.py); the
page writes the same file a person would. Rules:
- the form is turned into SKILL.md and read back with the loader's own checks: a skill that would
  be left out (bad name, unknown tool, too many steps...) is never saved, and neither is one that
  does not read back exactly as written;
- tool names must be checked against the running MCP servers, so nothing is saved while they are
  down;
- an edit is refused when the file changed since the engineer opened it (`version`): one save
  wins, nobody overwrites another's work without seeing it;
- every edit (and every restore of an earlier version) sets the skill back to a draft that is not
  reviewed: a changed procedure needs a new review before AINOPS uses it again;
- only a reviewed skill can go live (and only live skills are offered to the agent);
- the version an edit replaces is kept in skills/<name>/history/ (not in git; git keeps the
  committed history), and every file is written whole or not at all.
A skill only names read-only tools; it cannot run anything.
"""

import hashlib
import os
import re
import tempfile
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from ainops.agent.skills import _NAME, _STEP, Skill, parse_skill

HISTORY = "history"
_STAMP = re.compile(r"^\d{8}T\d{12}Z$")  # a history entry's id: when it was replaced
_LOCK = threading.Lock()  # one save at a time


class SkillError(Exception):
    """A save the skills folder cannot take; the message says why (shown to the engineer)."""


class SkillConflict(SkillError):
    """The skill changed (or appeared) since the engineer opened it."""


class SkillForm(BaseModel):
    """What the page's form holds. Limits stop absurd input before any check runs."""

    name: str = Field(max_length=64)
    description: str = Field(max_length=1000)
    intro: str = Field(default="", max_length=2000)
    steps: list[str] = Field(max_length=30)
    # Each step at most 2,000 characters (checked in `normalised`).


class SkillSave(BaseModel):
    skill: SkillForm
    by: str = Field(min_length=1, max_length=80)
    version: str | None = None  # the version the engineer opened; None for a new skill


class HistoryEntry(BaseModel):
    id: str  # when this version was replaced (also its file name)
    replaced_at: str
    saved_by: str  # who saved this version ("" for a file written by hand)
    saved_at: str
    reviewed_by: str


def version_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _one_line(text: str) -> str:
    return " ".join(text.split())


def normalised(form: SkillForm) -> SkillForm:
    """The form as SKILL.md will hold it: one line per sentence, sub-points ("- ") on their own
    lines, blank lines and empty steps dropped."""
    steps = []
    for step in form.steps:
        if len(step) > 2000:
            raise SkillError("a step is longer than 2,000 characters")
        lines: list[str] = []
        for raw in step.splitlines():
            text = _one_line(raw)
            if not text:
                continue
            if lines and text.startswith(("- ", "* ")):
                lines.append("- " + text[2:].strip())
            elif lines:
                lines[-1] += f" {text}"
            else:
                lines.append(text)
        if lines:
            steps.append("\n".join(lines))
    return SkillForm(
        name=form.name.strip().lower(),
        description=_one_line(form.description),
        intro=_one_line(form.intro),
        steps=steps,
    )


def render(form: SkillForm, metadata: dict[str, str]) -> str:
    """The SKILL.md text for a normalised form."""
    front = yaml.safe_dump(
        {"name": form.name, "description": form.description, "metadata": metadata},
        sort_keys=False,
        allow_unicode=True,
        width=10_000,
    )
    body = [f"{form.intro}\n"] if form.intro else []
    for number, step in enumerate(form.steps, start=1):
        first, *subpoints = step.split("\n")
        body.append(f"{number}. {first}")
        body += [f"   {line}" for line in subpoints]
    return f"---\n{front}---\n" + "\n".join(body) + "\n"


def check(
    form: SkillForm, known_tools: set[str] | None, metadata: dict[str, str] | None = None
) -> tuple[Skill | None, list[str], str]:
    """The skill as it would be saved, its problems, and its SKILL.md text."""
    try:
        clean = normalised(form)
    except SkillError as error:
        return None, [str(error)], ""
    text = render(clean, metadata or {"author": "", "reviewed_by": ""})
    problem = _name_problem(clean.name)
    if problem:
        return None, [problem], text
    if _STEP.match(clean.intro):
        return (
            None,
            ["the intro cannot start with a number and a dot: it would read as a step"],
            text,
        )
    skill, problems = parse_skill(clean.name, text, known_tools)
    if skill is not None and (
        skill.description != clean.description
        or skill.intro != clean.intro
        or skill.steps != clean.steps
    ):
        # e.g. an intro that starts with "1." would be read back as a step
        return None, ["the intro or a step would not read back as written: reword its start"], text
    return skill, problems, text


def _name_problem(name: str) -> str | None:
    if _NAME.fullmatch(name) and len(name) <= 64:
        return None
    return f"name '{name}' must be lowercase letters, digits and hyphens (at most 64 characters)"


def _folder(base: Path, name: str) -> Path:
    """The skill's folder, only for a valid name (never a path outside the skills folder)."""
    problem = _name_problem(name)
    if problem:
        raise SkillError(problem)
    return base / name


def read(base: Path, name: str) -> tuple[str, str] | None:
    """The SKILL.md text and its version, or None when there is no such skill."""
    file = _folder(base, name) / "SKILL.md"
    if not file.is_file():
        return None
    text = file.read_text(encoding="utf-8")
    return text, version_of(text)


def _write_atomically(path: Path, text: str) -> None:
    """Write the whole file or nothing (a crash never leaves half a file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp = tempfile.mkstemp(dir=path.parent, prefix=".skill-", suffix=".tmp")
    with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as file:
        file.write(text)
    os.replace(temp, path)


def _stamp(now: datetime) -> str:
    return now.strftime("%Y%m%dT%H%M%S%fZ")


def _metadata(text: str) -> dict[str, str]:
    """The metadata block of a SKILL.md text (empty when it cannot be read)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    for end in range(1, len(lines)):
        if lines[end].strip() == "---":
            try:
                meta = yaml.safe_load("\n".join(lines[1:end])) or {}
            except yaml.YAMLError:
                return {}
            extra = meta.get("metadata") if isinstance(meta, dict) else None
            return (
                {str(k): str(v or "") for k, v in extra.items()} if isinstance(extra, dict) else {}
            )
    return {}


def save(
    base: Path,
    request: SkillSave,
    known_tools: set[str] | None,
    now: datetime | None = None,
) -> tuple[Skill, str, bool]:
    """Create or edit a skill. Returns the saved skill, its new version, and whether it is new."""
    if known_tools is None:
        raise SkillError(
            "the MCP servers are not running, so the tool names cannot be checked: start them "
            "and save again"
        )
    now = now or datetime.now(UTC)
    by = _one_line(request.by)
    if not by:
        raise SkillError("say who you are: your name is kept with the skill")
    name = request.skill.name.strip().lower()
    folder = _folder(base, name)
    file = folder / "SKILL.md"
    with _LOCK:
        current = file.read_text(encoding="utf-8") if file.is_file() else None
        if request.version is None and folder.exists():
            raise SkillConflict(f"there is already a skill named '{name}'")
        if request.version is not None:
            _same_version(name, current, request.version)
        earlier = _metadata(current) if current is not None else {}
        metadata = {
            "author": earlier.get("author") or by,
            "reviewed_by": "",  # a changed procedure needs a new review...
            "reviewed_at": "",
            "status": "draft",  # ...and is not used by AINOPS until it is live again
            "updated_by": by,
            "updated_at": now.isoformat(timespec="seconds"),
        }
        skill, problems, text = check(request.skill, known_tools, metadata)
        if skill is None or problems:
            raise SkillError("; ".join(problems) or "the skill could not be read back")
        if current is not None:
            _write_atomically(folder / HISTORY / f"{_stamp(now)}.md", current)
        _write_atomically(file, text)
    return skill, version_of(text), current is None


def _same_version(name: str, current: str | None, version: str) -> str:
    """The current text, if it is still the version the engineer opened."""
    if current is None:
        raise SkillConflict(f"there is no skill named '{name}' any more")
    if version_of(current) != version:
        raise SkillConflict(
            f"'{name}' was changed by someone else after you opened it: reload it, then make "
            "your change again"
        )
    return current


def _set_metadata(
    base: Path, name: str, version: str, change: Callable[[Skill, dict[str, str]], dict[str, str]]
) -> tuple[Skill, str]:
    """Change only the metadata block (review, status): the procedure itself stays as it is, so
    no earlier version is kept for it."""
    file = _folder(base, name) / "SKILL.md"
    with _LOCK:
        current = _same_version(
            name, file.read_text(encoding="utf-8") if file.is_file() else None, version
        )
        skill, problems = parse_skill(name, current, None)  # its tools were checked when saved
        if skill is None:
            raise SkillError("the skill needs fixing in its file first: " + "; ".join(problems))
        metadata = change(skill, _metadata(current))
        form = SkillForm(
            name=skill.name, description=skill.description, intro=skill.intro, steps=skill.steps
        )
        changed, problems, text = check(form, None, metadata)
        if changed is None or problems:
            raise SkillError("; ".join(problems) or "the skill could not be read back")
        _write_atomically(file, text)
    return changed, version_of(text)


def review(
    base: Path, name: str, reviewer: str, version: str, now: datetime | None = None
) -> tuple[Skill, str]:
    """An engineer has checked the procedure. It stays in its status (a draft can then go live)."""
    by = _one_line(reviewer)
    if not by:
        raise SkillError("say who reviewed it: type your name")
    at = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    return _set_metadata(
        base, name, version, lambda _, meta: {**meta, "reviewed_by": by, "reviewed_at": at}
    )


def set_status(base: Path, name: str, status: str, version: str) -> tuple[Skill, str]:
    """Live: AINOPS uses it. Draft or off: it does not (a draft can still be tried). Any other
    value is refused when the file is read back (the loader's rule)."""

    def change(skill: Skill, meta: dict[str, str]) -> dict[str, str]:
        if status == "live" and not skill.reviewed_by.strip():
            raise SkillError(f"'{name}' has not been reviewed: review it before it goes live")
        return {**meta, "status": status}

    return _set_metadata(base, name, version, change)


def restore(
    base: Path,
    name: str,
    entry: str,
    by: str,
    version: str,
    known_tools: set[str] | None,
    now: datetime | None = None,
) -> tuple[Skill, str]:
    """Bring back an earlier version: saved like an edit (the current one is kept, and the skill
    needs a new review before it is live again)."""
    old, problems = parse_skill(name, old_version(base, name, entry), known_tools)
    if old is None:
        raise SkillError("this version cannot be used any more: " + "; ".join(problems))
    form = SkillForm(name=name, description=old.description, intro=old.intro, steps=old.steps)
    skill, new_version, _ = save(
        base, SkillSave(skill=form, by=by, version=version), known_tools, now
    )
    return skill, new_version


def history(base: Path, name: str) -> list[HistoryEntry]:
    """The versions an edit replaced, latest first."""
    folder = _folder(base, name) / HISTORY
    if not folder.is_dir():
        return []
    entries = []
    for path in sorted(folder.glob("*.md"), reverse=True):
        if not _STAMP.fullmatch(path.stem):
            continue
        meta = _metadata(path.read_text(encoding="utf-8"))
        replaced = datetime.strptime(path.stem, "%Y%m%dT%H%M%S%fZ").replace(tzinfo=UTC)
        entries.append(
            HistoryEntry(
                id=path.stem,
                replaced_at=replaced.isoformat(timespec="seconds"),
                saved_by=meta.get("updated_by", ""),
                saved_at=meta.get("updated_at", ""),
                reviewed_by=meta.get("reviewed_by", ""),
            )
        )
    return entries


def old_version(base: Path, name: str, entry: str) -> str:
    """The SKILL.md text of a replaced version."""
    if not _STAMP.fullmatch(entry):
        raise SkillError(f"'{entry}' is not a version of '{name}'")
    path = _folder(base, name) / HISTORY / f"{entry}.md"
    if not path.is_file():
        raise SkillError(f"'{entry}' is not a version of '{name}'")
    return path.read_text(encoding="utf-8")
