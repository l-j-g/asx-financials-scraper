#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./scripts/bootstrap-gcp.sh --project-id PROJECT_ID [options]

Options:
  --project-id PROJECT_ID
  --region REGION
  --repository REPOSITORY
  --service-account-name NAME
  --service-account-display-name NAME
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
REGION="australia-southeast1"
REPOSITORY="asx-financials"
SERVICE_ACCOUNT_NAME="asx-financials-run"
SERVICE_ACCOUNT_DISPLAY_NAME="ASX Financials Cloud Run"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-id)
      require_value "$1" "${2-}"
      PROJECT_ID=$2
      shift 2
      ;;
    --region)
      require_value "$1" "${2-}"
      REGION=$2
      shift 2
      ;;
    --repository)
      require_value "$1" "${2-}"
      REPOSITORY=$2
      shift 2
      ;;
    --service-account-name)
      require_value "$1" "${2-}"
      SERVICE_ACCOUNT_NAME=$2
      shift 2
      ;;
    --service-account-display-name)
      require_value "$1" "${2-}"
      SERVICE_ACCOUNT_DISPLAY_NAME=$2
      shift 2
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

if [[ -z "$PROJECT_ID" ]]; then
  echo "Missing required --project-id argument." >&2
  usage >&2
  exit 1
fi

if ! command -v gcloud >/dev/null 2>&1; then
  echo "gcloud CLI not found in PATH." >&2
  exit 1
fi

SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "Using project ${PROJECT_ID} in region ${REGION}"
run_gcloud \
  "Failed to set gcloud project to '${PROJECT_ID}'." \
  config set project "$PROJECT_ID"
run_gcloud \
  "Google Cloud project '${PROJECT_ID}' is not accessible to the active gcloud account." \
  projects describe "$PROJECT_ID"

run_gcloud \
  "Failed to enable required Google Cloud APIs for project '${PROJECT_ID}'." \
  services enable \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  iam.googleapis.com \
  run.googleapis.com \
  secretmanager.googleapis.com

if ! gcloud artifacts repositories describe "$REPOSITORY" --location "$REGION" >/dev/null 2>&1; then
  run_gcloud \
    "Failed to create Artifact Registry repository '${REPOSITORY}' in project '${PROJECT_ID}'." \
    artifacts repositories create "$REPOSITORY" \
    --repository-format docker \
    --location "$REGION" \
    --description "Container images for ASX Financials"
fi

if ! gcloud iam service-accounts describe "$SERVICE_ACCOUNT_EMAIL" >/dev/null 2>&1; then
  run_gcloud \
    "Failed to create service account '${SERVICE_ACCOUNT_EMAIL}' in project '${PROJECT_ID}'." \
    iam service-accounts create "$SERVICE_ACCOUNT_NAME" \
    --display-name "$SERVICE_ACCOUNT_DISPLAY_NAME"
fi

run_gcloud \
  "Failed to grant Secret Manager access to service account '${SERVICE_ACCOUNT_EMAIL}' in project '${PROJECT_ID}'." \
  projects add-iam-policy-binding "$PROJECT_ID" \
  --member "serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
  --role "roles/secretmanager.secretAccessor"

echo "Bootstrap complete."
echo "Service account: ${SERVICE_ACCOUNT_EMAIL}"
echo "Artifact Registry: ${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}"
