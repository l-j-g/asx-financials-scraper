# ASX Financials Backend

Python backend for ingesting ASX financial data from Yahoo Finance and storing it in PostgreSQL.

## Stack

- FastAPI
- SQLAlchemy
- Alembic
- yfinance
- PostgreSQL
- uv
- Ruff
- pytest
- mypy

## Local Setup

1. Create the virtual environment:

```powershell
py -3.13 -m venv .venv
```

2. Activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

3. Install `uv` and sync dependencies:

```powershell
python -m pip install --upgrade pip uv
uv sync --all-groups
```

4. Start local PostgreSQL:

```powershell
docker compose up -d postgres
```

5. Copy `.env.example` to `.env` and adjust values if needed.

6. Apply migrations:

```powershell
uv run alembic upgrade head
```

## Run

API:

```powershell
uv run uvicorn asx_financials.api.app:create_app --factory --reload
```

One-off ingestion:

```powershell
uv run asx-financials ingest BHP
uv run asx-financials ingest CSL --annual-only
uv run asx-financials ingest WBC --quarterly-only
```

## Debug in PyCharm

1. Open the repo in PyCharm and set the project interpreter to `.venv\Scripts\python.exe`.

2. Start local PostgreSQL:

```powershell
docker compose up -d postgres
```

3. Copy `.env.example` to `.env` if you have not already done so.

4. Apply migrations:

```powershell
uv run alembic upgrade head
```

5. Use the shared run configuration in `.run/ASX Financials API.run.xml`.

   It starts `uvicorn` in module mode with:

```text
asx_financials.api.app:create_app --factory --reload --host 127.0.0.1 --port 8000
```

6. Start the debugger in PyCharm and verify the app responds at `http://127.0.0.1:8000/health`.

The app reads `.env` from the repo root, so the shared PyCharm configuration does not need to duplicate your local settings.

## Quality Checks

```powershell
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

This deployment path keeps PostgreSQL external, stores the database connection string in Secret Manager, runs Alembic migrations as a Cloud Run job, and deploys the API to Cloud Run.

### Prerequisites

- A Google Cloud project with billing enabled.
- `gcloud` installed and authenticated.
- An external PostgreSQL database such as Supabase.
- A production `DATABASE_URL` using the `postgresql+psycopg://...` format.

### Choose the right Supabase connection string

Use one of these Supabase connection types:

- Direct connection if your runtime supports IPv6.
- Supavisor session mode on port `5432` if you want the safest Cloud Run-compatible option.

Do not use the transaction pooler on port `6543` for this app. The API and migration job both use long-lived SQLAlchemy sessions.

Example session pooler URL:

```powershell
postgresql+psycopg://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require
```

There is a production example file in `.env.production.example` with the same shape.

### Automated deploy

Bootstrap the Google Cloud resources once:

```powershell
.\scripts\bootstrap-gcp.ps1 -ProjectId your-project-id
```

Then deploy the app and run migrations:

```powershell
.\scripts\deploy-gcloud.ps1 `
  -ProjectId your-project-id `
  -DatabaseUrl "postgresql+psycopg://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require"
```

The deploy script does all of this:

- Builds and pushes the image to Artifact Registry.
- Creates or updates the Secret Manager secret for `DATABASE_URL`.
- Creates or updates the Cloud Run migration job.
- Executes the migration job unless you pass `-SkipMigrations`.
- Deploys the Cloud Run service.
- Prints the deployed service URL and `/health` URL.

Useful flags:

- `-PrivateService` keeps the Cloud Run service private.
- `-SkipMigrations` skips the migration execution for image-only redeploys.
- `-MaxInstances 1` is a conservative default if your Supabase plan has a low connection limit.

### Manual deploy

If you want to run each command yourself, use these variables:

```powershell
$PROJECT_ID = "your-project-id"
$REGION = "australia-southeast1"
$REPOSITORY = "asx-financials"
$SERVICE = "asx-financials-api"
$JOB = "asx-financials-migrate"
$SERVICE_ACCOUNT_NAME = "asx-financials-run"
$SERVICE_ACCOUNT_EMAIL = "$SERVICE_ACCOUNT_NAME@$PROJECT_ID.iam.gserviceaccount.com"
$IMAGE = "$REGION-docker.pkg.dev/$PROJECT_ID/$REPOSITORY/$SERVICE:latest"
$DATABASE_URL = "postgresql+psycopg://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require"
```

