# Start the local Neo4j knowledge graph in this window (Ctrl+C stops it).
# Installed per user, no admin rights, no Docker (the lab laptop must not run Hyper-V/WSL2):
#   Java:  %LOCALAPPDATA%\Programs\jdk-21.*        (Microsoft Build of OpenJDK 21, zip)
#   Neo4j: %LOCALAPPDATA%\Programs\neo4j-community-*  (Neo4j Community, zip)
# Browser UI: http://localhost:7474  (user neo4j, password = NEO4J_PASSWORD in the repo .env)

$programs = Join-Path $env:LOCALAPPDATA "Programs"
$jdk = Get-ChildItem $programs -Directory -Filter "jdk-21*" | Sort-Object Name -Descending | Select-Object -First 1
$neo4j = Get-ChildItem $programs -Directory -Filter "neo4j-community-*" | Sort-Object Name -Descending | Select-Object -First 1
if (-not $jdk -or -not $neo4j) {
    Write-Error "Java 21 or Neo4j not found in $programs (see backend/README.md)"
    exit 1
}
$env:JAVA_HOME = $jdk.FullName
& (Join-Path $neo4j.FullName "bin\neo4j.bat") console
