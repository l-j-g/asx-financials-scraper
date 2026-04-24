import csv
from io import StringIO
from urllib.request import Request, urlopen

from asx_financials.domain.models import AsxListedCompaniesFetchResult, AsxListedCompany
from asx_financials.domain.value_objects import AsxTicker


class AsxListedCompaniesCsvProvider:
    USER_AGENT = "asx-financials-scraper/0.1"

    def fetch(self, source_url: str) -> AsxListedCompaniesFetchResult:
        request = Request(source_url, headers={"User-Agent": self.USER_AGENT})
        with urlopen(request, timeout=30) as response:
            content = response.read().decode("utf-8-sig")

        return parse_asx_listed_companies_csv(content)


def parse_asx_listed_companies_csv(content: str) -> AsxListedCompaniesFetchResult:
    rows = list(csv.reader(StringIO(content)))
    header_index = next(
        (
            index
            for index, row in enumerate(rows)
            if {"Company name", "ASX code"}.issubset({column.strip() for column in row})
        ),
        None,
    )
    if header_index is None:
        return AsxListedCompaniesFetchResult(companies=[], invalid_count=0)

    reader = csv.DictReader(StringIO(content), fieldnames=rows[header_index])
    companies: list[AsxListedCompany] = []
    invalid_count = 0

    for row in list(reader)[header_index + 1 :]:
        raw_ticker = row.get("ASX code", "")
        try:
            ticker = AsxTicker.parse(raw_ticker).value
        except ValueError:
            invalid_count += 1
            continue

        company_name = (row.get("Company name") or "").strip()
        if not company_name:
            invalid_count += 1
            continue

        industry_group = (row.get("GICS industry group") or "").strip() or None
        companies.append(
            AsxListedCompany(
                ticker=ticker,
                company_name=company_name,
                industry_group=industry_group,
            )
        )

    return AsxListedCompaniesFetchResult(companies=companies, invalid_count=invalid_count)
