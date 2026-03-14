from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from instrumentation.src.pg_bridge import InstrumentedTradeRecorder


@pytest.mark.asyncio
async def test_record_entry_writes_to_pg_before_instrumentation():
    call_order: list[str] = []
    inner = AsyncMock()
    inner.record_entry.side_effect = lambda **kwargs: (call_order.append("inner"), "trade_123")[1]
    kit = MagicMock()
    kit.log_entry.side_effect = lambda **kwargs: call_order.append("kit")

    recorder = InstrumentedTradeRecorder(
        inner,
        kit,
        strategy_id="IARIC_v1",
        strategy_type="strategy_iaric",
    )

    trade_id = await recorder.record_entry(
        strategy_id="IARIC_v1",
        instrument="AAPL",
        direction="LONG",
        quantity=10,
        entry_price=Decimal("101.25"),
        entry_ts=datetime.now(timezone.utc),
        meta={"entry_signal": "reclaim", "entry_signal_strength": 0.8},
    )

    assert trade_id == "trade_123"
    assert call_order == ["inner", "kit"]
    assert kit.log_entry.call_args.kwargs["entry_signal"] == "reclaim"


@pytest.mark.asyncio
async def test_record_entry_swallows_instrumentation_failures():
    inner = AsyncMock()
    inner.record_entry.return_value = "trade_456"
    kit = MagicMock()
    kit.log_entry.side_effect = RuntimeError("boom")

    recorder = InstrumentedTradeRecorder(
        inner,
        kit,
        strategy_id="US_ORB_v1",
        strategy_type="strategy_orb",
    )

    trade_id = await recorder.record_entry(
        strategy_id="US_ORB_v1",
        instrument="MSFT",
        direction="LONG",
        quantity=5,
        entry_price=Decimal("250.10"),
        entry_ts=datetime.now(timezone.utc),
    )

    assert trade_id == "trade_456"
    inner.record_entry.assert_awaited_once()
    kit.log_entry.assert_called_once()


@pytest.mark.asyncio
async def test_record_exit_writes_to_pg_before_instrumentation():
    call_order: list[str] = []

    async def _inner_exit(**kwargs):
        call_order.append("inner")

    inner = AsyncMock()
    inner.record_exit.side_effect = _inner_exit
    kit = MagicMock()
    kit.log_exit.side_effect = lambda **kwargs: call_order.append("kit")

    recorder = InstrumentedTradeRecorder(
        inner,
        kit,
        strategy_id="IARIC_v1",
        strategy_type="strategy_iaric",
    )

    await recorder.record_exit(
        trade_id="trade_123",
        exit_price=Decimal("103.50"),
        exit_ts=datetime.now(timezone.utc),
        exit_reason="EXIT",
        realized_r=Decimal("1.5"),
    )

    assert call_order == ["inner", "kit"]


@pytest.mark.asyncio
async def test_record_exit_swallows_instrumentation_failures():
    inner = AsyncMock()
    inner.record_exit.return_value = None
    kit = MagicMock()
    kit.log_exit.side_effect = RuntimeError("boom")

    recorder = InstrumentedTradeRecorder(
        inner,
        kit,
        strategy_id="US_ORB_v1",
        strategy_type="strategy_orb",
    )

    await recorder.record_exit(
        trade_id="trade_789",
        exit_price=Decimal("99.50"),
        exit_ts=datetime.now(timezone.utc),
        exit_reason="STOP",
        realized_r=Decimal("-1.0"),
    )

    inner.record_exit.assert_awaited_once()
    kit.log_exit.assert_called_once()


@pytest.mark.asyncio
async def test_record_entry_falls_back_to_direct_instrumentation_without_pg():
    kit = MagicMock()
    recorder = InstrumentedTradeRecorder(
        None,
        kit,
        strategy_id="US_ORB_v1",
        strategy_type="strategy_orb",
    )

    trade_id = await recorder.record_entry(
        strategy_id="US_ORB_v1",
        instrument="AAPL",
        direction="LONG",
        quantity=3,
        entry_price=Decimal("101.50"),
        entry_ts=datetime.now(timezone.utc),
        meta={"entry_signal": "breakout"},
    )

    assert trade_id
    kit.log_entry.assert_called_once()
    assert kit.log_entry.call_args.kwargs["trade_id"] == trade_id


@pytest.mark.asyncio
async def test_record_exit_falls_back_to_direct_instrumentation_without_pg():
    kit = MagicMock()
    recorder = InstrumentedTradeRecorder(
        None,
        kit,
        strategy_id="IARIC_v1",
        strategy_type="strategy_iaric",
    )

    await recorder.record_exit(
        trade_id="fallback_trade",
        exit_price=Decimal("99.50"),
        exit_ts=datetime.now(timezone.utc),
        exit_reason="STOP",
        realized_r=Decimal("-1.0"),
    )

    kit.log_exit.assert_called_once()
    assert kit.log_exit.call_args.kwargs["trade_id"] == "fallback_trade"
