from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from asx_financials.application.interfaces import (
    Clock,
    FinancialDataProvider,
    FinancialDataStore,
    TickerUniverseProvider,
)
from asx_financials.domain.enums import IngestionRunStatus
from asx_financials.domain.models import (
    CompanyDetails,
    IngestionExecutionResult,
    LatestIngestionRun,
    ProviderFetchResult,
    StatementPreview,
    TickerUniverseSyncResult,
)
from asx_financials.domain.value_objects import AsxTicker

DEFAULT_ASX_LISTED_COMPANIES_URL = "https://www.asx.com.au/asx/research/ASXListedCompanies.csv"


@dataclass(frozen=True, slots=True)
class IngestTickerCommand:
    ticker: str
    include_annual: bool = True
    include_quarterly: bool = True


@dataclass(frozen=True, slots=True)
class InitializeTickerUniverseCommand:
    source_url: str = DEFAULT_ASX_LISTED_COMPANIES_URL


class SystemClock:
    def utcnow(self) -> datetime:
        return datetime.now(tz=UTC)


class TickerIngestionService:
    def __init__(
        self,
        data_provider: FinancialDataProvider,
        data_store: FinancialDataStore,
        clock: Clock,
    ) -> None:
        self._data_provider = data_provider
        self._data_store = data_store
        self._clock = clock

    def ingest(self, command: IngestTickerCommand) -> IngestionExecutionResult:
        if not command.include_annual and not command.include_quarterly:
            msg = "At least one reporting period must be requested."
            raise ValueError(msg)

        ticker = AsxTicker.parse(command.ticker)
        started_at_utc = self._clock.utcnow()
        ingestion_run_id = str(uuid4())
        yahoo_symbol = ticker.yahoo_symbol

        self._data_store.start_ingestion_run(
            ingestion_run_id=ingestion_run_id,
            ticker=ticker,
            yahoo_symbol=yahoo_symbol,
            started_at_utc=started_at_utc,
        )

        try:
            provider_result = self._data_provider.fetch(
                ticker=ticker,
                include_annual=command.include_annual,
                include_quarterly=command.include_quarterly,
            )

            status = self._determine_status(provider_result)
            completed_at_utc = self._clock.utcnow()
            message = self._build_message(provider_result, status)

            persisted = self._data_store.complete_ingestion_run(
                ingestion_run_id=ingestion_run_id,
                ticker=ticker,
                yahoo_symbol=provider_result.yahoo_symbol,
                status=status.value,
                completed_at_utc=completed_at_utc,
                message=message,
                company_profile=provider_result.company_profile,
                statement_snapshots=provider_result.statement_snapshots,
                raw_payloads=provider_result.raw_payloads,
                segment_failures=provider_result.segment_failures,
            )

            return IngestionExecutionResult(
                ingestion_run_id=ingestion_run_id,
                ticker=ticker.value,
                yahoo_symbol=provider_result.yahoo_symbol,
                status=status,
                started_at_utc=started_at_utc,
                completed_at_utc=completed_at_utc,
                inserted_snapshot_count=persisted.inserted_snapshot_count,
                stored_raw_payload_count=persisted.stored_raw_payload_count,
                segment_failures=provider_result.segment_failures,
                message=message,
            )
        except Exception as exc:
            self._data_store.mark_ingestion_run_failed(
                ingestion_run_id=ingestion_run_id,
                completed_at_utc=self._clock.utcnow(),
                message=str(exc),
            )
            raise

    @staticmethod
    def _determine_status(provider_result: ProviderFetchResult) -> IngestionRunStatus:
        if not provider_result.has_any_successful_data:
            return IngestionRunStatus.FAILED

        if provider_result.segment_failures:
            return IngestionRunStatus.PARTIALLY_SUCCEEDED

        return IngestionRunStatus.SUCCEEDED

    @staticmethod
    def _build_message(
        provider_result: ProviderFetchResult,
        status: IngestionRunStatus,
    ) -> str:
        if status is IngestionRunStatus.FAILED:
            if provider_result.segment_failures:
                return (
                    "Provider returned no usable data. "
                    f"{len(provider_result.segment_failures)} segment(s) failed."
                )
            return "Provider returned no usable data."

        if status is IngestionRunStatus.PARTIALLY_SUCCEEDED:
            return (
                "Ingestion completed with "
                f"{len(provider_result.segment_failures)} segment failure(s)."
            )

        return "Ingestion completed successfully."


class TickerUniverseInitializationService:
    def __init__(
        self,
        ticker_universe_provider: TickerUniverseProvider,
        data_store: FinancialDataStore,
        clock: Clock,
    ) -> None:
        self._ticker_universe_provider = ticker_universe_provider
        self._data_store = data_store
        self._clock = clock

    def initialize(self, command: InitializeTickerUniverseCommand) -> TickerUniverseSyncResult:
        fetch_result = self._ticker_universe_provider.fetch(command.source_url)
        return self._data_store.sync_ticker_universe(
            companies=fetch_result.companies,
            source_url=command.source_url,
            fetched_at_utc=self._clock.utcnow(),
            invalid_count=fetch_result.invalid_count,
        )


class TickerReadService:
    def __init__(self, data_store: FinancialDataStore) -> None:
        self._data_store = data_store

    def get_latest_ingestion(self, ticker: str) -> LatestIngestionRun | None:
        return self._data_store.get_latest_ingestion(AsxTicker.parse(ticker))

    def get_company(self, ticker: str) -> CompanyDetails | None:
        return self._data_store.get_company(AsxTicker.parse(ticker))

    def get_latest_statement_previews(self, ticker: str) -> list[StatementPreview]:
        return self._data_store.get_latest_statement_previews(AsxTicker.parse(ticker))
