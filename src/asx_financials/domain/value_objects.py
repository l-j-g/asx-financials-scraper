import re
from dataclasses import dataclass

TICKER_PATTERN = re.compile(r"^[A-Z0-9]{2,6}$")


@dataclass(frozen=True, slots=True)
class AsxTicker:
    value: str

    @property
    def yahoo_symbol(self) -> str:
        return f"{self.value}.AX"

    @classmethod
    def parse(cls, raw_value: str) -> "AsxTicker":
        candidate = raw_value.strip().upper()
        if candidate.endswith(".AX"):
            candidate = candidate[:-3]

        if not TICKER_PATTERN.fullmatch(candidate):
            msg = "Ticker must contain 2 to 6 alphanumeric ASX characters."
            raise ValueError(msg)

        return cls(candidate)
