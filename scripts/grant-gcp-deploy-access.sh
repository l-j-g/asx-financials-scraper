#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./scripts/grant-gcp-deploy-access.sh --project-id PROJECT_ID --user-email USER_EMAIL [options]

Options:
  --project-id PROJECT_ID
  --user-email USER_EMAIL
  --service-account-name NAME
  --enable-apis
  -h, --help
EOF
}

require_value() {
  local flag=$1
  local value=${2-}
  if [[ -z "$value" ]]; then
    echo "Missing value for $flag" >&2
    exit 1
  fi
}

run_gcloud() {
  local failure_message=$1
  shift

  if ! gcloud "$@"; then
    echo "$failure_message" >&2
    exit 1
  fi
}

PROJECT_ID=""
USER_EMAIL=""
SERVICE_ACCOUNT_NAME="asx-financials-run"
ENABLE_APIS=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-id)
      require_value "$1" "${2-}"
      PROJECT_ID=$2
      shift 2
      ;;
    --user-email)
      require_value "$1" "${2-}"
      USER_EMAIL=$2
      shift 2
      ;;
    --service-account-name)
      require_value "$1" "${2-}"
      SERVICE_ACCOUNT_NAME=$2
      shift 2
      ;;
    --enable-apis)
      ENABLE_APIS=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "$PROJECT_ID" || -z "$USER_EMAIL" ]]; then
  echo "Missing required --project-id or --user-email argument." >&2
  usage >&2
  exit 1
fi

if ! command -v gcloud >/dev/null 2>&1; then
  echo "gcloud CLI not found in PATH." >&2
  exit 1
fi

MEMBER="user:${USER_EMAIL}"
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
PROJECT_ROLES=(
  roles/run.admin
  roles/secretmanager.admin
  roles/artifactregistry.writer
  roles/serviceusage.serviceUsageAdmin
)

echo "Using project ${PROJECT_ID}"
run_gcloud \
  "Failed to set gcloud project to '${PROJECT_ID}'." \
  config set project "$PROJECT_ID"

if [[ "$ENABLE_APIS" == true ]]; then
  run_gcloud \
    "Failed to enable required APIs for project '${PROJECT_ID}'." \
    services enable \
    artifactregistry.googleapis.com \
    cloudbuild.googleapis.com \
    iam.googleapis.com \
    run.googleapis.com \
    secretmanager.googleapis.com
fi

for role in "${PROJECT_ROLES[@]}"; do
  echo "Granting ${role} to ${MEMBER}"
  run_gcloud \
    "Failed to grant '${role}' to '${MEMBER}' on project '${PROJECT_ID}'." \
    projects add-iam-policy-binding "$PROJECT_ID" \
    --member "$MEMBER" \
    --role "$role"
done

echo "Granting roles/iam.serviceAccountUser on ${SERVICE_ACCOUNT_EMAIL} to ${MEMBER}"
run_gcloud \
  "Failed to grant 'roles/iam.serviceAccountUser' to '${MEMBER}' on service account '${SERVICE_ACCOUNT_EMAIL}'." \
  iam service-accounts add-iam-policy-binding "$SERVICE_ACCOUNT_EMAIL" \
  --member "$MEMBER" \
  --role roles/iam.serviceAccountUser

echo "Access grant complete."
echo "User: ${USER_EMAIL}"
echo "Project: ${PROJECT_ID}"
echo "Service account: ${SERVICE_ACCOUNT_EMAIL}"
