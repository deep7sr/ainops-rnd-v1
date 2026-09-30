# Start the whole AINOPS stack, each piece in its own PowerShell window (close a window to stop it):
#   Neo4j (graph) -> network MCP (8101) -> topology MCP (8102) -> API (8000) -> web UI (5173)
# Then open http://localhost:5173
#
# Live lab or recorded data is chosen in the repo-root .env:
#   LAB_EXECUTOR=live   and LAB_EVE_HOST=<EVE-NG address>   (live devices)
#   LAB_EXECUTOR=replay                                    (recorded outputs, no device contacted)

$repo = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $repo "backend"
$frontend = Join-Path $repo "frontend"

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

Write-Host "Starting AINOPS..."
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
