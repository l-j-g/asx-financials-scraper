import pytest

from asx_financials.domain.value_objects import AsxTicker


def test_parse_normalizes_yahoo_suffix() -> None:
    ticker = AsxTicker.parse("bhp.ax")

    assert ticker.value == "BHP"
    assert ticker.yahoo_symbol == "BHP.AX"


@pytest.mark.parametrize("raw_value", ["", " ", "TOO-LONG", "!", "BHP.ASX"])
def test_parse_rejects_invalid_tickers(raw_value: str) -> None:
    with pytest.raises(ValueError):
        AsxTicker.parse(raw_value)
