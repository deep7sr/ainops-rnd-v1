# Start the whole AINOPS stack, each piece in its own PowerShell window (close a window to stop it):
#   Neo4j (graph) -> network MCP (8101) -> topology MCP (8102) -> API (8000) -> web UI (5173)
# Then open http://localhost:5173
#
# AINOPS works on the live lab: LAB_EVE_HOST=<EVE-NG address> in the repo-root .env.
# With -Sim it works on the simulated lab instead (backend/src/labsim, for when the EVE-NG lab is
# not available): a "lab simulator" window opens first, and every window gets
# LAB_EVE_HOST=127.0.0.1 and LAB_SIMULATED=true (these win over .env; the UI then says
# "simulated devices"). Faults: `cd backend; uv run python -m labsim faults`.
param([switch]$Sim)

$repo = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $repo "backend"
$frontend = Join-Path $repo "frontend"

if ($Sim) {
    $env:LAB_EVE_HOST = "127.0.0.1"
    $env:LAB_SIMULATED = "true"
}

function Start-Piece($title, $folder, $command) {
    $script = "`$Host.UI.RawUI.WindowTitle = '$title'; Set-Location '$folder'; $command"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $script
}

function Wait-Port($port, $name, $seconds = 90) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-NetConnection 127.0.0.1 -Port $port -InformationLevel Quiet -WarningAction SilentlyContinue) {
            Write-Host "  $name is up (port $port)"
            return
        }
        Start-Sleep -Seconds 1
    }
    Write-Warning "$name did not start on port $port within $seconds s: check its window"
}

Write-Host "Starting AINOPS$(if ($Sim) { ' on the SIMULATED lab' })..."
if ($Sim) {
    Start-Piece "AINOPS - lab simulator" $backend "uv run python -m labsim"
    Wait-Port 32769 "Lab simulator"
}
Start-Piece "AINOPS - Neo4j" $repo "& '$repo\scripts\start-neo4j.ps1'"
Wait-Port 7687 "Neo4j"
Start-Piece "AINOPS - network MCP" $backend "uv run python -m ainops mcp-network"
Wait-Port 8101 "Network MCP server"
Start-Piece "AINOPS - topology MCP" $backend "uv run python -m ainops mcp-topology"
Wait-Port 8102 "Topology MCP server"
Start-Piece "AINOPS - API" $backend "uv run python -m ainops api"
Wait-Port 8000 "API"
Start-Piece "AINOPS - web UI" $frontend "npm run dev"
Wait-Port 5173 "Web UI"
Write-Host "Ready: http://localhost:5173"
