import warnings
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
from typing import Any, cast

import pandas as pd
import yfinance as yf

from asx_financials.domain.enums import StatementFrequency, StatementType
from asx_financials.domain.models import (
    CompanyProfileSnapshot,
    FinancialStatementSnapshot,
    ProviderFetchResult,
    RawSourcePayload,
    SegmentFailure,
)
from asx_financials.domain.value_objects import AsxTicker

PANDAS4_WARNING = getattr(pd.errors, "Pandas4Warning", FutureWarning)


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _normalize_scalar(value: Any) -> Any:
    if value is None:
        return None

    if hasattr(value, "item"):
        try:
            value = value.item()
        except ValueError:
            pass

    if isinstance(value, pd.Timestamp):
        if value.tzinfo is None:
            value = value.tz_localize(UTC)
        else:
            value = value.tz_convert(UTC)
        return value.isoformat()

    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()

    if isinstance(value, date):
        return value.isoformat()

    if isinstance(value, dict):
        return {str(key): _normalize_scalar(inner) for key, inner in value.items()}

    if isinstance(value, list):
        return [_normalize_scalar(item) for item in value]

    if pd.isna(value):
        return None

    return value


def _dataframe_to_raw_payload(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "columns": [str(column) for column in frame.columns.tolist()],
        "index": [str(index) for index in frame.index.tolist()],
        "values": {
            str(column): {
                str(index): _normalize_scalar(value) for index, value in frame[column].items()
            }
            for column in frame.columns
        },
    }


def _column_to_period_end(column: Any) -> date | None:
    if isinstance(column, pd.Timestamp):
        return column.date()

    if isinstance(column, datetime):
        return column.date()

    if isinstance(column, date):
        return column

    parsed = cast(Any, pd.to_datetime(column, errors="coerce"))
    if pd.isna(parsed):
        return None

    return cast(date, parsed.date())


def _payload_hash(payload: dict[str, Any]) -> str:
    return sha256(repr(payload).encode("utf-8")).hexdigest()[:16]


def _run_yfinance_without_pandas4_warning(callback: Callable[[], Any]) -> Any:
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r".*Timestamp\.utcnow is deprecated.*",
            category=PANDAS4_WARNING,
            module=r"yfinance\..*",
        )
        return callback()


@dataclass(frozen=True, slots=True)
class StatementModuleDefinition:
    segment_name: str
    statement_type: StatementType
    frequency: StatementFrequency
    accessor_name: str


