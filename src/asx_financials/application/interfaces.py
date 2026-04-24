from datetime import datetime
from typing import Protocol

from asx_financials.domain.models import (
    CompanyDetails,
    CompanyProfileSnapshot,
    FinancialStatementSnapshot,
    LatestIngestionRun,
    PersistedIngestionOutcome,
    ProviderFetchResult,
    RawSourcePayload,
    SegmentFailure,
    StatementPreview,
)
from asx_financials.domain.value_objects import AsxTicker


class Clock(Protocol):
    def utcnow(self) -> datetime: ...


class FinancialDataProvider(Protocol):
    def fetch(
        self,
        ticker: AsxTicker,
        include_annual: bool,
        include_quarterly: bool,
    ) -> ProviderFetchResult: ...


class FinancialDataStore(Protocol):
    def start_ingestion_run(
        self,
        ingestion_run_id: str,
        ticker: AsxTicker,
        yahoo_symbol: str,
        started_at_utc: datetime,
    ) -> None: ...

    def complete_ingestion_run(
        self,
        *,
        ingestion_run_id: str,
        ticker: AsxTicker,
        yahoo_symbol: str,
        status: str,
        completed_at_utc: datetime,
        message: str,
        company_profile: CompanyProfileSnapshot | None,
        statement_snapshots: list[FinancialStatementSnapshot],
        raw_payloads: list[RawSourcePayload],
        segment_failures: list[SegmentFailure],
    ) -> PersistedIngestionOutcome: ...

    def mark_ingestion_run_failed(
        self,
        ingestion_run_id: str,
        completed_at_utc: datetime,
        message: str,
    ) -> None: ...

    def get_latest_ingestion(self, ticker: AsxTicker) -> LatestIngestionRun | None: ...

    def get_company(self, ticker: AsxTicker) -> CompanyDetails | None: ...

    def get_latest_statement_previews(self, ticker: AsxTicker) -> list[StatementPreview]: ...


class IngestionUseCase(Protocol):
    def ingest(self, command) -> object: ...


class ReadUseCase(Protocol):
    def get_latest_ingestion(self, ticker: str) -> object: ...

    def get_company(self, ticker: str) -> object: ...

    def get_latest_statement_previews(self, ticker: str) -> object: ...
