"""Cache loading and thin IB data-source bridges."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable

from ib_async import (
    IB,
    ScannerSubscription,
    TickByTickAllLast,
    TickByTickBidAsk,
)

from shared.ibkr_core.mapping.contract_factory import ContractFactory

from .config import PROXY_SYMBOLS, ScannerSettings
from .models import CachedSymbol, MinuteBar, QuoteSnapshot

REQUIRED_CACHE_FIELDS = {
    "symbol",
    "exchange",
    "primary_exchange",
    "currency",
    "tick_size",
    "point_value",
    "adv20",
    "prior_close",
    "sma20",
    "sma60",
    "sma20_slope",
    "atr1m14",
    "opening_value15_baseline_0935_0950",
    "minute_volume_baseline_0935_1115",
}


class CacheValidationError(ValueError):
    """Raised when the universe cache does not match the contract."""


def cache_contract() -> dict[str, Any]:
    return {
        "format": "jsonl",
        "version": 1,
        "required_fields": sorted(REQUIRED_CACHE_FIELDS),
        "optional_fields": [
            "sector",
            "float_shares",
            "float_bucket",
            "catalyst_tag",
            "luld_tier",
            "tech_tag",
            "secondary_universe",
        ],
        "notes": {
            "opening_value15_baseline_0935_0950": "20-day baseline for 09:35-09:50 dollar value",
            "minute_volume_baseline_0935_1115": "Minute-of-day baseline map covering the entry window",
        },
    }


def load_universe_cache(path: str | Path) -> dict[str, CachedSymbol]:
    rows: dict[str, CachedSymbol] = {}
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    with open(path, "r", encoding="utf-8") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            payload = json.loads(line)
            rows[payload["symbol"]] = _parse_cache_row(payload, line_no)
    return rows


def _parse_cache_row(payload: dict[str, Any], line_no: int) -> CachedSymbol:
    missing = REQUIRED_CACHE_FIELDS - payload.keys()
    if missing:
        raise CacheValidationError(f"line {line_no}: missing fields {sorted(missing)}")

    minute_map = payload["minute_volume_baseline_0935_1115"]
    if not isinstance(minute_map, dict) or "09:35" not in minute_map or "11:15" not in minute_map:
        raise CacheValidationError(
            f"line {line_no}: minute_volume_baseline_0935_1115 must be a dict with 09:35 and 11:15 keys"
        )

    try:
        return CachedSymbol(
            symbol=str(payload["symbol"]).upper(),
            exchange=str(payload["exchange"]),
            primary_exchange=str(payload["primary_exchange"]),
            currency=str(payload["currency"]),
            tick_size=float(payload["tick_size"]),
            point_value=float(payload["point_value"]),
            adv20=float(payload["adv20"]),
            prior_close=float(payload["prior_close"]),
            sma20=float(payload["sma20"]),
            sma60=float(payload["sma60"]),
            sma20_slope=float(payload["sma20_slope"]),
            atr1m14=float(payload["atr1m14"]),
            opening_value15_baseline_0935_0950=float(payload["opening_value15_baseline_0935_0950"]),
            minute_volume_baseline_0935_1115={str(key): float(value) for key, value in minute_map.items()},
            sector=str(payload.get("sector", "")),
            float_shares=float(payload["float_shares"]) if payload.get("float_shares") not in (None, "") else None,
            float_bucket=str(payload.get("float_bucket", "")),
            catalyst_tag=str(payload.get("catalyst_tag", "")),
            luld_tier=str(payload.get("luld_tier", "tier_1")),
            tech_tag=bool(payload.get("tech_tag", False)),
            secondary_universe=bool(payload.get("secondary_universe", float(payload["adv20"]) < 20_000_000.0)),
        )
    except (TypeError, ValueError) as exc:
        raise CacheValidationError(f"line {line_no}: {exc}") from exc


@dataclass
class UniversePoolManager:
    cache: dict[str, CachedSymbol]
    cap: int = 20

    def shortlist(self, scanner_symbols: Iterable[str]) -> list[str]:
        unique = []
        seen = set()
        for symbol in scanner_symbols:
            normalized = symbol.upper()
            if normalized in self.cache and normalized not in seen:
                seen.add(normalized)
                unique.append(normalized)
            if len(unique) >= self.cap:
                break
        return unique


class MinuteBarBuilder:
    """Build minute bars from streaming last-trade updates."""

    def __init__(self) -> None:
        self._current_minute: datetime | None = None
        self._open = 0.0
        self._high = 0.0
        self._low = 0.0
        self._close = 0.0
        self._volume = 0.0
        self._dollar_value = 0.0
        self._last_cumulative_volume = 0.0

    def update(self, ts: datetime, price: float, cumulative_volume: float) -> MinuteBar | None:
        minute = ts.replace(second=0, microsecond=0)
        volume_delta = max(0.0, cumulative_volume - self._last_cumulative_volume)
        self._last_cumulative_volume = max(self._last_cumulative_volume, cumulative_volume)

        if self._current_minute is None:
            self._reset(minute, price, volume_delta)
            return None

        if minute == self._current_minute:
            self._high = max(self._high, price)
            self._low = min(self._low, price)
            self._close = price
            self._volume += volume_delta
            self._dollar_value += price * volume_delta
            return None

        closed = MinuteBar(
            ts=self._current_minute,
            open=self._open,
            high=self._high,
            low=self._low,
            close=self._close,
            volume=self._volume,
            dollar_value=self._dollar_value,
        )
        self._reset(minute, price, volume_delta)
        return closed

    def _reset(self, minute: datetime, price: float, volume_delta: float) -> None:
        self._current_minute = minute
        self._open = price
        self._high = price
        self._low = price
        self._close = price
        self._volume = volume_delta
        self._dollar_value = price * volume_delta


class TradeFlowWindow:
    """Signed 90-second dollar imbalance from tick-by-tick data."""

    def __init__(self, window_seconds: int = 90) -> None:
        self._window = timedelta(seconds=window_seconds)
        self._events: deque[tuple[datetime, float]] = deque()

    def update(self, ts: datetime, price: float, size: float, bid: float, ask: float) -> None:
        midpoint = 0.0
        if bid > 0 and ask > 0:
            midpoint = (bid + ask) / 2.0
        signed_value = price * size
        if midpoint > 0:
            if price < midpoint:
                signed_value *= -1
        self._events.append((ts, signed_value))
        self._trim(ts)

    def imbalance(self, now: datetime) -> float:
        self._trim(now)
        total = sum(abs(value) for _, value in self._events)
        if total <= 0:
            return 0.0
        return sum(value for _, value in self._events) / total

    def _trim(self, now: datetime) -> None:
        cutoff = now - self._window
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()


class IBScannerSource:
    """Thin wrapper around one or more IB scanner subscriptions."""

    def __init__(self, ib: IB, settings: ScannerSettings) -> None:
        self._ib = ib
        self._settings = settings
        self._handles = []
        self._queue: asyncio.Queue[list[str]] = asyncio.Queue()
        self._latest: set[str] = set()
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        for scan_code in self._settings.scan_codes:
            handle = self._ib.reqScannerSubscription(
                ScannerSubscription(
                    numberOfRows=self._settings.rows_per_scan,
                    instrument=self._settings.instrument,
                    locationCode=self._settings.location_code,
                    scanCode=scan_code,
                    abovePrice=self._settings.above_price,
                    aboveVolume=self._settings.above_volume,
                    stockTypeFilter=self._settings.stock_type_filter,
                )
            )
            handle.updateEvent += self._on_update
            self._handles.append(handle)

    async def stop(self) -> None:
        if not self._running:
            return
        for handle in self._handles:
            try:
                handle.updateEvent -= self._on_update
            except Exception:
                pass
            self._ib.cancelScannerSubscription(handle)
        self._handles.clear()
        self._running = False

    async def next_update(self) -> list[str]:
        return await self._queue.get()

    def latest_symbols(self) -> list[str]:
        return sorted(self._latest)

    def _on_update(self, rows) -> None:
        symbols = {
            row.contractDetails.contract.symbol.upper()
            for row in rows
            if getattr(row, "contractDetails", None) and getattr(row.contractDetails, "contract", None)
        }
        if symbols:
            self._latest = symbols
            self._queue.put_nowait(sorted(symbols))


class IBMarketDataSource:
    """Light market-data bridge that feeds quotes, bars, and imbalance to the engine."""

    def __init__(
        self,
        ib: IB,
        contract_factory: ContractFactory,
        on_quote: Callable[[str, QuoteSnapshot, float], Any] | Callable[[str, QuoteSnapshot, float], Awaitable[Any]],
        on_bar: Callable[[str, MinuteBar], Any] | Callable[[str, MinuteBar], Awaitable[Any]],
    ) -> None:
        self._ib = ib
        self._factory = contract_factory
        self._on_quote = on_quote
        self._on_bar = on_bar
        self._builders: dict[str, MinuteBarBuilder] = {}
        self._flows: dict[str, TradeFlowWindow] = {}
        self._processed_ticks: dict[str, int] = {}
        self._cumulative_value: dict[str, float] = {}
        self._contracts: dict[str, Any] = {}
        self._instruments: dict[str, Any] = {}
        self._last_quote_ts: dict[str, datetime] = {}
        self._last_midpoints: dict[str, float] = {}
        self._last_spreads: dict[str, float] = {}
        self._quote_expansion_streaks: dict[str, int] = {}
        self._halted_state: dict[str, bool] = {}
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._ib.pendingTickersEvent += self._handle_pending_tickers
        self._running = True

    async def stop(self) -> None:
        if not self._running:
            return
        self._ib.pendingTickersEvent -= self._handle_pending_tickers
        for symbol, contract in list(self._contracts.items()):
            self._ib.cancelTickByTickData(contract, "Last")
            self._ib.cancelTickByTickData(contract, "BidAsk")
            self._ib.cancelMktData(contract)
            self._contracts.pop(symbol, None)
        self._running = False

    async def ensure_symbols(self, instruments: Iterable[Any]) -> None:
        wanted = {instrument.symbol: instrument for instrument in instruments}
        for symbol in list(self._contracts):
            if symbol not in wanted and symbol not in PROXY_SYMBOLS:
                contract = self._contracts.pop(symbol)
                self._ib.cancelTickByTickData(contract, "Last")
                self._ib.cancelTickByTickData(contract, "BidAsk")
                self._ib.cancelMktData(contract)
                self._builders.pop(symbol, None)
                self._flows.pop(symbol, None)
                self._processed_ticks.pop(symbol, None)
                self._cumulative_value.pop(symbol, None)
                self._instruments.pop(symbol, None)
                self._last_quote_ts.pop(symbol, None)
                self._last_midpoints.pop(symbol, None)
                self._last_spreads.pop(symbol, None)
                self._quote_expansion_streaks.pop(symbol, None)
                self._halted_state.pop(symbol, None)

        for symbol, instrument in wanted.items():
            if symbol in self._contracts:
                continue
            contract, _ = await self._factory.resolve(symbol=instrument.root or instrument.symbol, instrument=instrument)
            self._contracts[symbol] = contract
            self._instruments[symbol] = instrument
            self._builders[symbol] = MinuteBarBuilder()
            self._flows[symbol] = TradeFlowWindow()
            self._processed_ticks[symbol] = 0
            self._cumulative_value[symbol] = 0.0
            self._quote_expansion_streaks[symbol] = 0
            self._halted_state[symbol] = False
            self._ib.reqMktData(contract)
            self._ib.reqTickByTickData(contract, "Last")
            self._ib.reqTickByTickData(contract, "BidAsk")

    def _handle_pending_tickers(self, tickers) -> None:
        now = datetime.now(timezone.utc)
        for ticker in tickers:
            contract = getattr(ticker, "contract", None)
            symbol = getattr(contract, "symbol", "").upper()
            if symbol not in self._contracts:
                continue

            last = float(getattr(ticker, "last", 0.0) or 0.0)
            bid = float(getattr(ticker, "bid", 0.0) or 0.0)
            ask = float(getattr(ticker, "ask", 0.0) or 0.0)
            volume = float(getattr(ticker, "volume", 0.0) or 0.0)
            trades = getattr(ticker, "tickByTicks", []) or []
            processed = self._processed_ticks.get(symbol, 0)

            bid_past_low = False
            ask_past_high = False
            past_limit = False
            saw_trade = False

            for trade in trades[processed:]:
                if isinstance(trade, TickByTickAllLast):
                    trade_ts = trade.time if isinstance(trade.time, datetime) else now
                    price = float(trade.price)
                    size = float(trade.size)
                    saw_trade = saw_trade or (price > 0 and size > 0)
                    self._flows[symbol].update(trade_ts, price, size, bid, ask)
                    self._cumulative_value[symbol] += price * size
                    past_limit = past_limit or bool(getattr(getattr(trade, "tickAttribLast", None), "pastLimit", False))
                elif isinstance(trade, TickByTickBidAsk):
                    attrs = getattr(trade, "tickAttribBidAsk", None)
                    bid_past_low = bid_past_low or bool(getattr(attrs, "bidPastLow", False))
                    ask_past_high = ask_past_high or bool(getattr(attrs, "askPastHigh", False))

            self._processed_ticks[symbol] = len(trades)
            imbalance = self._flows[symbol].imbalance(now)
            midpoint = ((bid + ask) / 2.0) if bid > 0 and ask > 0 else 0.0
            previous_midpoint = self._last_midpoints.get(symbol, 0.0)
            previous_quote_ts = self._last_quote_ts.get(symbol)
            elapsed = max(0.0, (now - previous_quote_ts).total_seconds()) if previous_quote_ts else 0.0
            quote_gap_pct = (abs(midpoint - previous_midpoint) / previous_midpoint) if midpoint > 0 and previous_midpoint > 0 else 0.0
            midpoint_velocity = (quote_gap_pct / elapsed) if elapsed > 0 else 0.0
            spread_pct = ((ask - bid) / midpoint) if midpoint > 0 and ask > 0 and bid > 0 else 0.0
            previous_spread = self._last_spreads.get(symbol, 0.0)
            expansion_streak = self._quote_expansion_streaks.get(symbol, 0)
            if spread_pct > previous_spread and not saw_trade:
                expansion_streak += 1
            elif saw_trade or spread_pct <= previous_spread:
                expansion_streak = 0

            halted = bool(getattr(ticker, "halted", 0) or getattr(ticker, "delayedHalted", 0))
            resumed_from_halt = self._halted_state.get(symbol, False) and not halted
            self._halted_state[symbol] = halted
            self._last_midpoints[symbol] = midpoint if midpoint > 0 else previous_midpoint
            self._last_spreads[symbol] = spread_pct
            self._last_quote_ts[symbol] = now
            self._quote_expansion_streaks[symbol] = expansion_streak

            quote = QuoteSnapshot(
                ts=now,
                bid=bid,
                ask=ask,
                last=last or ((bid + ask) / 2.0 if bid > 0 and ask > 0 else 0.0),
                bid_size=float(getattr(ticker, "bidSize", 0.0) or 0.0),
                ask_size=float(getattr(ticker, "askSize", 0.0) or 0.0),
                cumulative_volume=volume,
                cumulative_value=self._cumulative_value.get(symbol, 0.0),
                vwap=float(getattr(ticker, "vwap", 0.0) or 0.0) or None,
                is_halted=halted,
                past_limit=past_limit,
                bid_past_low=bid_past_low,
                ask_past_high=ask_past_high,
                spread_pct=spread_pct,
                quote_gap_pct=quote_gap_pct,
                midpoint_velocity=midpoint_velocity,
                quote_expansion_streak=expansion_streak,
                resumed_from_halt=resumed_from_halt,
            )
            self._dispatch(self._on_quote(symbol, quote, imbalance))

            price = quote.last if quote.last > 0 else (quote.bid + quote.ask) / 2.0
            if price <= 0:
                continue
            bar = self._builders[symbol].update(now, price, quote.cumulative_volume)
            if bar is not None:
                self._dispatch(self._on_bar(symbol, bar))

    @staticmethod
    def _dispatch(result: Any) -> None:
        if inspect.isawaitable(result):
            asyncio.create_task(result)
