from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from asx_financials.domain.enums import IngestionRunStatus, StatementFrequency, StatementType

JsonDict = dict[str, Any]


@dataclass(frozen=True, slots=True)
class SegmentFailure:
    segment_name: str
    reason: str


@dataclass(frozen=True, slots=True)
class AsxListedCompany:
    ticker: str
    company_name: str
    industry_group: str | None


@dataclass(frozen=True, slots=True)
class AsxListedCompaniesFetchResult:
    companies: list[AsxListedCompany]
    invalid_count: int


@dataclass(frozen=True, slots=True)
class TickerUniverseSyncResult:
    sync_run_id: str
    source_url: str
    fetched_at_utc: datetime
    seen_count: int
    inserted_count: int
    updated_count: int
    reactivated_count: int
    deactivated_count: int
    invalid_count: int
    unchanged_count: int


@dataclass(frozen=True, slots=True)
class CompanyProfileSnapshot:
    source_name: str
    ticker: str
    yahoo_symbol: str
    company_name: str | None
    exchange_name: str | None
    currency: str | None
    sector: str | None
    industry: str | None
    country: str | None
    website: str | None
    profile_payload: JsonDict
    fetched_at_utc: datetime


@dataclass(frozen=True, slots=True)
class FinancialStatementSnapshot:
    source_name: str
    ticker: str
    yahoo_symbol: str
    statement_type: StatementType
    frequency: StatementFrequency
    source_period_key: str
    source_period_end: date | None
    payload: JsonDict
    fetched_at_utc: datetime


@dataclass(frozen=True, slots=True)
class RawSourcePayload:
    source_name: str
    ticker: str
    yahoo_symbol: str
    segment_name: str
    payload: JsonDict
    fetched_at_utc: datetime


@dataclass(frozen=True, slots=True)
class StatementAvailability:
    statement_type: StatementType
    frequency: StatementFrequency
    snapshot_count: int
    latest_source_period_end: date | None


@dataclass(frozen=True, slots=True)
class StatementPreview:
    statement_type: StatementType
    frequency: StatementFrequency
    source_period_end: date | None
    values: JsonDict
    fetched_at_utc: datetime


@dataclass(frozen=True, slots=True)
class ProviderFetchResult:
    source_name: str
    yahoo_symbol: str
    company_profile: CompanyProfileSnapshot | None
    statement_snapshots: list[FinancialStatementSnapshot] = field(default_factory=list)
    raw_payloads: list[RawSourcePayload] = field(default_factory=list)
    segment_failures: list[SegmentFailure] = field(default_factory=list)

    @property
    def has_any_successful_data(self) -> bool:
        return self.company_profile is not None or bool(self.statement_snapshots)


@dataclass(frozen=True, slots=True)
class IngestionExecutionResult:
    ingestion_run_id: str
    ticker: str
    yahoo_symbol: str
    status: IngestionRunStatus
    started_at_utc: datetime
    completed_at_utc: datetime
    inserted_snapshot_count: int
    stored_raw_payload_count: int
    segment_failures: list[SegmentFailure]
    message: str


@dataclass(frozen=True, slots=True)
class PersistedIngestionOutcome:
    inserted_snapshot_count: int
    stored_raw_payload_count: int


@dataclass(frozen=True, slots=True)
class LatestIngestionRun:
    ingestion_run_id: str
    ticker: str
    yahoo_symbol: str
    status: IngestionRunStatus
    started_at_utc: datetime
    completed_at_utc: datetime | None
    message: str
    stored_snapshot_count: int
    stored_raw_payload_count: int
    segment_failures: list[SegmentFailure]


@dataclass(frozen=True, slots=True)
class CompanyDetails:
    ticker: str
    yahoo_symbol: str
    source_name: str
    company_name: str | None
    exchange_name: str | None
    currency: str | None
    sector: str | None
    industry: str | None
    country: str | None
    website: str | None
    profile_payload: JsonDict
    updated_at_utc: datetime
    statement_availability: list[StatementAvailability]
