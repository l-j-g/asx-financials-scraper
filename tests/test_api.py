from datetime import UTC, datetime

from fastapi.testclient import TestClient

from asx_financials.api.app import ServiceContainer, create_app
from asx_financials.application.services import TickerReadService
from asx_financials.domain.enums import IngestionRunStatus
from asx_financials.domain.models import (
    CompanyDetails,
    IngestionExecutionResult,
    LatestIngestionRun,
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


def test_ingestion_endpoint_returns_success() -> None:
    app = create_app()
    app.state.services = ServiceContainer(
        ingestion_service=StubIngestionService(),
        read_service=StubReadService(),
    )

    client = TestClient(app)
    response = client.post("/ingestions/BHP")

    assert response.status_code == 200
    assert response.json()["ticker"] == "BHP"


def test_company_endpoint_returns_company() -> None:
    app = create_app()
    app.state.services = ServiceContainer(
        ingestion_service=StubIngestionService(),
        read_service=StubReadService(),
    )

    client = TestClient(app)
    response = client.get("/companies/BHP")

    assert response.status_code == 200
    assert response.json()["company_name"] == "BHP Group Limited"
