from __future__ import annotations

from dataclasses import dataclass, field


class VeriStockDBError(Exception):
    """Base error for import failures."""


class DataPollutionError(VeriStockDBError):
    """Source shape, header, or schema pollution."""


class CircuitBreakerTripped(VeriStockDBError):
    """Blank or invalid source value that must stop import."""


@dataclass(frozen=True)
class ValidationError:
    severity: str
    code: str
    message: str
    sample_stock_id: str | None = None
    sample_value: str | None = None


@dataclass(frozen=True)
class CloseRow:
    trade_date: str
    stock_id: str
    stock_name: str
    market: str
    open: int
    high: int
    low: int
    close: int
    volume: int
    amount: int
    transactions: int


@dataclass(frozen=True)
class PreviousClose:
    close: int
    trade_date: str | None = None


@dataclass(frozen=True)
class DataEvent:
    event_type: str
    trade_date: str
    stock_id: str
    stock_name: str | None
    market: str
    source_open: str | None = None
    source_high: str | None = None
    source_low: str | None = None
    source_close: str | None = None
    stored_open: int | None = None
    stored_high: int | None = None
    stored_low: int | None = None
    stored_close: int | None = None
    reference_period: str | None = None
    reference_value: int | None = None
    note: str | None = None


@dataclass
class ValidationOutcome:
    rows: list[CloseRow] = field(default_factory=list)
    errors: list[ValidationError] = field(default_factory=list)
    events: list[DataEvent] = field(default_factory=list)
    status: str = "OK"
    excluded_count: int = 0

    @property
    def ok(self) -> bool:
        return self.status in {"OK", "FIXED"} and not self.errors
