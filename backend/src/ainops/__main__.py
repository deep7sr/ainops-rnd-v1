"""`uv run python -m ainops <command>`: the same as the `ainops` script.

On the lab laptop Smart App Control blocks the freshly built `ainops.exe` launcher, but allows the
python.org Python, so this form always works.
"""

from ainops.cli import main

main()
