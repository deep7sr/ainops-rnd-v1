"""Expert skills: step-by-step procedures for frequent questions, written by network engineers.

One folder per skill, in the Agent Skills format (skills/<name>/SKILL.md):

    ---
    name: site-to-site-unreachable          # same as the folder
    description: Use when users at one site cannot reach a host at the other site.
    metadata:
      author: Praveen
      reviewed_by: Praveen                  # empty = not reviewed yet
      status: live                          # draft (default), live or off
    ---
    Optional intro text.

    1. `trace_route` from the source LAN to the destination. A long step
       can go on over indented lines.
       - an indented line starting with "- " is a sub-point of the step
    2. ...

The agent always sees only each skill's name and description. It opens a skill with use_skill
when the question fits, then follows the steps and tags each tool call with the step it does.

Only LIVE skills are offered to the agent. A draft is offered only to an investigation that was
started to try it ("Try this skill"); a skill that is off is never offered. Only a reviewed skill
can be live.

Rules, checked by code when the skills are loaded. A skill that breaks one is left out and its
problems are listed (Skills page), so one typo never stops the agent:
- name: lowercase letters, digits and hyphens, at most 64 characters, the same as the folder;
- description: required, at most 300 characters;
- numbered steps 1, 2, 3... (at least 1, at most MAX_STEPS); text after a step is indented;
- `backticks` hold only tool names, and every tool named must exist;
- status: draft, live or off; live needs reviewed_by.
A skill cannot run anything: the agent still only calls the read-only tools.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, get_args

import yaml
from pydantic import BaseModel

MAX_STEPS = 12
MAX_DESCRIPTION = 300
_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_STEP = re.compile(r"^(\d+)\.\s+(\S.*)$")
_TICKED = re.compile(r"`([^`]*)`")

Status = Literal["draft", "live", "off"]
STATUSES: tuple[str, ...] = get_args(Status)


class Skill(BaseModel):
    name: str
    description: str
    intro: str
    steps: list[str]
    tools: list[str]  # the tools the steps name, in order
    author: str
    reviewed_by: str  # empty while the skill is a draft
    path: str  # relative to the skills folder
    updated_by: str = ""  # who saved it last on the Skills page (empty: written by hand)
    updated_at: str = ""
    status: Status = "draft"  # only live skills are offered to the agent
    reviewed_at: str = ""


class SkillProblem(BaseModel):
    folder: str
    problems: list[str]


@dataclass
class SkillLibrary:
    skills: dict[str, Skill] = field(default_factory=dict)
    problems: list[SkillProblem] = field(default_factory=list)
    tools_checked: bool = True  # False when the tool list was not available to check against
    trying: str | None = None  # the skill an engineer started this investigation to try

    def get(self, name: str) -> Skill | None:
        return self.skills.get(name.strip().lower())

    def for_agent(self, trying: str | None = None) -> "SkillLibrary":
        """The skills one investigation may use: the live ones, and the one being tried (whatever
        its status). A skill that is not offered cannot be opened either."""
        tried = self.get(trying) if trying else None
        offered = {
            name: skill
            for name, skill in self.skills.items()
            if skill.status == "live" or (tried is not None and name == tried.name)
        }
        return SkillLibrary(
            skills=offered,
            tools_checked=self.tools_checked,
            trying=tried.name if tried else None,
        )

    def prompt_section(self) -> str:
        """Added to the agent's instructions: the list of skills, never their steps."""
        if not self.skills:
            return ""
        lines = [
            "",
            "Expert skills: step-by-step procedures written by the network engineers. If one fits",
            "the question, call use_skill with its name BEFORE any other tool, follow its steps in",
            "order and give every tool call the skill_step it carries out. Go beyond the steps",
            "(skill_step 0) only when they do not explain the problem, and say why in `reason`.",
        ]
        lines += [f"- {s.name}: {s.description}" for s in self.skills.values()]
        if self.trying:
            lines.append(
                f"The engineer started this investigation to try the skill {self.trying}: open it "
                "with use_skill first and follow it, unless the question has nothing to do with it."
            )
        return "\n".join(lines) + "\n"


def step_tools(skill: Skill) -> list[set[str]]:
    """The tools each step names (index 0 = step 1)."""
    return [
        {name.strip() for name in _TICKED.findall(step) if name.strip() in skill.tools}
        for step in skill.steps
    ]


def instructions(skill: Skill) -> str:
    """What use_skill returns to the agent."""
    steps = "\n".join(f"{n}. {text}" for n, text in enumerate(skill.steps, start=1))
    intro = f"{skill.intro}\n\n" if skill.intro else ""
    return (
        f"Skill {skill.name}. Follow these steps in order; skill_step = the step number.\n\n"
        f"{intro}{steps}"
    )