class YFinanceProvider:
    SOURCE_NAME = "yfinance"

    MODULES = (
        StatementModuleDefinition(
            segment_name="income-statement-annual",
            statement_type=StatementType.INCOME_STATEMENT,
            frequency=StatementFrequency.ANNUAL,
            accessor_name="get_income_stmt",
        ),
        StatementModuleDefinition(
            segment_name="income-statement-quarterly",
            statement_type=StatementType.INCOME_STATEMENT,
            frequency=StatementFrequency.QUARTERLY,
            accessor_name="get_income_stmt",
        ),
        StatementModuleDefinition(
            segment_name="balance-sheet-annual",
            statement_type=StatementType.BALANCE_SHEET,
            frequency=StatementFrequency.ANNUAL,
            accessor_name="get_balance_sheet",
        ),
        StatementModuleDefinition(
            segment_name="balance-sheet-quarterly",
            statement_type=StatementType.BALANCE_SHEET,
            frequency=StatementFrequency.QUARTERLY,
            accessor_name="get_balance_sheet",
        ),
        StatementModuleDefinition(
            segment_name="cash-flow-annual",
            statement_type=StatementType.CASH_FLOW,
            frequency=StatementFrequency.ANNUAL,
            accessor_name="get_cash_flow",
        ),
        StatementModuleDefinition(
            segment_name="cash-flow-quarterly",
            statement_type=StatementType.CASH_FLOW,
            frequency=StatementFrequency.QUARTERLY,
            accessor_name="get_cash_flow",
        ),
    )

    def fetch(
        self,
        ticker: AsxTicker,
        include_annual: bool,
        include_quarterly: bool,
    ) -> ProviderFetchResult:
        yahoo_ticker = yf.Ticker(ticker.yahoo_symbol)
        fetched_at_utc = _utcnow()

        raw_payloads: list[RawSourcePayload] = []
        failures: list[SegmentFailure] = []

        info = self._safe_info(yahoo_ticker)
        company_profile = self._build_company_profile(
            ticker=ticker,
            fetched_at_utc=fetched_at_utc,
            info=info,
            raw_payloads=raw_payloads,
            failures=failures,
        )

        statement_snapshots: list[FinancialStatementSnapshot] = []
        for module in self.MODULES:
            if module.frequency is StatementFrequency.ANNUAL and not include_annual:
                continue
            if module.frequency is StatementFrequency.QUARTERLY and not include_quarterly:
                continue

            frame = self._fetch_statement_frame(yahoo_ticker, module)
            if frame is None or frame.empty:
                failures.append(SegmentFailure(module.segment_name, "Statement data was empty."))
                continue

            raw_payloads.append(
                RawSourcePayload(
                    source_name=self.SOURCE_NAME,
                    ticker=ticker.value,
                    yahoo_symbol=ticker.yahoo_symbol,
                    segment_name=module.segment_name,
                    payload=_dataframe_to_raw_payload(frame),
                    fetched_at_utc=fetched_at_utc,
                )
            )

            statement_snapshots.extend(
                self._build_statement_snapshots(
                    ticker=ticker,
                    fetched_at_utc=fetched_at_utc,
                    frame=frame,
                    module=module,
                )
            )

        return ProviderFetchResult(
            source_name=self.SOURCE_NAME,
            yahoo_symbol=ticker.yahoo_symbol,
            company_profile=company_profile,
            statement_snapshots=statement_snapshots,
            raw_payloads=raw_payloads,
            segment_failures=failures,
        )

    def _safe_info(self, yahoo_ticker: Any) -> dict[str, Any]:
        info = _run_yfinance_without_pandas4_warning(yahoo_ticker.get_info)
        if not isinstance(info, dict):
            return {}
        return {str(key): _normalize_scalar(value) for key, value in info.items()}

    def _build_company_profile(
        self,
        *,
        ticker: AsxTicker,
        fetched_at_utc: datetime,
        info: dict[str, Any],
        raw_payloads: list[RawSourcePayload],
        failures: list[SegmentFailure],
    ) -> CompanyProfileSnapshot | None:
        if not info:
            failures.append(SegmentFailure("company-profile", "Company profile data was empty."))
            return None

        raw_payloads.append(
            RawSourcePayload(
                source_name=self.SOURCE_NAME,
                ticker=ticker.value,
                yahoo_symbol=ticker.yahoo_symbol,
                segment_name="company-profile",
                payload=info,
                fetched_at_utc=fetched_at_utc,
            )
        )

        return CompanyProfileSnapshot(
            source_name=self.SOURCE_NAME,
            ticker=ticker.value,
            yahoo_symbol=ticker.yahoo_symbol,
            company_name=info.get("longName") or info.get("shortName"),
            exchange_name=(
                info.get("fullExchangeName") or info.get("exchange") or info.get("exchangeName")
            ),
            currency=info.get("financialCurrency") or info.get("currency"),
            sector=info.get("sector"),
            industry=info.get("industry"),
            country=info.get("country"),
            website=info.get("website"),
            profile_payload=info,
            fetched_at_utc=fetched_at_utc,
        )

    def _fetch_statement_frame(
        self,
        yahoo_ticker: Any,
        module: StatementModuleDefinition,
    ) -> pd.DataFrame | None:
        accessor = getattr(yahoo_ticker, module.accessor_name)
        frequency = "yearly" if module.frequency is StatementFrequency.ANNUAL else "quarterly"
        frame = _run_yfinance_without_pandas4_warning(
            lambda: accessor(pretty=False, freq=frequency)
        )

        if frame is None:
            return None
        if isinstance(frame, pd.DataFrame):
            return frame
        return pd.DataFrame(frame)

    def _build_statement_snapshots(
        self,
        *,
        ticker: AsxTicker,
        fetched_at_utc: datetime,
        frame: pd.DataFrame,
        module: StatementModuleDefinition,
    ) -> list[FinancialStatementSnapshot]:
        snapshots: list[FinancialStatementSnapshot] = []

        for column in frame.columns:
            period_end = _column_to_period_end(column)
            values = {
                str(index): _normalize_scalar(value)
                for index, value in frame[column].items()
                if _normalize_scalar(value) is not None
            }

            if not values:
                continue

            payload = {
                "periodEnd": period_end.isoformat() if period_end is not None else None,
                "values": values,
            }

            source_period_key = (
                period_end.isoformat() if period_end is not None else _payload_hash(payload)
            )

            snapshots.append(
                FinancialStatementSnapshot(
                    source_name=self.SOURCE_NAME,
                    ticker=ticker.value,
                    yahoo_symbol=ticker.yahoo_symbol,
                    statement_type=module.statement_type,
                    frequency=module.frequency,
                    source_period_key=source_period_key,
                    source_period_end=period_end,
                    payload=payload,
                    fetched_at_utc=fetched_at_utc,
                )
            )

        return snapshots
