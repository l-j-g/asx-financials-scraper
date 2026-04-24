"""Initial schema for ASX financial ingestion."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260424_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("yahoo_symbol", sa.String(length=24), nullable=False),
        sa.Column("source_name", sa.String(length=64), nullable=False),
        sa.Column("company_name", sa.String(length=255), nullable=True),
        sa.Column("exchange_name", sa.String(length=128), nullable=True),
        sa.Column("currency", sa.String(length=16), nullable=True),
        sa.Column("sector", sa.String(length=128), nullable=True),
        sa.Column("industry", sa.String(length=128), nullable=True),
        sa.Column("country", sa.String(length=128), nullable=True),
        sa.Column("website", sa.String(length=255), nullable=True),
        sa.Column("profile_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("ticker"),
    )

    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("yahoo_symbol", sa.String(length=24), nullable=False),
        sa.Column("started_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("segment_failures", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("stored_snapshot_count", sa.Integer(), nullable=False),
        sa.Column("raw_payload_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ingestion_runs_ticker"), "ingestion_runs", ["ticker"], unique=False)

    op.create_table(
        "financial_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ingestion_run_id", sa.String(length=36), nullable=False),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("yahoo_symbol", sa.String(length=24), nullable=False),
        sa.Column("source_name", sa.String(length=64), nullable=False),
        sa.Column("statement_type", sa.String(length=32), nullable=False),
        sa.Column("frequency", sa.String(length=16), nullable=False),
        sa.Column("source_period_key", sa.String(length=64), nullable=False),
        sa.Column("source_period_end", sa.Date(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fetched_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["ingestion_run_id"], ["ingestion_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "ticker",
            "statement_type",
            "frequency",
            "source_period_key",
            name="uq_financial_snapshots_period",
        ),
    )
    op.create_index(
        op.f("ix_financial_snapshots_ticker"),
        "financial_snapshots",
        ["ticker"],
        unique=False,
    )

    op.create_table(
        "raw_source_payloads",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ingestion_run_id", sa.String(length=36), nullable=False),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("yahoo_symbol", sa.String(length=24), nullable=False),
        sa.Column("source_name", sa.String(length=64), nullable=False),
        sa.Column("segment_name", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fetched_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["ingestion_run_id"], ["ingestion_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_raw_source_payloads_ticker"),
        "raw_source_payloads",
        ["ticker"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_raw_source_payloads_ticker"), table_name="raw_source_payloads")
    op.drop_table("raw_source_payloads")
    op.drop_index(op.f("ix_financial_snapshots_ticker"), table_name="financial_snapshots")
    op.drop_table("financial_snapshots")
    op.drop_index(op.f("ix_ingestion_runs_ticker"), table_name="ingestion_runs")
    op.drop_table("ingestion_runs")
    op.drop_table("companies")