def _front_matter(text: str) -> tuple[dict[str, Any], str, list[str]]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text, ["SKILL.md must start with a --- block (name, description)"]
    for end in range(1, len(lines)):
        if lines[end].strip() == "---":
            try:
                meta = yaml.safe_load("\n".join(lines[1:end])) or {}
            except yaml.YAMLError as error:
                return {}, "", [f"the --- block is not valid YAML: {error}"]
            if not isinstance(meta, dict):
                return {}, "", ["the --- block must hold name: and description: lines"]
            return meta, "\n".join(lines[end + 1 :]), []
    return {}, "", ["the --- block is not closed with a second --- line"]


def _steps(body: str) -> tuple[str, list[str], list[str]]:
    intro: list[str] = []
    steps: list[list[str]] = []
    problems: list[str] = []
    for line in body.splitlines():
        if not line.strip():
            continue
        match = _STEP.match(line)
        if match:
            number = int(match.group(1))
            if number != len(steps) + 1:
                problems.append(f"step {number} should be numbered {len(steps) + 1}")
            steps.append([match.group(2).strip()])
        elif steps and line[0].isspace():
            text = line.strip()
            if text.startswith(("- ", "* ")):
                steps[-1].append(text)  # a sub-point: its own line
            else:
                steps[-1][-1] += f" {text}"  # the sentence goes on (wrapped line)
        elif steps:
            problems.append(
                f"'{line.strip()[:40]}' comes after step {len(steps)}: indent it to make it part "
                "of that step"
            )
        else:
            intro.append(line.strip())
    return " ".join(intro), ["\n".join(parts) for parts in steps], problems


def parse_skill(
    folder: str, text: str, known_tools: set[str] | None
) -> tuple[Skill | None, list[str]]:
    meta, body, problems = _front_matter(text)
    if problems:
        return None, problems
    name = str(meta.get("name") or "").strip()
    description = " ".join(str(meta.get("description") or "").split())
    raw_extra = meta.get("metadata")
    extra: dict[str, Any] = raw_extra if isinstance(raw_extra, dict) else {}

    if not _NAME.fullmatch(name) or len(name) > 64:
        problems.append(
            f"name '{name}' must be lowercase letters, digits and hyphens (at most 64 characters)"
        )
    elif name != folder:
        problems.append(f"name '{name}' must be the same as its folder '{folder}'")
    if not description:
        problems.append("description is missing: say when the skill should be used")
    elif len(description) > MAX_DESCRIPTION:
        problems.append(f"description is longer than {MAX_DESCRIPTION} characters")

    intro, steps, step_problems = _steps(body)
    problems += step_problems
    if not steps:
        problems.append("no numbered steps (1. ..., 2. ...)")
    elif len(steps) > MAX_STEPS:
        problems.append(f"{len(steps)} steps: at most {MAX_STEPS}; split it into two skills")

    tools: list[str] = []
    not_tools: list[str] = []
    for ticked in _TICKED.findall(body):
        token = ticked.strip()
        known = known_tools is None or token in known_tools
        if not re.fullmatch(r"[a-z][a-z0-9_]*", token) or not known:
            if token not in not_tools:
                not_tools.append(token)
        elif token not in tools:
            tools.append(token)
    problems += [
        f"`{token}` is not a tool: backticks are only for tool names (see the MCP tools page)"
        for token in not_tools
    ]

    raw_status = extra.get("status")
    # YAML reads an unquoted `off` as false (and `on`/`yes` as true): take them as written.
    if isinstance(raw_status, bool):
        status = "off" if raw_status is False else "on"
    else:
        status = str(raw_status or "draft").strip().lower()
    reviewed_by = str(extra.get("reviewed_by") or "")
    if status not in STATUSES:
        problems.append(f"status '{status}' must be draft, live or off")
    elif status == "live" and not reviewed_by.strip():
        problems.append("status is live but nobody reviewed it: a live skill needs reviewed_by")

    if problems:
        return None, problems
    return (
        Skill(
            name=name,
            description=description,
            intro=intro,
            steps=steps,
            tools=tools,
            author=str(extra.get("author") or ""),
            reviewed_by=reviewed_by,
            path=f"{folder}/SKILL.md",
            updated_by=str(extra.get("updated_by") or ""),
            updated_at=str(extra.get("updated_at") or ""),
            status=status,  # type: ignore[arg-type]  # one of STATUSES (checked above)
            reviewed_at=str(extra.get("reviewed_at") or ""),
        ),
        [],
    )


def load_skills(directory: Path, known_tools: Iterable[str] | None) -> SkillLibrary:
    """Every valid skill in `directory`; the invalid ones are listed with their problems."""
    tools = set(known_tools) if known_tools is not None else None
    library = SkillLibrary(tools_checked=tools is not None)
    if not directory.is_dir():
        return library
    for folder in sorted(p for p in directory.iterdir() if p.is_dir()):
        file = folder / "SKILL.md"
        if not file.is_file():
            continue
        skill, problems = parse_skill(folder.name, file.read_text(encoding="utf-8"), tools)
        if skill is None:
            library.problems.append(SkillProblem(folder=folder.name, problems=problems))
        else:
            library.skills[skill.name] = skill
    return library
