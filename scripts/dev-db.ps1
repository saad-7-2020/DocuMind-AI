<#
.SYNOPSIS
  Run a local Postgres + pgvector WITHOUT Docker (Windows development fallback).

.DESCRIPTION
  Uses the Postgres 16 binaries bundled in `pixeltable-pgserver` 0.5.1 (they include pgvector 0.8.1).

  The version is pinned on purpose: pgvector is compiled for the CPU of whoever built the package,
  and newer builds (0.6.0, Postgres 18) use AVX-512 instructions, which crash the server with
  "illegal instruction" (0xC000001D) on CPUs without AVX-512 (e.g. AMD Ryzen 5 5500). 0.5.1 was
  verified on such a CPU to insert 1024-d vectors, build an HNSW index and search.

  This build has no `unaccent` extension, so migration 0001 falls back to a French search
  configuration without accent folding. The Docker image has `unaccent` and gets the full one.

  It listens only on loopback (127.0.0.1 and ::1), port 5433, with the same credentials and database
  names as docker-compose.yml, so backend/.env needs no change. Data lives outside the repo.

  One-time prerequisite (isolated environment, not part of the project dependencies):
      py -m uv venv A:\documind\pgenv --python 3.13
      py -m uv pip install --python A:\documind\pgenv\Scripts\python.exe pixeltable-pgserver==0.5.1

.EXAMPLE
  .\scripts\dev-db.ps1 start     # creates the cluster on first run, then starts it
  .\scripts\dev-db.ps1 status
  .\scripts\dev-db.ps1 stop
#>
param(
    [ValidateSet("start", "stop", "status")] [string]$Action = "start",
    [string]$PgHome = "A:\documind\pgenv\Lib\site-packages\pixeltable_pgserver\pginstall",
    [string]$DataDir = "A:\documind\pgdata16",
    [int]$Port = 5433
)

$ErrorActionPreference = "Stop"
$bin = Join-Path $PgHome "bin"
if (-not (Test-Path "$bin\postgres.exe")) { throw "Bundled Postgres not found at $PgHome (see the prerequisite in this script's header)." }
$log = Join-Path $DataDir "server.log"
$user = "documind"
$password = "documind"   # local development credential, same as docker-compose.yml

function Test-Running { & "$bin\pg_isready.exe" -h 127.0.0.1 -p $Port 2>&1 | Out-Null; return ($LASTEXITCODE -eq 0) }

function Initialize-Cluster {
    if (Test-Path "$DataDir\PG_VERSION") { return }
    New-Item -ItemType Directory -Force $DataDir | Out-Null
    $pw = New-TemporaryFile
    try {
        Set-Content -Path $pw -Value $password -NoNewline -Encoding ascii
        # UTF8 + C locale: independent of the Windows (French/CP1252) locale.
        & "$bin\initdb.exe" -D $DataDir -U $user --pwfile=$pw -E UTF8 --locale=C --auth=scram-sha-256 | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "initdb failed" }
    } finally { Remove-Item $pw -Force -ErrorAction SilentlyContinue }
    Write-Host "Initialized a new cluster in $DataDir"
}

function Initialize-Databases {
    $env:PGPASSWORD = $password
    foreach ($db in "documind", "documind_test") {
        $exists = & "$bin\psql.exe" -h 127.0.0.1 -p $Port -U $user -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$db'"
        if (-not $exists) { & "$bin\psql.exe" -h 127.0.0.1 -p $Port -U $user -d postgres -c "CREATE DATABASE $db" | Out-Null; Write-Host "Created database $db" }
    }
}

switch ($Action) {
    "start" {
        if (Test-Running) { Write-Host "Already running on 127.0.0.1:$Port"; break }
        Initialize-Cluster
        # The server inherits the caller's handles, so waiting on pg_ctl (`-Wait`, or piping its output)
        # blocks until Postgres exits. Launch it detached with no wait, then poll for readiness.
        $ctlArgs = @("start", "-D", "`"$DataDir`"", "-l", "`"$log`"", "-o", "`"-p $Port -c listen_addresses=127.0.0.1,::1`"")
        Start-Process -FilePath "$bin\pg_ctl.exe" -ArgumentList $ctlArgs -WindowStyle Hidden
        $deadline = (Get-Date).AddSeconds(60)
        while (-not (Test-Running) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500 }
        if (-not (Test-Running)) { throw "Postgres did not start within 60 s; see $log" }
        Initialize-Databases
        Write-Host "Postgres is up on 127.0.0.1:$Port  (user=$user, databases: documind, documind_test)"
    }
    "stop" {
        if (Test-Path "$DataDir\PG_VERSION") {
            Start-Process -FilePath "$bin\pg_ctl.exe" -ArgumentList @("stop", "-D", "`"$DataDir`"", "-m", "fast") -WindowStyle Hidden
            $deadline = (Get-Date).AddSeconds(30)
            while ((Test-Running) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500 }
        }
        Write-Host "Stopped."
    }
    "status" {
        if (Test-Running) { Write-Host "running on 127.0.0.1:$Port" } else { Write-Host "not running"; exit 1 }
    }
}
