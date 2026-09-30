$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$envFile = Join-Path $repoRoot '.env.staging.qa.local'
$srcPath = Join-Path $repoRoot 'src'
$stagingRef = 'ucncxwnhcdrqonknkvau'

function Assert-StagingTarget {
    param([hashtable]$Config)

    $supabaseUrl = [string]$Config['SUPABASE_URL']
    $databaseUrl = [string]$Config['DATABASE_URL']
    $projectRef = [string]$Config['SUPABASE_PROJECT_REF']
    $supabaseUri = $null
    $databaseUri = $null
    if (-not [Uri]::TryCreate($supabaseUrl, [UriKind]::Absolute, [ref]$supabaseUri) -or
        $supabaseUri.Scheme -ne 'https' -or
        $supabaseUri.Host -ne "$stagingRef.supabase.co" -or
        $supabaseUri.UserInfo -or $supabaseUri.Query -or $supabaseUri.Fragment) {
        throw 'The Supabase API target is not the staging project.'
    }
    if (-not [Uri]::TryCreate($databaseUrl, [UriKind]::Absolute, [ref]$databaseUri) -or
        $databaseUri.Scheme -notin @('postgres', 'postgresql') -or
        $databaseUri.Host -notlike '*.pooler.supabase.com' -or
        ($databaseUri.UserInfo -split ':', 2)[0] -ne "postgres.$stagingRef") {
        throw 'The database target is not the staging project.'
    }
    if ($projectRef -and $projectRef -ne $stagingRef) {
        throw 'The project ref is not the staging project.'
    }
}

if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
    throw 'The ignored staging QA env file is missing.'
}

$qaConfig = @{}
foreach ($line in Get-Content -LiteralPath $envFile) {
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
        $qaConfig[$Matches[1]] = $Matches[2]
    }
}

$appEnv = ([string]$qaConfig['APP_ENV']).Trim('"').Trim("'").ToLowerInvariant()
$jobs = ([string]$qaConfig['MELPIS_BACKGROUND_JOBS_ENABLED']).Trim('"').Trim("'").ToLowerInvariant()
if ($appEnv -ne 'staging' -or $jobs -ne 'false') {
    throw 'The staging QA env file must set APP_ENV=staging and disable background jobs.'
}
Assert-StagingTarget $qaConfig

docker network inspect melpis-staging-qa --format '{{.Name}}' *> $null
if ($LASTEXITCODE -ne 0) { throw 'The staging QA Docker network is missing.' }
$networkContainersJson = docker network inspect melpis-staging-qa --format '{{json .Containers}}'
$attachedContainers = @(
    ($networkContainersJson | ConvertFrom-Json).PSObject.Properties.Value.Name
)
if ($LASTEXITCODE -ne 0 -or @($attachedContainers | Where-Object {
    $_ -and $_ -notin @('melpis-staging-qa-api', 'melpis-staging-qa-web')
}).Count -gt 0) {
    throw 'The staging QA network contains an unexpected container.'
}
docker image inspect whatsapp-ai-responder:latest --format '{{.Id}}' *> $null
if ($LASTEXITCODE -ne 0) { throw 'The local API image is missing.' }

$existingJson = docker container inspect melpis-staging-qa-api 2>$null
if ($LASTEXITCODE -eq 0) {
    $existing = ($existingJson | ConvertFrom-Json)[0]
    if (-not $existing.NetworkSettings.Networks.'melpis-staging-qa') {
        throw 'The existing API container is outside the staging QA network.'
    }
    $existingConfig = @{}
    foreach ($entry in $existing.Config.Env) {
        if ($entry -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
            $existingConfig[$Matches[1]] = $Matches[2]
        }
    }
    if ($existingConfig['APP_ENV'] -ne 'staging' -or
        $existingConfig['MELPIS_BACKGROUND_JOBS_ENABLED'] -ne 'false') {
        throw 'The existing API container is not isolated for staging QA.'
    }
    Assert-StagingTarget $existingConfig
    docker rm -f melpis-staging-qa-api *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Could not remove the previous staging QA API.' }
}

$containerId = docker run -d --name melpis-staging-qa-api `
    --network melpis-staging-qa --network-alias api `
    -p 127.0.0.1:8001:8000 --env-file $envFile `
    --mount "type=bind,source=$srcPath,target=/app/src,readonly" `
    whatsapp-ai-responder:latest `
    uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --no-proxy-headers --no-access-log
if ($LASTEXITCODE -ne 0 -or -not $containerId) {
    throw 'Could not start the staging QA API.'
}
Write-Output 'Staging QA API started with Uvicorn access logging disabled.'
