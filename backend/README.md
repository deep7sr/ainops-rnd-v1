# AINOPS backend (agentic design)

Python package `ainops`: the MCP servers that give an AI agent read-only access to the lab, the
knowledge graph, and the agent service. Everything runs with [uv](https://docs.astral.sh/uv/) from
this folder.

On the lab laptop, always start commands as `uv run python -m ainops ...`: Smart App Control blocks
the freshly built `ainops.exe` launcher but allows the python.org Python.

## Set up a new machine

Everything installs per user, without admin rights. Needs the python.org Python 3.12 and Node 24.
On the UST network the Zscaler proxy blocks `.ps1` installers and GitHub release downloads, and
replaces HTTPS certificates with its own, so:

1. **uv** from PyPI, in the 0.12 series (the build backend is pinned `<0.13`):
   `python -m pip install --user "uv<0.13"`. Put `%APPDATA%\Python\Python312\Scripts` and
   `%USERPROFILE%\.local\bin` on the user PATH, and set the user variable `UV_SYSTEM_CERTS=1`
   (uv then trusts the Windows certificate store, which has the proxy's certificate). Restart
   VS Code afterwards.
2. `cd backend; uv sync --locked` and `cd frontend; npm ci`: exact versions from the lockfiles.
3. **AI calls through the proxy**: Python (httpx, so the LLM client) does not use the Windows
   store and fails with `CERTIFICATE_VERIFY_FAILED`. Make a bundle of certifi's list plus the
   proxy's roots, outside the repo, and point the user variable `SSL_CERT_FILE` at it:
   ```powershell
   $dir = "$env:LOCALAPPDATA\Programs\certs"; New-Item -ItemType Directory -Force $dir | Out-Null
   $text = [IO.File]::ReadAllText((backend\.venv\Scripts\python -c "import certifi; print(certifi.where())"))
   foreach ($c in Get-ChildItem Cert:\LocalMachine\Root | ? Subject -match 'Zscaler' | Sort-Object Thumbprint -Unique) {
       $b64 = [Convert]::ToBase64String($c.RawData) -replace '(.{64})', "`$1`n"
       $text += "`n-----BEGIN CERTIFICATE-----`n$($b64.TrimEnd())`n-----END CERTIFICATE-----`n" }
   [IO.File]::WriteAllText("$dir\ca-bundle.pem", $text)
   [Environment]::SetEnvironmentVariable("SSL_CERT_FILE", "$dir\ca-bundle.pem", "User")
   ```
   uv, git, curl and npm keep working with it set (checked 2026-10-21). It is a copy: run it
   again when certifi is updated or the proxy's certificate changes. Restart VS Code afterwards.
4. **Java 21 and Neo4j Community 2026.09.0**: unzip both into `%LOCALAPPDATA%\Programs` (that is
   where `scripts/start-neo4j.ps1` looks). Downloads, with the published SHA-256 next to each:
   `https://aka.ms/download-jdk/microsoft-jdk-21-windows-x64.zip` and
   `https://dist.neo4j.org/neo4j-community-2026.09.0-windows.zip`.
5. Put `NEO4J_PASSWORD=...` in the repo-root `.env` (in the editor), then, before the first start,
   `neo4j-admin dbms set-initial-password` with that value (from a script that reads `.env`, so
   the password is never typed into a terminal or shown).
6. Restore a graph (optional): `neo4j-admin database load neo4j --from-path=<folder with
   neo4j.dump> --overwrite-destination=true` while Neo4j is stopped.
7. Commit checks: `uv tool install pre-commit`, then `pre-commit install` in the repo root.
   The gitleaks hook needs `gitleaks.exe` on the PATH (`%LOCALAPPDATA%\Programs\gitleaks`); check
   any copy against the release's `checksums.txt` before using it.
8. Run the checks below and the frontend's `npx vitest run && npx tsc -b && npx eslint src`.

## Simulated lab (labsim)

For when the EVE-NG lab is not available: `src/labsim` opens one telnet console per lab device on
this laptop, on the same ports as EVE-NG, so AINOPS reaches it exactly as it reaches the real lab
(Netmiko, logins, the same commands). The answers are worked out from a model of the lab
(`src/labsim/lab.yaml`, rebuilt from the live recordings in `fixtures/`) and the faults applied to
it: interfaces, CDP, OSPF neighbours (FULL only with matching subnet and area, not passive),
routing tables by shortest path with the real costs, ARP, and pings hop by hop there and back.

```
powershell -ExecutionPolicy Bypass -File ..\scripts\start-all.ps1 -Sim   # everything, simulated
uv run python -m labsim                   # or only the simulator (127.0.0.1, inventory ports)
uv run python -m labsim faults            # the faults, and which are on
uv run python -m labsim fault fault-1     # apply one (the running simulator picks it up)
uv run python -m labsim heal              # remove them all (or: heal fault-1)
```

`-Sim` sets `LAB_EVE_HOST=127.0.0.1` and `LAB_SIMULATED=true` for every window (no `.env` change);
the UI header then says "Lab · simulated devices". Faults are named changes in `lab.yaml` (shut,
wrong address, OSPF passive, network not announced); add one there, no code needed.

What it is not:
- **Not the lab.** Results from it are never shown as real ones (badge), and a diagnosis checked on
  it still has to be checked on the real lab before a demo.
- **Faithful where it was checked:** for every live recording, the simulator's answer parses to
  the same result with AINOPS's own parsers (`tests/test_labsim_fidelity.py`). That covers the
  Cisco outputs and Junos routes, interfaces and zones. Junos version, interface detail, ARP,
  OSPF/LLDP neighbours, logs and policies follow Juniper's documented format and are NOT yet
  checked against our lab.
- **Not simulated:** typed configuration (`conf t`, `no shutdown`: use `labsim fault`/`heal`),
  static and BGP routes, console timeouts, slow vSRX boots, a person sharing the console. As on
  the real consoles, `show logging` needs enable mode (AINOPS's sessions are in user EXEC).
- AINOPS never imports `labsim` (a test checks it).

## Evaluation set (evals)

Questions to AINOPS on the simulated lab, each with the faults it is asked under and the answer
an engineer would accept, scored by code: right, partly (right device, not the interface),
wrong, missed, failed. A wrong answer with high confidence is flagged on its own.

```powershell
cd backend
uv run python -m evals --list                    # the cases (src/evals/cases.yaml)
uv run python -m evals                           # all of them
uv run python -m evals --case leased-line-shut   # one (repeat --case for more)
uv run python -m evals --repeat 3 --pause 60     # each 3 times, a minute apart
```

- Needs the stack on the simulated lab (`scripts\start-all.ps1 -Sim`); it refuses to run when
  AINOPS reports the live lab or no simulated console answers. It switches the simulator's
  faults per case and puts back the ones that were on, also when it fails or is stopped.
- Runs the agent in its own process: no case is drafted in Cases and no past case is offered as a
  hint, so runs compare. Never runs discovery (the graph must be the healthy one).
- Results: a table, and `logs/evals/eval-<time>.json` with each answer, its checks and tokens.
- **Cost:** a full pass is roughly 0.5-0.9 million tokens. The free Groq tier (8,000 tokens a
  minute, 200,000 a day) cannot run it; a fault-1 case alone fails there with a 413.
- Add a case to `cases.yaml` for every wrong answer found by hand.
- AINOPS never imports `evals` (a test checks it).

## Network MCP server

Read-only, vendor-neutral tools for the lab routers (Cisco IOS) and firewalls (Juniper vSRX).

```
uv run python -m ainops mcp-network        # http://127.0.0.1:8101/mcp
```

It always works on the live lab: `LAB_EVE_HOST=<EVE-NG address>` in the repo-root `.env`. There is
no mode that answers from saved outputs, and nothing is recorded while it works.

Test data (real device outputs the tests replay) is captured on purpose, never by normal use:

```
uv run python -m ainops capture healthy-2026-10-08   # -> fixtures/captures/healthy-2026-10-08/
```

Try the tools by hand, without any LLM, in the official MCP Inspector:

```
npx @modelcontextprotocol/inspector
```

Choose transport "Streamable HTTP", URL `http://127.0.0.1:8101/mcp`, Connect, then open Tools.

Where things live:

| File | What it is |
|---|---|
| `src/ainops/network/server.py` | Tool definitions (name, description, inputs): what the LLM sees |
| `src/ainops/network/commands.yaml` | The only commands the tools can send, per platform (SME-reviewed) |
| `src/ainops/network/guard.py` | Last check before a command is sent: read-only prefixes, pipes, forbidden words |
| `src/ainops/network/service.py` | Tool logic: inventory lookup, input validation, parsing, audit |
| `src/ainops/network/parsers.py` | Cisco text and Junos JSON -> one shared JSON shape |
| `lab/inventory.yaml` (repo root) | The lab devices and how to reach them (no secrets) |
| `logs/network-audit.jsonl` (repo root) | One line per tool call: who, what, which command, outcome |

## Checks

```
uv run pytest
uv run mypy src tests
uv run ruff check src tests && uv run ruff format --check src tests
```
