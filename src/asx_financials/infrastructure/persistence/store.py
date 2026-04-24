import json
import re
from dataclasses import asdict
from datetime import UTC, date, datetime
from hashlib import sha256
from typing import Any, cast
from uuid import uuid4

from pymongo import ASCENDING, DESCENDING, MongoClient, ReturnDocument
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from asx_financials.domain.enums import IngestionRunStatus, StatementFrequency, StatementType
from asx_financials.domain.models import (
    AsxListedCompany,
    CompanyDetails,
    CompanyProfileSnapshot,
    FinancialStatementSnapshot,
    LatestIngestionRun,
    PersistedIngestionOutcome,
    RawSourcePayload,
    SegmentFailure,
    StatementAvailability,
    StatementPreview,
    TickerUniverseSyncResult,
)
from asx_financials.domain.value_objects import AsxTicker


def create_mongo_data_store(mongodb_uri: str, database_name: str) -> "MongoFinancialDataStore":
    client: MongoClient = MongoClient(mongodb_uri)
    return MongoFinancialDataStore(client[database_name])


class MongoFinancialDataStore:
    def __init__(self, database: Database) -> None:
        self._database = database
        self._indexes_ensured = False

    @property
    def _tickers(self) -> Collection:
        return self._database["tickers"]

    @property
    def _ingestion_runs(self) -> Collection:
        return self._database["ingestion_runs"]

    @property
    def _statement_snapshots(self) -> Collection:
        return self._database["statement_snapshots"]

    @property
    def _financial_facts(self) -> Collection:
        return self._database["financial_facts"]

    @property
    def _raw_source_payloads(self) -> Collection:
        return self._database["raw_source_payloads"]

    @property
    def _ticker_universe_sync_runs(self) -> Collection:
        return self._database["ticker_universe_sync_runs"]

    def sync_ticker_universe(
        self,
        *,
        companies: list[AsxListedCompany],
        source_url: str,
        fetched_at_utc: datetime,
        invalid_count: int = 0,
    ) -> TickerUniverseSyncResult:
        self._ensure_indexes_once()
        sync_run_id = str(uuid4())
        started_at = _utcnow()
        seen_tickers = {company.ticker for company in companies}
        inserted_count = 0
        updated_count = 0
        reactivated_count = 0
        unchanged_count = 0

        self._ticker_universe_sync_runs.insert_one(
            {
                "syncRunId": sync_run_id,
                "sourceUrl": source_url,
                "startedAt": started_at,
                "completedAt": None,
                "status": "running",
                "counts": {},
            }
        )

        for company in companies:
            existing = self._tickers.find_one({"ticker": company.ticker})
            if existing is None:
                inserted_count += 1
            elif existing.get("status") == "inactive" or not existing.get("listedOnAsx", False):
                reactivated_count += 1
            elif _ticker_csv_fields_changed(existing, company, source_url):
                updated_count += 1
            else:
                unchanged_count += 1

            self._tickers.update_one(
                {"ticker": company.ticker},
                {
                    "$set": {
                        "ticker": company.ticker,
                        "yahooSymbol": AsxTicker(company.ticker).yahoo_symbol,
                        "sourceName": "asx_listed_companies_csv",
                        "companyName": company.company_name,
                        "exchangeName": "ASX",
                        "industryGroup": company.industry_group,
                        "status": "active",
                        "listedOnAsx": True,
                        "lastSeenInAsxList": _to_utc_datetime(fetched_at_utc),
                        "lastAsxListSyncAt": _to_utc_datetime(fetched_at_utc),
                        "asxListSourceUrl": source_url,
                        "updatedAt": _to_utc_datetime(fetched_at_utc),
                    },
                    "$unset": {"delistedDetectedAt": ""},
                    "$setOnInsert": {
                        "createdAt": _utcnow(),
                        "firstSeenInAsxList": _to_utc_datetime(fetched_at_utc),
                    },
                },
                upsert=True,
            )

        deactivation_filter = {
            "lastSeenInAsxList": {"$exists": True},
            "ticker": {"$nin": list(seen_tickers)},
            "listedOnAsx": True,
        }
        deactivated_count = self._tickers.update_many(
            deactivation_filter,
            {
                "$set": {
                    "status": "inactive",
                    "listedOnAsx": False,
                    "delistedDetectedAt": _to_utc_datetime(fetched_at_utc),
                    "lastAsxListSyncAt": _to_utc_datetime(fetched_at_utc),
                    "updatedAt": _to_utc_datetime(fetched_at_utc),
                }
            },
        ).modified_count

        result = TickerUniverseSyncResult(
            sync_run_id=sync_run_id,
            source_url=source_url,
            fetched_at_utc=fetched_at_utc,
            seen_count=len(companies),
            inserted_count=inserted_count,
            updated_count=updated_count,
            reactivated_count=reactivated_count,
            deactivated_count=deactivated_count,
            invalid_count=invalid_count,
            unchanged_count=unchanged_count,
        )
        self._ticker_universe_sync_runs.update_one(
            {"syncRunId": sync_run_id},
            {
                "$set": {
                    "completedAt": _utcnow(),
                    "status": "succeeded",
                    "counts": {
                        "seen": result.seen_count,
                        "inserted": result.inserted_count,
                        "updated": result.updated_count,
                        "reactivated": result.reactivated_count,
                        "deactivated": result.deactivated_count,
                        "invalid": result.invalid_count,
                        "unchanged": result.unchanged_count,
                    },
                }
            },
        )
        return result

    def start_ingestion_run(
        self,
        ingestion_run_id: str,
        ticker: AsxTicker,
        yahoo_symbol: str,
        started_at_utc: datetime,
    ) -> None:
        self._ensure_indexes_once()
        self._ingestion_runs.insert_one(
            {
                "runId": ingestion_run_id,
                "runType": "ticker_fundamentals",
                "ticker": ticker.value,
                "yahooSymbol": yahoo_symbol,
                "sourceName": "yfinance",
                "status": IngestionRunStatus.RUNNING.value,
                "startedAt": _to_utc_datetime(started_at_utc),
                "completedAt": None,
                "message": "Ingestion started.",
                "segmentFailures": [],
                "counts": {
                    "storedSnapshots": 0,
                    "rawPayloads": 0,
                    "financialFacts": 0,
                },
            }
        )

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
    ) -> PersistedIngestionOutcome:
        self._ensure_indexes_once()
        inserted_snapshot_count = 0
        stored_raw_payload_count = 0
        stored_fact_count = 0

        if company_profile is not None:
            self._upsert_ticker(company_profile)

        raw_payload_ids: dict[tuple[str, str], str] = {}
        for raw_payload in raw_payloads:
            raw_payload_id = str(uuid4())
            self._raw_source_payloads.insert_one(
                {
                    "rawPayloadId": raw_payload_id,
                    "runId": ingestion_run_id,
                    "ticker": raw_payload.ticker,
                    "yahooSymbol": raw_payload.yahoo_symbol,
                    "sourceName": raw_payload.source_name,
                    "segmentName": raw_payload.segment_name,
                    "payloadHash": _hash_payload(raw_payload.payload),
                    "payload": raw_payload.payload,
                    "fetchedAt": _to_utc_datetime(raw_payload.fetched_at_utc),
                    "createdAt": _utcnow(),
                }
            )
            raw_payload_ids[(raw_payload.source_name, raw_payload.segment_name)] = raw_payload_id
            stored_raw_payload_count += 1

        for snapshot in statement_snapshots:
            raw_payload_ref = raw_payload_ids.get((snapshot.source_name, _segment_name(snapshot)))
            inserted, fact_count = self._insert_statement_snapshot(
                ingestion_run_id,
                snapshot,
                raw_payload_ref,
            )
            inserted_snapshot_count += 1 if inserted else 0
            stored_fact_count += fact_count

        result = self._ingestion_runs.find_one_and_update(
            {"runId": ingestion_run_id},
            {
                "$set": {
                    "ticker": ticker.value,
                    "yahooSymbol": yahoo_symbol,
                    "status": status,
                    "completedAt": _to_utc_datetime(completed_at_utc),
                    "message": message,
                    "segmentFailures": [asdict(failure) for failure in segment_failures],
                    "counts": {
                        "storedSnapshots": inserted_snapshot_count,
                        "rawPayloads": stored_raw_payload_count,
                        "financialFacts": stored_fact_count,
                    },
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if result is None:
            msg = f"Ingestion run {ingestion_run_id} was not found."
            raise RuntimeError(msg)

        return PersistedIngestionOutcome(
            inserted_snapshot_count=inserted_snapshot_count,
            stored_raw_payload_count=stored_raw_payload_count,
        )

    def mark_ingestion_run_failed(
        self,
        ingestion_run_id: str,
        completed_at_utc: datetime,
        message: str,
    ) -> None:
        self._ensure_indexes_once()
        self._ingestion_runs.update_one(
            {"runId": ingestion_run_id},
            {
                "$set": {
                    "status": IngestionRunStatus.FAILED.value,
                    "completedAt": _to_utc_datetime(completed_at_utc),
                    "message": message,
                }
            },
        )

    def get_latest_ingestion(self, ticker: AsxTicker) -> LatestIngestionRun | None:
        self._ensure_indexes_once()
        document = self._ingestion_runs.find_one(
            {"ticker": ticker.value},
            sort=[("startedAt", DESCENDING)],
        )
        if document is None:
            return None

        counts = document.get("counts", {})
        return LatestIngestionRun(
            ingestion_run_id=document["runId"],
            ticker=document["ticker"],
            yahoo_symbol=document["yahooSymbol"],
            status=IngestionRunStatus(document["status"]),
            started_at_utc=_from_datetime(document["startedAt"]),
            completed_at_utc=_from_optional_datetime(document.get("completedAt")),
            message=document["message"],
            stored_snapshot_count=counts.get("storedSnapshots", 0),
            stored_raw_payload_count=counts.get("rawPayloads", 0),
            segment_failures=[
                SegmentFailure(**payload) for payload in document.get("segmentFailures", [])
            ],
        )

    def get_company(self, ticker: AsxTicker) -> CompanyDetails | None:
        self._ensure_indexes_once()
        document = self._tickers.find_one({"ticker": ticker.value})
        if document is None:
            return None

        availability = list(self._build_statement_availability(ticker))
        return CompanyDetails(
            ticker=document["ticker"],
            yahoo_symbol=document["yahooSymbol"],
            source_name=document["sourceName"],
            company_name=document.get("companyName"),
            exchange_name=document.get("exchangeName"),
            currency=document.get("currency"),
            sector=document.get("sector"),
            industry=document.get("industry"),
            country=document.get("country"),
            website=document.get("website"),
            profile_payload=document.get("profilePayload", {}),
            updated_at_utc=_from_datetime(document["updatedAt"]),
            statement_availability=availability,
        )

    def get_latest_statement_previews(self, ticker: AsxTicker) -> list[StatementPreview]:
        self._ensure_indexes_once()
        pipeline: list[dict[str, Any]] = [
            {"$match": {"ticker": ticker.value, "isCurrent": True}},
            {"$sort": {"statementType": 1, "frequency": 1, "periodEnd": -1, "fetchedAt": -1}},
            {
                "$group": {
                    "_id": {"statementType": "$statementType", "frequency": "$frequency"},
                    "document": {"$first": "$$ROOT"},
                }
            },
            {"$replaceRoot": {"newRoot": "$document"}},
            {"$sort": {"statementType": 1, "frequency": 1}},
        ]
        return [
            StatementPreview(
                statement_type=StatementType(document["statementType"]),
                frequency=StatementFrequency(document["frequency"]),
                source_period_end=_from_optional_date(document.get("periodEnd")),
                values=document.get("payload", {}).get("values", {}),
                fetched_at_utc=_from_datetime(document["fetchedAt"]),
            )
            for document in self._statement_snapshots.aggregate(cast(Any, pipeline))
        ]

    def _ensure_indexes_once(self) -> None:
        if self._indexes_ensured:
            return

        self._tickers.create_index([("ticker", ASCENDING)], unique=True)
        self._tickers.create_index([("listedOnAsx", ASCENDING), ("ticker", ASCENDING)])
        self._tickers.create_index([("sector", ASCENDING), ("industry", ASCENDING)])
        self._tickers.create_index([("marketCap", DESCENDING)])

        self._ticker_universe_sync_runs.create_index([("syncRunId", ASCENDING)], unique=True)
        self._ticker_universe_sync_runs.create_index([("startedAt", DESCENDING)])

        self._ingestion_runs.create_index([("runId", ASCENDING)], unique=True)
        self._ingestion_runs.create_index([("ticker", ASCENDING), ("startedAt", DESCENDING)])

        self._statement_snapshots.create_index(
            [
                ("ticker", ASCENDING),
                ("sourceName", ASCENDING),
                ("statementType", ASCENDING),
                ("frequency", ASCENDING),
                ("periodEnd", ASCENDING),
                ("revisionHash", ASCENDING),
            ],
            unique=True,
        )
        self._statement_snapshots.create_index(
            [
                ("ticker", ASCENDING),
                ("statementType", ASCENDING),
                ("frequency", ASCENDING),
                ("periodEnd", DESCENDING),
                ("isCurrent", ASCENDING),
            ]
        )

        self._financial_facts.create_index(
            [
                ("metricKey", ASCENDING),
                ("frequency", ASCENDING),
                ("periodEnd", DESCENDING),
                ("isCurrent", ASCENDING),
                ("value", ASCENDING),
            ]
        )
        self._financial_facts.create_index(
            [
                ("ticker", ASCENDING),
                ("metricKey", ASCENDING),
                ("frequency", ASCENDING),
                ("periodEnd", DESCENDING),
            ]
        )

        self._raw_source_payloads.create_index([("runId", ASCENDING)])
        self._raw_source_payloads.create_index(
            [("ticker", ASCENDING), ("segmentName", ASCENDING), ("fetchedAt", DESCENDING)]
        )

        self._database["market_daily"].create_index(
            [("ticker", ASCENDING), ("tradeDate", ASCENDING)],
            unique=True,
        )
        self._database["market_latest"].create_index([("ticker", ASCENDING)], unique=True)
        self._database["reporting_events"].create_index(
            [("expectedDate", ASCENDING), ("eventType", ASCENDING)]
        )
        self._database["reporting_events"].create_index(
            [("ticker", ASCENDING), ("expectedDate", ASCENDING)]
        )
        self._indexes_ensured = True

    def _upsert_ticker(self, company_profile: CompanyProfileSnapshot) -> None:
        self._tickers.update_one(
            {"ticker": company_profile.ticker},
            {
                "$set": {
                    "ticker": company_profile.ticker,
                    "yahooSymbol": company_profile.yahoo_symbol,
                    "sourceName": company_profile.source_name,
                    "companyName": company_profile.company_name,
                    "exchangeName": company_profile.exchange_name,
                    "currency": company_profile.currency,
                    "sector": company_profile.sector,
                    "industry": company_profile.industry,
                    "country": company_profile.country,
                    "website": company_profile.website,
                    "profilePayload": company_profile.profile_payload,
                    "lastFundamentalAt": _to_utc_datetime(company_profile.fetched_at_utc),
                    "updatedAt": _to_utc_datetime(company_profile.fetched_at_utc),
                },
                "$setOnInsert": {
                    "status": "active",
                    "createdAt": _utcnow(),
                },
            },
            upsert=True,
        )

    def _insert_statement_snapshot(
        self,
        ingestion_run_id: str,
        snapshot: FinancialStatementSnapshot,
        raw_payload_id: str | None,
    ) -> tuple[bool, int]:
        revision_hash = _hash_payload(snapshot.payload)
        period_end = _to_optional_date_key(snapshot.source_period_end)
        snapshot_id = str(uuid4())
        base_filter = {
            "ticker": snapshot.ticker,
            "sourceName": snapshot.source_name,
            "statementType": snapshot.statement_type.value,
            "frequency": snapshot.frequency.value,
            "periodEnd": period_end,
        }
        document = {
            "snapshotId": snapshot_id,
            "runId": ingestion_run_id,
            **base_filter,
            "yahooSymbol": snapshot.yahoo_symbol,
            "sourcePeriodKey": snapshot.source_period_key,
            "fiscalYear": snapshot.source_period_end.year if snapshot.source_period_end else None,
            "fiscalQuarter": _fiscal_quarter(snapshot.source_period_end),
            "revisionHash": revision_hash,
            "isCurrent": True,
            "payload": snapshot.payload,
            "rawPayloadId": raw_payload_id,
            "fetchedAt": _to_utc_datetime(snapshot.fetched_at_utc),
            "createdAt": _utcnow(),
        }

        try:
            self._statement_snapshots.insert_one(document)
        except DuplicateKeyError:
            return False, 0

        self._statement_snapshots.update_many(
            {**base_filter, "snapshotId": {"$ne": snapshot_id}},
            {"$set": {"isCurrent": False}},
        )
        self._financial_facts.update_many(base_filter, {"$set": {"isCurrent": False}})
        fact_documents = _build_fact_documents(snapshot_id, document)
        if fact_documents:
            self._financial_facts.insert_many(fact_documents)

        return True, len(fact_documents)

    def _build_statement_availability(self, ticker: AsxTicker) -> list[StatementAvailability]:
        pipeline: list[dict[str, Any]] = [
            {"$match": {"ticker": ticker.value, "isCurrent": True}},
            {
                "$group": {
                    "_id": {"statementType": "$statementType", "frequency": "$frequency"},
                    "snapshotCount": {"$sum": 1},
                    "latestPeriodEnd": {"$max": "$periodEnd"},
                }
            },
            {"$sort": {"_id.statementType": 1, "_id.frequency": 1}},
        ]
        return [
            StatementAvailability(
                statement_type=StatementType(row["_id"]["statementType"]),
                frequency=StatementFrequency(row["_id"]["frequency"]),
                snapshot_count=row["snapshotCount"],
                latest_source_period_end=_from_optional_date(row.get("latestPeriodEnd")),
            )
            for row in self._statement_snapshots.aggregate(cast(Any, pipeline))
        ]


def _build_fact_documents(
    snapshot_id: str,
    snapshot_document: dict[str, Any],
) -> list[dict[str, Any]]:
    values = snapshot_document.get("payload", {}).get("values", {})
    if not isinstance(values, dict):
        return []

    documents = []
    for metric_label, value in values.items():
        if not isinstance(value, int | float):
            continue
        documents.append(
            {
                "factId": str(uuid4()),
                "ticker": snapshot_document["ticker"],
                "sourceName": snapshot_document["sourceName"],
                "statementSnapshotId": snapshot_id,
                "statementType": snapshot_document["statementType"],
                "frequency": snapshot_document["frequency"],
                "periodEnd": snapshot_document["periodEnd"],
                "metricKey": _metric_key(metric_label),
                "metricLabel": metric_label,
                "value": value,
                "currency": None,
                "unit": None,
                "isCurrent": True,
                "fetchedAt": snapshot_document["fetchedAt"],
                "createdAt": _utcnow(),
            }
        )
    return documents


def _ticker_csv_fields_changed(
    existing: dict[str, Any],
    company: AsxListedCompany,
    source_url: str,
) -> bool:
    return (
        existing.get("companyName") != company.company_name
        or existing.get("industryGroup") != company.industry_group
        or existing.get("exchangeName") != "ASX"
        or existing.get("asxListSourceUrl") != source_url
    )


def _hash_payload(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def _metric_key(value: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    value = re.sub(r"[^A-Za-z0-9]+", "_", value)
    return value.strip("_").lower()


def _segment_name(snapshot: FinancialStatementSnapshot) -> str:
    statement_type = snapshot.statement_type.value.replace("_", "-")
    return f"{statement_type}-{snapshot.frequency.value}"


def _fiscal_quarter(value: date | None) -> int | None:
    if value is None:
        return None
    return ((value.month - 1) // 3) + 1


def _to_optional_date_key(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _from_optional_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _to_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _from_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _from_optional_datetime(value: datetime | None) -> datetime | None:
    return _from_datetime(value) if value is not None else None


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)
