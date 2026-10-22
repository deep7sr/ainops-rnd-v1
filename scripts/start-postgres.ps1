# Start the local Postgres (the system of record) in this window (Ctrl+C or closing it stops it).
# Installed per user, no admin rights, no Windows service, no Docker (see backend/README.md):
#   Postgres: %LOCALAPPDATA%\Programs\pgsql-*   (the EDB "binaries" zip, unpacked and renamed)
#   Data:     %LOCALAPPDATA%\ainops\pgdata      (outside the repo; made on the first start)
# It listens on 127.0.0.1:5432 only. The first start makes the database files with the admin
# user "postgres" and the password POSTGRES_ADMIN_PASSWORD from the repo .env (never printed).
# Then, once: `cd backend; uv run python -m ainops db setup` (roles, databases, schema).

$repo = Split-Path -Parent $PSScriptRoot
$programs = Join-Path $env:LOCALAPPDATA "Programs"
$pgsql = Get-ChildItem $programs -Directory -Filter "pgsql-*" | Sort-Object Name -Descending | Select-Object -First 1
if (-not $pgsql -or -not (Test-Path (Join-Path $pgsql.FullName "bin\postgres.exe"))) {
    Write-Error "Postgres not found in $programs\pgsql-* (see backend/README.md)"
    exit 1
}
$bin = Join-Path $pgsql.FullName "bin"
$data = Join-Path $env:LOCALAPPDATA "ainops\pgdata"

if (-not (Test-Path (Join-Path $data "PG_VERSION"))) {
    # .env keys can hold digits: match [A-Z0-9_], and take everything after the first "=".
    $line = Get-Content (Join-Path $repo ".env") | Where-Object { $_ -match '^POSTGRES_ADMIN_PASSWORD=' } | Select-Object -First 1
    $password = if ($line) { $line.Substring($line.IndexOf("=") + 1).Trim().Trim('"') } else { "" }
    if (-not $password) {
        Write-Error "POSTGRES_ADMIN_PASSWORD is not set in $repo\.env: set it, then start again"
        exit 1
    }
    Write-Host "First start: making the database files in $data ..."
    New-Item -ItemType Directory -Force $data | Out-Null
    $pwfile = New-TemporaryFile
    try {
        [System.IO.File]::WriteAllText($pwfile.FullName, $password)
        & (Join-Path $bin "initdb.exe") -D $data -U postgres --pwfile=$($pwfile.FullName) `
            --auth=scram-sha-256 --encoding=UTF8 --locale=C
        if ($LASTEXITCODE -ne 0) { Write-Error "initdb failed"; exit 1 }
    } finally {
        Remove-Item $pwfile.FullName -Force
    }
}

& (Join-Path $bin "postgres.exe") -D $data -c listen_addresses=127.0.0.1 -p 5432
