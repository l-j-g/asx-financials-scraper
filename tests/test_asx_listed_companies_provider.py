from asx_financials.infrastructure.providers.asx_listed_companies_provider import (
    parse_asx_listed_companies_csv,
)


def test_parse_asx_listed_companies_csv_returns_valid_rows() -> None:
    result = parse_asx_listed_companies_csv(
        "\n".join(
            [
                "Company name,ASX code,GICS industry group",
                "BHP Group Limited,BHP,Materials",
                "Commonwealth Bank of Australia,CBA,Banks",
            ]
        )
    )

    assert result.invalid_count == 0
    assert [company.ticker for company in result.companies] == ["BHP", "CBA"]
    assert result.companies[0].company_name == "BHP Group Limited"
    assert result.companies[0].industry_group == "Materials"


def test_parse_asx_listed_companies_csv_counts_invalid_rows() -> None:
    result = parse_asx_listed_companies_csv(
        "\n".join(
            [
                "Company name,ASX code,GICS industry group",
                "BHP Group Limited,BHP,Materials",
                "Bad Ticker,TOO-LONG,Materials",
                ",CBA,Banks",
            ]
        )
    )

    assert result.invalid_count == 2
    assert [company.ticker for company in result.companies] == ["BHP"]


def test_parse_asx_listed_companies_csv_skips_title_line() -> None:
    result = parse_asx_listed_companies_csv(
        "\n".join(
            [
                "ASX listed companies",
                "Company name,ASX code,GICS industry group",
                "BHP Group Limited,BHP,Materials",
            ]
        )
    )

    assert result.invalid_count == 0
    assert [company.ticker for company in result.companies] == ["BHP"]
