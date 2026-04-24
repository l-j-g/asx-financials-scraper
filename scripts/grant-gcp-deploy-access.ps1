param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectId,
    [Parameter(Mandatory = $true)]
    [string]$UserEmail,
    [string]$ServiceAccountName = "asx-financials-run",
    [switch]$EnableApis
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

$member = "user:$UserEmail"
$serviceAccountEmail = "$ServiceAccountName@$ProjectId.iam.gserviceaccount.com"
$projectRoles = @(
    "roles/run.admin"
    "roles/secretmanager.admin"
    "roles/artifactregistry.writer"
    "roles/serviceusage.serviceUsageAdmin"
)

Write-Host "Using project $ProjectId"
Invoke-GcloudChecked -Arguments @("config", "set", "project", $ProjectId) -FailureMessage "Failed to set gcloud project to '$ProjectId'."

if ($EnableApis) {
    Invoke-GcloudChecked -Arguments @(
        "services",
        "enable",
        "artifactregistry.googleapis.com",
        "cloudbuild.googleapis.com",
        "iam.googleapis.com",
        "run.googleapis.com",
        "secretmanager.googleapis.com"
    ) -FailureMessage "Failed to enable required APIs for project '$ProjectId'."
}

foreach ($role in $projectRoles) {
    Write-Host "Granting $role to $member"
    Invoke-GcloudChecked -Arguments @(
        "projects",
        "add-iam-policy-binding",
        $ProjectId,
        "--member",
        $member,
        "--role",
        $role
    ) -FailureMessage "Failed to grant '$role' to '$member' on project '$ProjectId'."
}

Write-Host "Granting roles/iam.serviceAccountUser on $serviceAccountEmail to $member"
Invoke-GcloudChecked -Arguments @(
    "iam",
    "service-accounts",
    "add-iam-policy-binding",
    $serviceAccountEmail,
    "--member",
    $member,
    "--role",
    "roles/iam.serviceAccountUser"
) -FailureMessage "Failed to grant 'roles/iam.serviceAccountUser' to '$member' on service account '$serviceAccountEmail'."

Write-Host "Access grant complete."
Write-Host "User: $UserEmail"
Write-Host "Project: $ProjectId"
Write-Host "Service account: $serviceAccountEmail"
