# ASX Financials Backend

Python backend for ingesting ASX financial data from Yahoo Finance and storing it in MongoDB.

## Stack

- FastAPI
- yfinance
- MongoDB
- uv
- Ruff
- pytest
- mypy

## Local Setup

1. Create the virtual environment:

```bash
python3.13 -m venv .venv
```

2. Activate it:

```bash
source .venv/bin/activate
```

3. Install `uv` and sync dependencies:

```bash
python -m pip install --upgrade pip uv
uv sync --all-groups
```

4. Start local MongoDB:

```bash
docker compose up -d mongodb
```

5. Copy `.env.example` to `.env` and adjust values if needed.

## Run

API:

```bash
uv run uvicorn asx_financials.api.app:create_app --factory --reload
```

One-off ingestion:

```bash
uv run asx-financials ingest BHP
uv run asx-financials ingest CSL --annual-only
uv run asx-financials ingest WBC --quarterly-only
```

## Debug in PyCharm

1. Open the repo in PyCharm and set the project interpreter to `.venv/bin/python`.

2. Start local MongoDB:

```bash
docker compose up -d mongodb
```

3. Copy `.env.example` to `.env` if you have not already done so.

4. Use the shared run configuration in `.run/ASX Financials API.run.xml`.

   It starts `uvicorn` in module mode with:

```text
asx_financials.api.app:create_app --factory --reload --host 127.0.0.1 --port 8000
```

5. Start the debugger in PyCharm and verify the app responds at `http://127.0.0.1:8000/health`.

The app reads `.env` from the repo root, so the shared PyCharm configuration does not need to duplicate your local settings.

## Quality Checks

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```

## API

- `POST /ingestions/{ticker}?include_annual=true&include_quarterly=true`
- `GET /ingestions/{ticker}`
- `GET /companies/{ticker}`

## Deploy to Google Cloud Run

This deployment path keeps MongoDB external, stores the MongoDB connection string in Secret Manager, and deploys the API to Cloud Run.

### Prerequisites

- A Google Cloud project with billing enabled.
- `gcloud` installed and authenticated.
- An external MongoDB database such as MongoDB Atlas.
- A production `MONGODB_URI` using the `mongodb+srv://...` or `mongodb://...` format.

```text
mongodb+srv://<user>:<password>@<cluster>/<database>?retryWrites=true&w=majority
```

There is a production example file in `.env.production.example`.

### Automated deploy

Bootstrap the Google Cloud resources once:

```bash
./scripts/bootstrap-gcp.sh --project-id your-project-id
```

Then deploy the app:

```bash
./scripts/deploy-gcloud.sh \
  --project-id your-project-id \
  --mongodb-uri "mongodb+srv://<user>:<password>@<cluster>/asx_financials?retryWrites=true&w=majority"
```

The deploy script does all of this:

- Builds and pushes the image to Artifact Registry.
- Creates or updates the Secret Manager secret for `MONGODB_URI`.
- Deploys the Cloud Run service.
- Prints the deployed service URL and `/health` URL.

Useful flags:

- `--private-service` keeps the Cloud Run service private.
- `--mongodb-database asx_financials` sets the database name used by the app.
- `--max-instances 1` is a conservative default if your MongoDB plan has a low connection limit.

### Manual deploy

If you want to run each command yourself, use these variables:

```bash
PROJECT_ID="your-project-id"
REGION="australia-southeast1"
REPOSITORY="asx-financials"
SERVICE="asx-financials-api"
SERVICE_ACCOUNT_NAME="asx-financials-run"
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/${SERVICE}:latest"
MONGODB_URI="mongodb+srv://<user>:<password>@<cluster>/asx_financials?retryWrites=true&w=majority"
MONGODB_DATABASE="asx_financials"
```

Enable services and create base resources:

```bash
gcloud config set project "$PROJECT_ID"

gcloud services enable \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  iam.googleapis.com \
  run.googleapis.com \
  secretmanager.googleapis.com

gcloud artifacts repositories create "$REPOSITORY" \
  --repository-format=docker \
  --location="$REGION" \
  --description="Container images for ASX Financials"

gcloud iam service-accounts create "$SERVICE_ACCOUNT_NAME" \
  --display-name="ASX Financials Cloud Run"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
  --role="roles/secretmanager.secretAccessor"
```

Store the MongoDB URI in Secret Manager:

```bash
printf '%s' "$MONGODB_URI" > .gcp-mongodb-uri.txt

gcloud secrets create asx-financials-mongodb-uri \
  --replication-policy=automatic

gcloud secrets versions add asx-financials-mongodb-uri \
  --data-file=.gcp-mongodb-uri.txt

rm .gcp-mongodb-uri.txt
```

Build and deploy:

```bash
gcloud builds submit --tag "$IMAGE"

gcloud run deploy "$SERVICE" \
  --image "$IMAGE" \
  --region "$REGION" \
  --service-account "$SERVICE_ACCOUNT_EMAIL" \
  --allow-unauthenticated \
  --port 8080 \
  --min-instances 0 \
  --max-instances 2 \
  --concurrency 10 \
  --timeout 900 \
  --cpu 1 \
  --memory 512Mi \
  --set-secrets MONGODB_URI=asx-financials-mongodb-uri:latest \
  --set-env-vars APP_ENV=production,MONGODB_DATABASE="$MONGODB_DATABASE",YAHOO_REQUEST_TIMEOUT_SECONDS=30
```

### Verify the deployment

```bash
SERVICE_URL="$(gcloud run services describe "$SERVICE" \
  --region "$REGION" \
  --format='value(status.url)')"

curl -fsS "$SERVICE_URL/health"
```

You can then test a real endpoint, for example:

```bash
curl -fsS "$SERVICE_URL/companies/BHP"
```

### Rollout checklist

1. Build and push the new image with `gcloud builds submit`.
2. Deploy the new Cloud Run revision with `gcloud run deploy`.
3. Verify `/health` and one application endpoint.

## Notes

- Financial statement payloads and raw provider payloads are stored as MongoDB documents.
- Statement snapshots are append-only by revision hash, with `isCurrent` marking latest revision.
- Comparable metrics are extracted into `financial_facts` for cross-company screening.
- Failed or null provider responses do not overwrite the last successful stored values.
