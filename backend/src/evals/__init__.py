"""The evaluation set: questions to AINOPS on the simulated lab, scored by code.

    uv run python -m evals                 all cases (cases.yaml)
    uv run python -m evals --case NAME     one case (repeat --case for more)
    uv run python -m evals --repeat 3      each case three times (the AI's answers vary)
    uv run python -m evals --list          the cases

It needs the stack on the simulated lab (`scripts\\start-all.ps1 -Sim`) and an LLM that can
finish an investigation. It refuses to run on the live lab. It switches the simulator's faults
for each case and puts back the ones that were on, even when it fails. It runs the agent in its own
process: no case is drafted and no past case is offered as a hint, so runs are comparable.

AINOPS never imports this package (like labsim): it is test tooling around the product.
"""