Enable services and create base resources:

```powershell
gcloud config set project $PROJECT_ID

gcloud services enable `
  artifactregistry.googleapis.com `
  cloudbuild.googleapis.com `
  iam.googleapis.com `
  run.googleapis.com `
  secretmanager.googleapis.com

gcloud artifacts repositories create $REPOSITORY `
  --repository-format=docker `
  --location=$REGION `
  --description="Container images for ASX Financials"

gcloud iam service-accounts create $SERVICE_ACCOUNT_NAME `
  --display-name="ASX Financials Cloud Run"

gcloud projects add-iam-policy-binding $PROJECT_ID `
  --member="serviceAccount:$SERVICE_ACCOUNT_EMAIL" `
  --role="roles/secretmanager.secretAccessor"
```

Store the database URL in Secret Manager:

```powershell
Set-Content -Path .gcp-database-url.txt -Value $DATABASE_URL -NoNewline

gcloud secrets create asx-financials-database-url `
  --replication-policy=automatic

gcloud secrets versions add asx-financials-database-url `
  --data-file=.gcp-database-url.txt

Remove-Item .gcp-database-url.txt
```

Build, migrate, and deploy:

```powershell
gcloud builds submit --tag $IMAGE

gcloud run jobs create $JOB `
  --image $IMAGE `
  --region $REGION `
  --service-account $SERVICE_ACCOUNT_EMAIL `
  --set-secrets DATABASE_URL=asx-financials-database-url:latest `
  --set-env-vars APP_ENV=production,RUN_MIGRATIONS_ON_STARTUP=false,YAHOO_REQUEST_TIMEOUT_SECONDS=30,DATABASE_POOL_SIZE=2,DATABASE_MAX_OVERFLOW=0,DATABASE_POOL_TIMEOUT_SECONDS=30,DATABASE_POOL_RECYCLE_SECONDS=1800,DATABASE_CONNECT_TIMEOUT_SECONDS=10 `
  --command uv `
  --args run,alembic,upgrade,head

gcloud run jobs execute $JOB --region $REGION --wait

gcloud run deploy $SERVICE `
  --image $IMAGE `
  --region $REGION `
  --service-account $SERVICE_ACCOUNT_EMAIL `
  --allow-unauthenticated `
  --port 8080 `
  --min-instances 0 `
  --max-instances 2 `
  --concurrency 10 `
  --timeout 900 `
  --cpu 1 `
  --memory 512Mi `
  --set-secrets DATABASE_URL=asx-financials-database-url:latest `
  --set-env-vars APP_ENV=production,RUN_MIGRATIONS_ON_STARTUP=false,YAHOO_REQUEST_TIMEOUT_SECONDS=30,DATABASE_POOL_SIZE=2,DATABASE_MAX_OVERFLOW=0,DATABASE_POOL_TIMEOUT_SECONDS=30,DATABASE_POOL_RECYCLE_SECONDS=1800,DATABASE_CONNECT_TIMEOUT_SECONDS=10
```

### Verify the deployment

```powershell
$SERVICE_URL = gcloud run services describe $SERVICE `
  --region $REGION `
  --format="value(status.url)"

Invoke-RestMethod "$SERVICE_URL/health"
```

You can then test a real endpoint, for example:

```powershell
Invoke-RestMethod "$SERVICE_URL/companies/BHP"
```

### Rollout checklist

1. Build and push the new image with `gcloud builds submit`.
2. Update and execute the migration job if the release changes the schema.
3. Deploy the new Cloud Run revision with `gcloud run deploy`.
4. Verify `/health` and one application endpoint.

## Notes

- Financial statement payloads and raw provider payloads are stored in PostgreSQL `jsonb`.
- Successful snapshots are append-only and deduplicated by ticker, statement type, frequency, and source period key.
- Failed or null provider responses do not overwrite the last successful stored values.
- Supabase remains compatible because it is PostgreSQL-based.
