param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectId,
    [string]$Region = "australia-southeast1",
    [string]$Repository = "asx-financials",
    [string]$ServiceAccountName = "asx-financials-run",
    [string]$ServiceAccountDisplayName = "ASX Financials Cloud Run"
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

Write-Host "Using project $ProjectId in region $Region"
Invoke-GcloudChecked -Arguments @("config", "set", "project", $ProjectId) -FailureMessage "Failed to set gcloud project to '$ProjectId'."
Invoke-GcloudChecked -Arguments @("projects", "describe", $ProjectId) -FailureMessage "Google Cloud project '$ProjectId' is not accessible to the active gcloud account."

Invoke-GcloudChecked -Arguments @(
    "services",
    "enable",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "iam.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com"
) -FailureMessage "Failed to enable required Google Cloud APIs for project '$ProjectId'."

& gcloud artifacts repositories describe $Repository --location $Region *> $null
if ($LASTEXITCODE -ne 0) {
    Invoke-GcloudChecked -Arguments @(
        "artifacts",
        "repositories",
        "create",
        $Repository,
        "--repository-format",
        "docker",
        "--location",
        $Region,
        "--description",
        "Container images for ASX Financials"
    ) -FailureMessage "Failed to create Artifact Registry repository '$Repository' in project '$ProjectId'."
}

& gcloud iam service-accounts describe $serviceAccountEmail *> $null
if ($LASTEXITCODE -ne 0) {
    Invoke-GcloudChecked -Arguments @(
        "iam",
        "service-accounts",
        "create",
        $ServiceAccountName,
        "--display-name",
        $ServiceAccountDisplayName
    ) -FailureMessage "Failed to create service account '$serviceAccountEmail' in project '$ProjectId'."
}

Invoke-GcloudChecked -Arguments @(
    "projects",
    "add-iam-policy-binding",
    $ProjectId,
    "--member",
    "serviceAccount:$serviceAccountEmail",
    "--role",
    "roles/secretmanager.secretAccessor"
) -FailureMessage "Failed to grant Secret Manager access to service account '$serviceAccountEmail' in project '$ProjectId'."

Write-Host "Bootstrap complete."
Write-Host "Service account: $serviceAccountEmail"
Write-Host "Artifact Registry: $Region-docker.pkg.dev/$ProjectId/$Repository"
