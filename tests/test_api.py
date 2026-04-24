from datetime import UTC, datetime

from fastapi.testclient import TestClient

from asx_financials.api.app import ServiceContainer, create_app
from asx_financials.application.services import TickerReadService
from asx_financials.config import get_settings
from asx_financials.domain.enums import IngestionRunStatus
from asx_financials.domain.models import (
    CompanyDetails,
    IngestionExecutionResult,
    LatestIngestionRun,
    TickerUniverseSyncResult,
)


class StubIngestionService:
    def ingest(self, command):
        return IngestionExecutionResult(
            ingestion_run_id="run-1",
            ticker=command.ticker,
            yahoo_symbol=f"{command.ticker}.AX",
            status=IngestionRunStatus.SUCCEEDED,
            started_at_utc=datetime(2026, 4, 24, tzinfo=UTC),
            completed_at_utc=datetime(2026, 4, 24, tzinfo=UTC),
            inserted_snapshot_count=1,
            stored_raw_payload_count=1,
            segment_failures=[],
            message="ok",
        )


class StubTickerUniverseService:
    def initialize(self, command):
        return TickerUniverseSyncResult(
            sync_run_id="sync-1",
            source_url=command.source_url,
            fetched_at_utc=datetime(2026, 4, 24, tzinfo=UTC),
            seen_count=2,
            inserted_count=1,
            updated_count=1,
            reactivated_count=0,
            deactivated_count=0,
            invalid_count=0,
            unchanged_count=0,
        )


class StubReadService(TickerReadService):
    def __init__(self) -> None:
        pass

    def get_latest_ingestion(self, ticker: str):
        return LatestIngestionRun(
            ingestion_run_id="run-1",
            ticker=ticker,
            yahoo_symbol=f"{ticker}.AX",
            status=IngestionRunStatus.SUCCEEDED,
            started_at_utc=datetime(2026, 4, 24, tzinfo=UTC),
            completed_at_utc=datetime(2026, 4, 24, tzinfo=UTC),
            message="ok",
            stored_snapshot_count=1,
            stored_raw_payload_count=1,
            segment_failures=[],
        )

    def get_company(self, ticker: str):
        return CompanyDetails(
            ticker=ticker,
            yahoo_symbol=f"{ticker}.AX",
            source_name="yfinance",
            company_name="BHP Group Limited",
            exchange_name="ASX",
            currency="AUD",
            sector="Materials",
            industry="Mining",
            country="Australia",
            website="https://www.bhp.com",
            profile_payload={"longName": "BHP Group Limited"},
            updated_at_utc=datetime(2026, 4, 24, tzinfo=UTC),
            statement_availability=[],
        )


def test_ingestion_endpoint_returns_success(monkeypatch) -> None:
    monkeypatch.setenv("MONGODB_URI", "mongodb://localhost:27017")
    get_settings.cache_clear()
    app = create_app()
    app.state.services = ServiceContainer(
        ingestion_service=StubIngestionService(),
        ticker_universe_service=StubTickerUniverseService(),
        read_service=StubReadService(),
    )

    client = TestClient(app)
    response = client.post("/ingestions/BHP")

    assert response.status_code == 200
    assert response.json()["ticker"] == "BHP"


def test_company_endpoint_returns_company(monkeypatch) -> None:
    monkeypatch.setenv("MONGODB_URI", "mongodb://localhost:27017")
    get_settings.cache_clear()
    app = create_app()
    app.state.services = ServiceContainer(
        ingestion_service=StubIngestionService(),
        ticker_universe_service=StubTickerUniverseService(),
        read_service=StubReadService(),
    )

    client = TestClient(app)
    response = client.get("/companies/BHP")

    assert response.status_code == 200
    assert response.json()["company_name"] == "BHP Group Limited"


def test_initialise_tickers_endpoint_returns_counts(monkeypatch) -> None:
    monkeypatch.setenv("MONGODB_URI", "mongodb://localhost:27017")
    get_settings.cache_clear()
    app = create_app()
    app.state.services = ServiceContainer(
        ingestion_service=StubIngestionService(),
        ticker_universe_service=StubTickerUniverseService(),
        read_service=StubReadService(),
    )

    client = TestClient(app)
    response = client.post("/tickers/initialise")

    assert response.status_code == 200
    assert response.json()["sync_run_id"] == "sync-1"
    assert response.json()["seen_count"] == 2
