from datetime import date

import pandas as pd

from asx_financials.domain.enums import StatementFrequency, StatementType
from asx_financials.domain.value_objects import AsxTicker
from asx_financials.infrastructure.providers import yfinance_provider
from asx_financials.infrastructure.providers.yfinance_provider import YFinanceProvider


class StubTicker:
    def get_info(self):
        return {
            "longName": "BHP Group Limited",
            "fullExchangeName": "ASX",
            "currency": "AUD",
            "sector": "Materials",
            "industry": "Mining",
            "country": "Australia",
            "website": "https://www.bhp.com",
        }

    def get_income_stmt(self, pretty: bool = False, freq: str = "yearly"):
        return (
            pd.DataFrame(
                {
                    pd.Timestamp("2024-06-30"): {"TotalRevenue": 100, "NetIncome": 50},
                    pd.Timestamp("2025-03-31"): {"TotalRevenue": 25, "NetIncome": 10},
                }
            )
            if freq == "yearly"
            else pd.DataFrame({pd.Timestamp("2025-03-31"): {"TotalRevenue": 25, "NetIncome": 10}})
        )

    def get_balance_sheet(self, pretty: bool = False, freq: str = "yearly"):
        return pd.DataFrame({pd.Timestamp("2024-06-30"): {"TotalAssets": 200}})

    def get_cash_flow(self, pretty: bool = False, freq: str = "yearly"):
        return pd.DataFrame({pd.Timestamp("2024-06-30"): {"OperatingCashFlow": 80}})


def test_provider_extracts_company_and_statement_snapshots(monkeypatch) -> None:
    monkeypatch.setattr(yfinance_provider.yf, "Ticker", lambda _: StubTicker())
    provider = YFinanceProvider()

    result = provider.fetch(AsxTicker.parse("BHP"), include_annual=True, include_quarterly=True)

    assert result.company_profile is not None
    assert result.company_profile.company_name == "BHP Group Limited"
    assert len(result.statement_snapshots) >= 4
    assert any(
        snapshot.statement_type is StatementType.INCOME_STATEMENT
        and snapshot.frequency is StatementFrequency.QUARTERLY
        and snapshot.source_period_end == date(2025, 3, 31)
        for snapshot in result.statement_snapshots
    )


def test_provider_reports_missing_profile(monkeypatch) -> None:
    class EmptyTicker(StubTicker):
        def get_info(self):
            return {}

    monkeypatch.setattr(yfinance_provider.yf, "Ticker", lambda _: EmptyTicker())
    provider = YFinanceProvider()

    result = provider.fetch(AsxTicker.parse("CSL"), include_annual=True, include_quarterly=False)

    assert result.company_profile is None
    assert any(failure.segment_name == "company-profile" for failure in result.segment_failures)
