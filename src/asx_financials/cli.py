import argparse
import json
import os
import sys
from dataclasses import asdict
from typing import TextIO

from asx_financials.application.services import (
    IngestTickerCommand,
    SystemClock,
    TickerIngestionService,
    TickerReadService,
)
from asx_financials.config import get_settings
from asx_financials.domain.enums import IngestionRunStatus
from asx_financials.domain.models import CompanyDetails, LatestIngestionRun, StatementPreview
from asx_financials.infrastructure.persistence.database import create_session_factory
from asx_financials.infrastructure.persistence.store import SqlAlchemyFinancialDataStore
from asx_financials.infrastructure.providers.yfinance_provider import YFinanceProvider

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
CYAN = "\033[36m"

PREVIEW_KEYS = {
    "income_statement": (
        "TotalRevenue",
        "OperatingRevenue",
        "GrossProfit",
        "EBITDA",
        "EBIT",
        "NetIncome",
        "BasicEPS",
    ),
    "balance_sheet": (
        "TotalAssets",
        "TotalLiabilitiesNetMinorityInterest",
        "TotalEquityGrossMinorityInterest",
        "CashAndCashEquivalents",
        "TotalDebt",
        "NetDebt",
    ),
    "cash_flow": (
        "OperatingCashFlow",
        "FreeCashFlow",
        "CapitalExpenditure",
        "InvestingCashFlow",
        "FinancingCashFlow",
        "EndCashPosition",
    ),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="asx-financials")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="Ingest one ASX ticker.")
    ingest_parser.add_argument("ticker")
    ingest_parser.add_argument("--annual-only", action="store_true")
    ingest_parser.add_argument("--quarterly-only", action="store_true")
    ingest_parser.add_argument("--json", action="store_true", help="Print JSON payload.")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command != "ingest":
        parser.error("Unknown command.")

    include_annual = not args.quarterly_only
    include_quarterly = not args.annual_only

    settings = get_settings()
    session_factory = create_session_factory(
        settings.database_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout_seconds=settings.database_pool_timeout_seconds,
        pool_recycle_seconds=settings.database_pool_recycle_seconds,
        connect_timeout_seconds=settings.database_connect_timeout_seconds,
    )
    store = SqlAlchemyFinancialDataStore(session_factory)
    provider = YFinanceProvider()
    service = TickerIngestionService(provider, store, SystemClock())
    read_service = TickerReadService(store)
    console_stream = sys.stderr if args.json else sys.stdout

    _emit_console(
        console_stream,
        f"Starting ingestion for {args.ticker.upper()} "
        f"(annual={include_annual}, quarterly={include_quarterly})",
        color=BLUE,
    )

    result = service.ingest(
        IngestTickerCommand(
            ticker=args.ticker,
            include_annual=include_annual,
            include_quarterly=include_quarterly,
        )
    )

    latest_ingestion = read_service.get_latest_ingestion(result.ticker)
    company = read_service.get_company(result.ticker)
    previews = read_service.get_latest_statement_previews(result.ticker)

    _emit_result_summary(console_stream, result, company)
    _emit_company_summary(console_stream, company)
    _emit_statement_summary(console_stream, company)
    _emit_data_preview(console_stream, previews)
    _emit_latest_summary(console_stream, latest_ingestion)
    _emit_failures(console_stream, result)

    if args.json:
        payload = {
            "result": asdict(result),
            "latest_ingestion": asdict(latest_ingestion) if latest_ingestion is not None else None,
            "company": asdict(company) if company is not None else None,
            "statement_previews": [asdict(preview) for preview in previews],
        }
        print(json.dumps(payload, default=str))


def _emit_result_summary(
    stream: TextIO,
    result,
    company: CompanyDetails | None,
) -> None:
    status_color = _status_color(result.status)
    company_name = company.company_name if company and company.company_name else "Unknown company"
    snapshot_label = (
        f"new_snapshots={result.inserted_snapshot_count}"
        if result.inserted_snapshot_count
        else "new_snapshots=0 (already stored)"
    )
    _emit_console(
        stream,
        (
            f"{result.status.value.upper()}: {result.ticker} "
            f"({company_name}) | {snapshot_label} "
            f"| raw_payloads={result.stored_raw_payload_count}"
        ),
        color=status_color,
        bold=True,
    )


