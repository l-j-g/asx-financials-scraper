param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectId,
    [string]$Region = "australia-southeast1",
    [string]$Repository = "asx-financials",
    [string]$Service = "asx-financials-api",
    [string]$Job = "asx-financials-migrate",
    [string]$ServiceAccountName = "asx-financials-run",
    [string]$SecretName = "asx-financials-database-url",
    [string]$ImageTag = "latest",
    [string]$DatabaseUrl,
    [int]$MinInstances = 0,
    [int]$MaxInstances = 2,
    [int]$Concurrency = 10,
    [int]$TimeoutSeconds = 900,
    [string]$Cpu = "1",
    [string]$Memory = "512Mi",
    [int]$YahooRequestTimeoutSeconds = 30,
    [int]$DatabasePoolSize = 2,
    [int]$DatabaseMaxOverflow = 0,
    [int]$DatabasePoolTimeoutSeconds = 30,
    [int]$DatabasePoolRecycleSeconds = 1800,
    [int]$DatabaseConnectTimeoutSeconds = 10,
    [switch]$SkipMigrations,
    [switch]$PrivateService
)

$ErrorActionPreference = "Stop"

function Invoke-GcloudChecked {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [string]$FailureMessage = "gcloud command failed."
    )

    & gcloud @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw $FailureMessage
    }
}

$serviceAccountEmail = "$ServiceAccountName@$ProjectId.iam.gserviceaccount.com"
$image = "$Region-docker.pkg.dev/$ProjectId/$Repository/${Service}:$ImageTag"
$envVars = @(
    "APP_ENV=production"
    "RUN_MIGRATIONS_ON_STARTUP=false"
    "YAHOO_REQUEST_TIMEOUT_SECONDS=$YahooRequestTimeoutSeconds"
    "DATABASE_POOL_SIZE=$DatabasePoolSize"
    "DATABASE_MAX_OVERFLOW=$DatabaseMaxOverflow"
    "DATABASE_POOL_TIMEOUT_SECONDS=$DatabasePoolTimeoutSeconds"
    "DATABASE_POOL_RECYCLE_SECONDS=$DatabasePoolRecycleSeconds"
    "DATABASE_CONNECT_TIMEOUT_SECONDS=$DatabaseConnectTimeoutSeconds"
) -join ","

Write-Host "Using project $ProjectId in region $Region"
Invoke-GcloudChecked -Arguments @("config", "set", "project", $ProjectId) -FailureMessage "Failed to set gcloud project to '$ProjectId'."
Invoke-GcloudChecked -Arguments @("projects", "describe", $ProjectId) -FailureMessage "Google Cloud project '$ProjectId' is not accessible to the active gcloud account."

if ($PSBoundParameters.ContainsKey("DatabaseUrl")) {
    $tmp = [System.IO.Path]::GetTempFileName()
    try {
        Set-Content -Path $tmp -Value $DatabaseUrl -NoNewline

        & gcloud secrets describe $SecretName *> $null
        if ($LASTEXITCODE -ne 0) {
            Invoke-GcloudChecked -Arguments @("secrets", "create", $SecretName, "--replication-policy=automatic") -FailureMessage "Failed to create secret '$SecretName' in project '$ProjectId'."
        }

        Invoke-GcloudChecked -Arguments @("secrets", "versions", "add", $SecretName, "--data-file", $tmp) -FailureMessage "Failed to add a new version to secret '$SecretName' in project '$ProjectId'."
        Write-Host "Updated secret $SecretName"
    }
    finally {
        Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    }
}

 $secretVersion = "latest"

Write-Host "Building image $image"
Invoke-GcloudChecked -Arguments @("builds", "submit", "--tag", $image) -FailureMessage "Cloud Build failed for image '$image'."

$jobArgs = @(
    "run"
    "jobs"
    "describe"
    $Job
    "--region"
    $Region
)
& gcloud @jobArgs *> $null

$jobUpsertArgs = @(
    "run"
    "jobs"
    $(if ($LASTEXITCODE -eq 0) { "update" } else { "create" })
    $Job
    "--image"
    $image
    "--region"
    $Region
    "--service-account"
    $serviceAccountEmail
    "--set-secrets"
    "DATABASE_URL=${SecretName}:$secretVersion"
    "--set-env-vars"
    $envVars
    "--command"
    "uv"
    "--args"
    "run,alembic,upgrade,head"
    "--tasks"
    "1"
    "--max-retries"
    "0"
)
Invoke-GcloudChecked -Arguments $jobUpsertArgs -FailureMessage "Failed to create or update Cloud Run job '$Job' in project '$ProjectId'."

if (-not $SkipMigrations) {
    Write-Host "Running migrations job $Job"
    Invoke-GcloudChecked -Arguments @("run", "jobs", "execute", $Job, "--region", $Region, "--wait") -FailureMessage "Failed to execute Cloud Run job '$Job' in project '$ProjectId'."
}

$deployArgs = @(
    "run"
    "deploy"
    $Service
    "--image"
    $image
    "--region"
    $Region
    "--service-account"
    $serviceAccountEmail
    "--port"
    "8080"
    "--min-instances"
    "$MinInstances"
    "--max-instances"
    "$MaxInstances"
    "--concurrency"
    "$Concurrency"
    "--timeout"
    "$TimeoutSeconds"
    "--cpu"
    $Cpu
    "--memory"
    $Memory
    "--set-secrets"
    "DATABASE_URL=${SecretName}:$secretVersion"
    "--set-env-vars"
    $envVars
)

if ($PrivateService) {
    $deployArgs += "--no-allow-unauthenticated"
}
else {
    $deployArgs += "--allow-unauthenticated"
}

Write-Host "Deploying service $Service"
Invoke-GcloudChecked -Arguments $deployArgs -FailureMessage "Failed to deploy Cloud Run service '$Service' in project '$ProjectId'."

$serviceUrl = & gcloud run services describe $Service `
    --region $Region `
    --format "value(status.url)"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to describe Cloud Run service '$Service' in project '$ProjectId'."
}

Write-Host "Service URL: $serviceUrl"
Write-Host "Health check: $serviceUrl/health"
