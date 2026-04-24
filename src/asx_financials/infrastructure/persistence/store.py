from dataclasses import asdict
from datetime import datetime
from typing import Any

from sqlalchemy import Select, desc, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from asx_financials.domain.enums import IngestionRunStatus, StatementFrequency, StatementType
from asx_financials.domain.models import (
    CompanyDetails,
    CompanyProfileSnapshot,
    FinancialStatementSnapshot,
    LatestIngestionRun,
    PersistedIngestionOutcome,
    RawSourcePayload,
    SegmentFailure,
    StatementAvailability,
    StatementPreview,
)
from asx_financials.domain.value_objects import AsxTicker
from asx_financials.infrastructure.persistence.models import (
    CompanyModel,
    FinancialSnapshotModel,
    IngestionRunModel,
    RawSourcePayloadModel,
)


class SqlAlchemyFinancialDataStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def start_ingestion_run(
        self,
        ingestion_run_id: str,
        ticker: AsxTicker,
        yahoo_symbol: str,
        started_at_utc: datetime,
    ) -> None:
        with self._session_factory() as session:
            session.add(
                IngestionRunModel(
                    id=ingestion_run_id,
                    ticker=ticker.value,
                    yahoo_symbol=yahoo_symbol,
                    started_at_utc=started_at_utc,
                    status=IngestionRunStatus.RUNNING.value,
                    message="Ingestion started.",
                    segment_failures=[],
                    stored_snapshot_count=0,
                    raw_payload_count=0,
                )
            )
            session.commit()

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
        with self._session_factory() as session:
            inserted_snapshot_count = 0
            stored_raw_payload_count = 0

            if company_profile is not None:
                self._upsert_company(session, company_profile)

            for snapshot in statement_snapshots:
                inserted_snapshot_count += self._insert_snapshot(
                    session,
                    ingestion_run_id,
                    snapshot,
                )

            for raw_payload in raw_payloads:
                session.add(
                    RawSourcePayloadModel(
                        ingestion_run_id=ingestion_run_id,
                        ticker=raw_payload.ticker,
                        yahoo_symbol=raw_payload.yahoo_symbol,
                        source_name=raw_payload.source_name,
                        segment_name=raw_payload.segment_name,
                        payload=raw_payload.payload,
                        fetched_at_utc=raw_payload.fetched_at_utc,
                    )
                )
                stored_raw_payload_count += 1

            run = session.get(IngestionRunModel, ingestion_run_id)
            if run is None:
                msg = f"Ingestion run {ingestion_run_id} was not found."
                raise RuntimeError(msg)

            run.yahoo_symbol = yahoo_symbol
            run.completed_at_utc = completed_at_utc
            run.status = status
            run.message = message
            run.segment_failures = [asdict(failure) for failure in segment_failures]
            run.stored_snapshot_count = inserted_snapshot_count
            run.raw_payload_count = stored_raw_payload_count

            session.commit()

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
        with self._session_factory() as session:
            run = session.get(IngestionRunModel, ingestion_run_id)
            if run is None:
                return

            run.completed_at_utc = completed_at_utc
            run.status = IngestionRunStatus.FAILED.value
            run.message = message
            session.commit()

    def get_latest_ingestion(self, ticker: AsxTicker) -> LatestIngestionRun | None:
        statement = (
            select(IngestionRunModel)
            .where(IngestionRunModel.ticker == ticker.value)
            .order_by(desc(IngestionRunModel.started_at_utc))
            .limit(1)
        )

        with self._session_factory() as session:
            model = session.execute(statement).scalar_one_or_none()
            if model is None:
                return None

            return LatestIngestionRun(
                ingestion_run_id=model.id,
                ticker=model.ticker,
                yahoo_symbol=model.yahoo_symbol,
                status=IngestionRunStatus(model.status),
                started_at_utc=model.started_at_utc,
                completed_at_utc=model.completed_at_utc,
                message=model.message,
                stored_snapshot_count=model.stored_snapshot_count,
                stored_raw_payload_count=model.raw_payload_count,
                segment_failures=[SegmentFailure(**payload) for payload in model.segment_failures],
            )

    def get_company(self, ticker: AsxTicker) -> CompanyDetails | None:
        availability_statement: Select[tuple[str, str, int, Any]] = (
            select(
                FinancialSnapshotModel.statement_type,
                FinancialSnapshotModel.frequency,
                func.count(FinancialSnapshotModel.id),
                func.max(FinancialSnapshotModel.source_period_end),
            )
            .where(FinancialSnapshotModel.ticker == ticker.value)
            .group_by(FinancialSnapshotModel.statement_type, FinancialSnapshotModel.frequency)
            .order_by(FinancialSnapshotModel.statement_type, FinancialSnapshotModel.frequency)
        )

        with self._session_factory() as session:
            company = session.get(CompanyModel, ticker.value)
            if company is None:
                return None

            availability_rows = session.execute(availability_statement).all()
            availability = [
                StatementAvailability(
                    statement_type=StatementType(statement_type),
                    frequency=StatementFrequency(frequency),
                    snapshot_count=count,
                    latest_source_period_end=latest_period_end,
                )
                for statement_type, frequency, count, latest_period_end in availability_rows
            ]

            return CompanyDetails(
                ticker=company.ticker,
                yahoo_symbol=company.yahoo_symbol,
                source_name=company.source_name,
                company_name=company.company_name,
                exchange_name=company.exchange_name,
                currency=company.currency,
                sector=company.sector,
                industry=company.industry,
                country=company.country,
                website=company.website,
                profile_payload=company.profile_payload,
                updated_at_utc=company.updated_at_utc,
                statement_availability=availability,
            )

    def get_latest_statement_previews(self, ticker: AsxTicker) -> list[StatementPreview]:
        statement = (
            select(FinancialSnapshotModel)
            .where(FinancialSnapshotModel.ticker == ticker.value)
            .order_by(
                FinancialSnapshotModel.statement_type,
                FinancialSnapshotModel.frequency,
                desc(FinancialSnapshotModel.source_period_end),
                desc(FinancialSnapshotModel.fetched_at_utc),
            )
        )

        with self._session_factory() as session:
            rows = session.execute(statement).scalars().all()

        previews: list[StatementPreview] = []
        seen: set[tuple[str, str]] = set()
        for row in rows:
            key = (row.statement_type, row.frequency)
            if key in seen:
                continue

            values = row.payload.get("values", {})
            if not isinstance(values, dict):
                values = {}

            previews.append(
                StatementPreview(
                    statement_type=StatementType(row.statement_type),
                    frequency=StatementFrequency(row.frequency),
                    source_period_end=row.source_period_end,
                    values=values,
                    fetched_at_utc=row.fetched_at_utc,
                )
            )
            seen.add(key)

        return previews

    @staticmethod
    def _upsert_company(session: Session, company_profile: CompanyProfileSnapshot) -> None:
        model = CompanyModel(
            ticker=company_profile.ticker,
            yahoo_symbol=company_profile.yahoo_symbol,
            source_name=company_profile.source_name,
            company_name=company_profile.company_name,
            exchange_name=company_profile.exchange_name,
            currency=company_profile.currency,
            sector=company_profile.sector,
            industry=company_profile.industry,
            country=company_profile.country,
            website=company_profile.website,
            profile_payload=company_profile.profile_payload,
            updated_at_utc=company_profile.fetched_at_utc,
        )
        session.merge(model)

    @staticmethod
    def _insert_snapshot(
        session: Session,
        ingestion_run_id: str,
        snapshot: FinancialStatementSnapshot,
    ) -> int:
        statement = (
            insert(FinancialSnapshotModel)
            .values(
                ingestion_run_id=ingestion_run_id,
                ticker=snapshot.ticker,
                yahoo_symbol=snapshot.yahoo_symbol,
                source_name=snapshot.source_name,
                statement_type=snapshot.statement_type.value,
                frequency=snapshot.frequency.value,
                source_period_key=snapshot.source_period_key,
                source_period_end=snapshot.source_period_end,
                payload=snapshot.payload,
                fetched_at_utc=snapshot.fetched_at_utc,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    FinancialSnapshotModel.ticker,
                    FinancialSnapshotModel.statement_type,
                    FinancialSnapshotModel.frequency,
                    FinancialSnapshotModel.source_period_key,
                ]
            )
            .returning(FinancialSnapshotModel.id)
        )

        result = session.execute(statement)
        inserted_id = result.scalar_one_or_none()
        return 1 if inserted_id is not None else 0
