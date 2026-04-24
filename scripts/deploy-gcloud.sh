#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./scripts/deploy-gcloud.sh --project-id PROJECT_ID [options]

Options:
  --project-id PROJECT_ID
  --region REGION
  --repository REPOSITORY
  --service SERVICE
  --service-account-name NAME
  --secret-name NAME
  --image-tag TAG
  --mongodb-uri URI
  --mongodb-database NAME
  --min-instances COUNT
  --max-instances COUNT
  --concurrency COUNT
  --timeout-seconds SECONDS
  --cpu CPU
  --memory MEMORY
  --yahoo-request-timeout-seconds SECONDS
  --private-service
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

cleanup() {
  if [[ -n "${TMP_MONGODB_URI_FILE:-}" ]]; then
    rm -f "$TMP_MONGODB_URI_FILE"
  fi
}

PROJECT_ID=""
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REGION="australia-southeast1"
REPOSITORY="asx-financials"
SERVICE="asx-financials-api"
SERVICE_ACCOUNT_NAME="asx-financials-run"
SECRET_NAME="asx-financials-mongodb-uri"
IMAGE_TAG="latest"
MONGODB_URI=""
MONGODB_DATABASE="asx_financials"
MIN_INSTANCES=0
MAX_INSTANCES=2
CONCURRENCY=10
TIMEOUT_SECONDS=900
CPU="1"
MEMORY="512Mi"
YAHOO_REQUEST_TIMEOUT_SECONDS=30
PRIVATE_SERVICE=false
TMP_MONGODB_URI_FILE=""

trap cleanup EXIT

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
    --service)
      require_value "$1" "${2-}"
      SERVICE=$2
      shift 2
      ;;
    --service-account-name)
      require_value "$1" "${2-}"
      SERVICE_ACCOUNT_NAME=$2
      shift 2
      ;;
    --secret-name)
      require_value "$1" "${2-}"
      SECRET_NAME=$2
      shift 2
      ;;
    --image-tag)
      require_value "$1" "${2-}"
      IMAGE_TAG=$2
      shift 2
      ;;
    --mongodb-uri)
      require_value "$1" "${2-}"
      MONGODB_URI=$2
      shift 2
      ;;
    --mongodb-database)
      require_value "$1" "${2-}"
      MONGODB_DATABASE=$2
      shift 2
      ;;
    --min-instances)
      require_value "$1" "${2-}"
      MIN_INSTANCES=$2
      shift 2
      ;;
    --max-instances)
      require_value "$1" "${2-}"
      MAX_INSTANCES=$2
      shift 2
      ;;
    --concurrency)
      require_value "$1" "${2-}"
      CONCURRENCY=$2
      shift 2
      ;;
    --timeout-seconds)
      require_value "$1" "${2-}"
      TIMEOUT_SECONDS=$2
      shift 2
      ;;
    --cpu)
      require_value "$1" "${2-}"
      CPU=$2
      shift 2
      ;;
    --memory)
      require_value "$1" "${2-}"
      MEMORY=$2
      shift 2
      ;;
    --yahoo-request-timeout-seconds)
      require_value "$1" "${2-}"
      YAHOO_REQUEST_TIMEOUT_SECONDS=$2
      shift 2
      ;;
    --private-service)
      PRIVATE_SERVICE=true
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
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/${SERVICE}:${IMAGE_TAG}"
ENV_VARS="APP_ENV=production,MONGODB_DATABASE=${MONGODB_DATABASE},YAHOO_REQUEST_TIMEOUT_SECONDS=${YAHOO_REQUEST_TIMEOUT_SECONDS}"

echo "Using project ${PROJECT_ID} in region ${REGION}"
run_gcloud "Failed to set gcloud project to '${PROJECT_ID}'." config set project "$PROJECT_ID"
run_gcloud "Google Cloud project '${PROJECT_ID}' is not accessible." projects describe "$PROJECT_ID"

if [[ -n "$MONGODB_URI" ]]; then
  TMP_MONGODB_URI_FILE=$(mktemp)
  printf '%s' "$MONGODB_URI" > "$TMP_MONGODB_URI_FILE"

  if ! gcloud secrets describe "$SECRET_NAME" >/dev/null 2>&1; then
    run_gcloud "Failed to create secret '${SECRET_NAME}'." \
      secrets create "$SECRET_NAME" --replication-policy=automatic
  fi

  run_gcloud "Failed to add new version to secret '${SECRET_NAME}'." \
    secrets versions add "$SECRET_NAME" --data-file "$TMP_MONGODB_URI_FILE"
  echo "Updated secret ${SECRET_NAME}"
else
  run_gcloud "Secret '${SECRET_NAME}' missing. Pass --mongodb-uri to create it." \
    secrets describe "$SECRET_NAME"
fi

echo "Building image ${IMAGE}"
run_gcloud "Cloud Build failed for image '${IMAGE}'." builds submit "$REPO_ROOT" --tag "$IMAGE"

DEPLOY_ARGS=(
  run deploy "$SERVICE"
  --image "$IMAGE"
  --region "$REGION"
  --service-account "$SERVICE_ACCOUNT_EMAIL"
  --port 8080
  --min-instances "$MIN_INSTANCES"
  --max-instances "$MAX_INSTANCES"
  --concurrency "$CONCURRENCY"
  --timeout "$TIMEOUT_SECONDS"
  --cpu "$CPU"
  --memory "$MEMORY"
  --set-secrets "MONGODB_URI=${SECRET_NAME}:latest"
  --set-env-vars "$ENV_VARS"
)

if [[ "$PRIVATE_SERVICE" == true ]]; then
  DEPLOY_ARGS+=(--no-allow-unauthenticated)
else
  DEPLOY_ARGS+=(--allow-unauthenticated)
fi

echo "Deploying service ${SERVICE}"
run_gcloud "Failed to deploy Cloud Run service '${SERVICE}'." "${DEPLOY_ARGS[@]}"

if ! SERVICE_URL=$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)'); then
  echo "Failed to describe Cloud Run service '${SERVICE}'." >&2
  exit 1
fi

echo "Service URL: ${SERVICE_URL}"
echo "Health check: ${SERVICE_URL}/health"
