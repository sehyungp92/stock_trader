# Stock Trader

Automated U.S. equity trading stack running three live strategies through Interactive Brokers. Each strategy runs as its own process/container, shares the same OMS and instrumentation stack, and sizes from an allocation-aware slice of account NAV.

## Strategies

- `IARIC_v1`: all-day intraday accumulation-reversal strategy.
- `US_ORB_v1`: opening-range breakout strategy for the early session.
- `ALCB_v1`: AVWAP Leader Compression Breakout campaign strategy with nightly selection, 30m execution, multi-day management, long/short support, and OMS-managed stops/partials/adds.

## Structure

```text
stock_trader/
|- strategy_iaric/
|- strategy_orb/
|- strategy_alcb/
|- shared/
|- instrumentation/
|- config/
|- infra/
|- docs/
`- tests/
```

## Quick Start

```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml up -d
```

## Capital Allocation

`STOCK_TRADER_DEPLOY_MODE=both` now means all three live strategies run together. If no allocation overrides are supplied, capital defaults to an equal-third split:

- `STOCK_TRADER_CAPITAL_ALLOCATION_IARIC_PCT`
- `STOCK_TRADER_CAPITAL_ALLOCATION_US_ORB_PCT`
- `STOCK_TRADER_CAPITAL_ALLOCATION_ALCB_PCT`

When any of those are set in combined mode, all three must sum to `100`.

Solo launches are also supported:

- `STOCK_TRADER_DEPLOY_MODE=iaric`
- `STOCK_TRADER_DEPLOY_MODE=us_orb`
- `STOCK_TRADER_DEPLOY_MODE=alcb`

In solo mode, the selected strategy uses `100%` of account capital.

## Configuration

Key variables live in [.env.example](/Users/sehyu/Documents/Other/Projects/stock_trader/.env.example):

- `IB_CLIENT_ID_IARIC`
- `IB_CLIENT_ID_US_ORB`
- `IB_CLIENT_ID_ALCB`
- `STOCK_TRADER_PAPER_CAPITAL`
- `STOCK_TRADER_DEPLOY_MODE`
- `STOCK_TRADER_CAPITAL_ALLOCATION_*`
- `DB_*`
- `INSTRUMENTATION_*`

## Testing

```bash
pytest
```

See [infra/DEPLOY.md](/Users/sehyu/Documents/Other/Projects/stock_trader/infra/DEPLOY.md) for VPS deployment details.
