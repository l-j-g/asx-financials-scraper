#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-asx-db-494302}"
REGION="${REGION:-australia-southeast1}"
SERVICE="${SERVICE:-asx-financials-api}"

FILTER="resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${SERVICE}\" AND resource.labels.location=\"${REGION}\""

if ! command -v gcloud >/dev/null 2>&1; then
  echo "gcloud CLI not found in PATH." >&2
  exit 1
fi

if ! gcloud alpha logging tail --help >/dev/null 2>&1; then
  echo "gcloud alpha logging tail is not available. Run: gcloud components update" >&2
  exit 1
fi

echo "Tailing Cloud Run logs for ${SERVICE} (${PROJECT_ID}/${REGION})"

PYTHONWARNINGS="ignore::SyntaxWarning" gcloud alpha logging tail "$FILTER" \
  --project "$PROJECT_ID" \
  --format "value(timestamp,severity,textPayload,jsonPayload.message)"