def _emit_company_summary(stream: TextIO, company: CompanyDetails | None) -> None:
    if company is None:
        _emit_console(stream, "No company profile stored.", color=YELLOW)
        return

    _emit_console(
        stream,
        (
            f"Profile: exchange={company.exchange_name or 'n/a'} | "
            f"currency={company.currency or 'n/a'} | "
            f"sector={company.sector or 'n/a'} | "
            f"industry={company.industry or 'n/a'} | "
            f"country={company.country or 'n/a'}"
        ),
        color=CYAN,
    )
    if company.website:
        _emit_console(stream, f"Website: {company.website}", color=CYAN)


def _emit_statement_summary(stream: TextIO, company: CompanyDetails | None) -> None:
    if company is None or not company.statement_availability:
        _emit_console(stream, "Statements: none stored.", color=YELLOW)
        return

    _emit_console(stream, "Statements:", color=BLUE, bold=True)
    for availability in company.statement_availability:
        latest_period = (
            availability.latest_source_period_end.isoformat()
            if availability.latest_source_period_end is not None
            else "n/a"
        )
        _emit_console(
            stream,
            (
                f"  - {availability.statement_type.value}/{availability.frequency.value}: "
                f"count={availability.snapshot_count}, latest={latest_period}"
            ),
            color=DIM,
        )


def _emit_data_preview(stream: TextIO, previews: list[StatementPreview]) -> None:
    if not previews:
        return

    _emit_console(stream, "Latest data preview:", color=BLUE, bold=True)
    for preview in previews:
        latest_period = (
            preview.source_period_end.isoformat() if preview.source_period_end else "n/a"
        )
        summary = _format_preview_values(preview)
        _emit_console(
            stream,
            (
                f"  - {preview.statement_type.value}/{preview.frequency.value} "
                f"({latest_period}): {summary}"
            ),
            color=CYAN,
        )


def _emit_latest_summary(stream: TextIO, latest_ingestion: LatestIngestionRun | None) -> None:
    if latest_ingestion is None:
        return

    completed_at = (
        latest_ingestion.completed_at_utc.isoformat()
        if latest_ingestion.completed_at_utc
        else "n/a"
    )
    _emit_console(
        stream,
        (
            f"Run: id={latest_ingestion.ingestion_run_id} | "
            f"started={latest_ingestion.started_at_utc.isoformat()} | "
            f"completed={completed_at}"
        ),
        color=DIM,
    )


def _emit_failures(stream: TextIO, result) -> None:
    if not result.segment_failures:
        return

    for failure in result.segment_failures:
        _emit_console(
            stream,
            f"Segment failure: {failure.segment_name} - {failure.reason}",
            color=YELLOW,
        )


def _emit_console(
    stream: TextIO,
    message: str,
    *,
    color: str = "",
    bold: bool = False,
) -> None:
    prefix = "[asx-financials]"
    if _supports_color(stream):
        style = f"{BOLD if bold else ''}{color}"
        if style:
            print(f"{style}{prefix}{RESET} {message}", file=stream, flush=True)
            return

    print(f"{prefix} {message}", file=stream, flush=True)


def _status_color(status: IngestionRunStatus) -> str:
    if status is IngestionRunStatus.SUCCEEDED:
        return GREEN
    if status is IngestionRunStatus.PARTIALLY_SUCCEEDED:
        return YELLOW
    if status is IngestionRunStatus.FAILED:
        return RED
    return BLUE


def _format_preview_values(preview: StatementPreview) -> str:
    selected: list[str] = []
    seen_keys: set[str] = set()
    candidate_keys = PREVIEW_KEYS.get(preview.statement_type.value, ())

    for key in candidate_keys:
        value = preview.values.get(key)
        if value is None:
            continue

        selected.append(f"{key}={_format_value(value)}")
        seen_keys.add(key)
        if len(selected) == 3:
            return " | ".join(selected)

    for key in sorted(preview.values):
        if key in seen_keys:
            continue

        value = preview.values.get(key)
        if value is None:
            continue

        selected.append(f"{key}={_format_value(value)}")
        if len(selected) == 3:
            break

    if not selected:
        return "no previewable values"

    return " | ".join(selected)


def _format_value(value: object) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        if value.is_integer():
            return f"{int(value):,}"
        return f"{value:,.2f}"
    return str(value)


def _supports_color(stream: TextIO) -> bool:
    if os.getenv("NO_COLOR"):
        return False
    return hasattr(stream, "isatty") and stream.isatty()
