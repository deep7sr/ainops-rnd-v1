# Expert skills

A skill is the procedure an experienced network engineer follows for a frequent question, written
down so the AINOPS agent follows it too. The agent always sees each skill's name and description;
when a question fits, it opens the skill, follows the steps in order and tags every check with the
step it carries out. The Investigate page shows which skill and which step.

## Writing one

Make a folder named like the skill, with a `SKILL.md` file inside:

```markdown
---
name: interface-flapping
description: Use when an interface goes up and down, or users report short drops on one link.
metadata:
  author: Praveen
  reviewed_by: ""
---
Optional intro: what the skill is about, what "healthy" looks like.

1. `get_interface_detail` on the interface: how often it flapped, input errors and
   CRC. A step can go on over lines that start with spaces.
   - A line starting with spaces and "- " is a sub-point of the step.
2. `get_logs` on the device: when the flaps happened.
```

Rules (checked when skills are loaded; a skill that breaks one is not used, and the Skills page
says what to fix):

- **name**: lowercase letters, digits and hyphens, the same as the folder name.
- **description**: say *when* to use the skill (at most 300 characters). The agent picks skills by
  reading it, so be specific.
- **steps**: numbered 1, 2, 3..., at most 12.
- **backticks** are only for tool names, and the tool must exist (see the MCP tools page). A skill
  cannot contain device commands and cannot run anything: the agent still only calls the
  read-only tools.
- **reviewed_by** stays empty while the skill is a draft; the reviewer fills in their name.
