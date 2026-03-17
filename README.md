# Stock Trader

Automated intraday equity trading system running two independent strategies via Interactive Brokers. Deploys as Docker containers alongside an existing swing_trader VPS stack, sharing IB Gateway, PostgreSQL, dashboard, and relay infrastructure.

## Architecture

Each strategy runs in its own container with a unique IB client ID. Both write to shared PostgreSQL tables so the dashboard picks them up automatically. An instrumentation sidecar in each container handles diagnostics, trade logging, regime classification, and event forwarding.

## Strategies

### IARIC v1 — Intraday Accumulation-Reversal with Institutional Consideration

**Session:** 09:30–16:00 ET (all-day) &bull; **Max positions:** 8

IARIC trades pullback-and-reclaim setups on a curated watchlist of 20–40 liquid stocks. It watches for intraday drops — either a fast panic flush (3%+ in under 15 min) or a slower drift exhaustion (2%+ over 60 min) — then waits for price to reclaim the setup low with institutional sponsorship before entering.

**Edge:** The alpha comes from detecting when institutional selling pressure has exhausted. Three independent signals — sponsor flow (strong vs stale accumulation), micropressure proxy (volume surge + close-to-prior-close ratio), and a direct flow proxy — feed a confidence model that gates entries. A RED reading (distribution detected on any signal) blocks the trade entirely; GREEN (2+ accumulative signals) gets full size. The strategy is essentially front-running the reversal that occurs when forced/panic selling dries up and patient institutional buyers step in, confirmed by microstructure evidence rather than price alone.

Additional regime filtering (VIX percentile, sector breadth, market tier classification) scales position sizing and acceptance bar requirements, ensuring the strategy reduces exposure when broad conditions don't support mean-reversion setups.

### US_ORB v1 — U.S. Opening Range Breakout

**Session:** 09:35–11:15 ET (early day only) &bull; **Max positions:** 4

US_ORB dynamically scans for stocks exhibiting abnormal opening participation — top % gainers and hot-by-volume names — then builds a 15-minute opening range (09:35–09:50) and trades confirmed breakouts above that range.

**Edge:** The alpha exploits the opening participation anomaly: stocks trading at 3x+ their normal first-15-minute dollar volume (`surge >= 3.0`) with relative volume above 2.2x are experiencing an outsized attention event — retail FOMO, short covering, or institutional rotation. The strategy doesn't chase the initial move; instead it requires a structured acceptance sequence (breakout → pullback → support hold near VWAP/OR high → reclaim) that filters for genuine institutional absorption versus unsupported retail spikes. A quality scoring model (surge, RVOL, 90-second aggressor imbalance, relative strength, spread) non-linearly sizes positions from 0.5x to 1.25x base risk, concentrating capital in the highest-conviction setups.

A Volatility Danger Model (VDM) replaces simple LULD band checks with a points-based scoring system that tracks PastLimit ticks, halts, spread blowouts, and VWAP extension to gate entries and reduce size in deteriorating microstructure conditions. Flow regime overlay (SPY + QQQ aggressor delta) further adjusts sizing and trail tightness.

## Project Structure

```
stock_trader/
├── strategy_iaric/          # IARIC strategy code
├── strategy_orb/            # US_ORB strategy code
├── shared/                  # OMS, risk, market data, deployment services
├── instrumentation/         # Diagnostics, trade logging, regime classifier
├── config/                  # Contracts, routing, IBKR profiles
├── infra/                   # Dockerfile, docker-compose, deploy guide
├── tests/                   # Unit and integration tests
├── docs/                    # Strategy specs, deployment guide, integration docs
└── _references/             # Sister project source (swing_trader, momentum_trader)
```

## Quick Start

```bash
cp .env.example .env         # fill in credentials and config
docker compose -f infra/docker-compose.yml up -d
```

See [`docs/implementation.md`](docs/implementation.md) for the full deployment walkthrough and [`infra/DEPLOY.md`](infra/DEPLOY.md) for the quick-reference deployment checklist.

## Configuration

Key environment variables (see `.env.example` for full list):

| Variable | Purpose |
|----------|---------|
| `IBKR_HOST` / `IBKR_PORT` | IB Gateway connection |
| `STRATEGY_MODE` | `paper` or `live` |
| `PAPER_CAPITAL` | Starting equity for paper trading (e.g. `5000`) |
| `IARIC_CAPITAL_PCT` / `ORB_CAPITAL_PCT` | Capital split between strategies (default 50/50) |
| `DB_*` | PostgreSQL connection for shared dashboard |
| `RELAY_*` | Event relay endpoint and HMAC credentials |

## Testing

```bash
pytest
```
