# Deploying `stock_trader` On The Swing-Trader VPS

This repo does not provision PostgreSQL, the dashboard, or the relay. It joins the existing `_references/swing_trader` VPS stack and runs two strategy containers:

- `IARIC_v1` via `python -m strategy_iaric`
- `US_ORB_v1` via `python -m strategy_orb`

## Target topology

```text
Ubuntu VPS (all services reachable on 127.0.0.1 via network_mode: host)
|- IB Gateway on host :4002 (swing_trader managed)
|- PostgreSQL on host :5432 (swing_trader managed)
|- Relay on host :8001 (swing_trader/relay, forwards to trading_assistant)
|- Dashboard (swing_trader managed)
|- Docker
|  |- stock_trader_strategy_iaric (network_mode: host)
|  `- stock_trader_strategy_orb  (network_mode: host)
```

## Prerequisites

- The shared `swing_trader` stack is already running on this VPS (IB Gateway, PostgreSQL, relay).
- You have the same DB credentials used by the shared PostgreSQL instance.

## 1. Prepare the repo

```bash
cd /opt/trading
git clone <YOUR_REPO_URL> stock_trader
cd stock_trader
cp .env.example .env
```

Fill in `.env` with the real credentials and account details:

| Variable | Notes |
| --- | --- |
| `ALGO_TRADER_ENV` | Usually `paper` or `live` on the VPS |
| `DB_*` | Must match the shared `swing_trader` Postgres service |
| `IB_HOST` / `IB_PORT` / `IB_ACCOUNT_ID` | Point at the host IB Gateway |
| `IB_CLIENT_ID_IARIC` | Unique client ID for `IARIC_v1` |
| `IB_CLIENT_ID_US_ORB` | Unique client ID for `US_ORB_v1` |
| `STOCK_TRADER_DEPLOY_MODE` | `both` by default; override to `iaric` or `us_orb` for solo launches |
| `STOCK_TRADER_CAPITAL_ALLOCATION_IARIC_PCT` | Capital share for `IARIC_v1` when `STOCK_TRADER_DEPLOY_MODE=both` |
| `STOCK_TRADER_CAPITAL_ALLOCATION_US_ORB_PCT` | Capital share for `US_ORB_v1` when `STOCK_TRADER_DEPLOY_MODE=both` |
| `INSTRUMENTATION_RELAY_URL` | `http://127.0.0.1:8001/events` (hardcoded in docker-compose, `.env` value ignored) |
| `INSTRUMENTATION_HMAC_SECRET` | **Required in paper/live.** Shared HMAC secret matching the relay's `secrets.json["stock_trader"]`. Containers refuse to start without it. |

Lock the file down after editing:

```bash
chmod 600 .env
```

When both strategies run together, the capital split comes from the two allocation variables above. For example, `50 / 50` means each strategy sizes from half of the fetched account NAV. In solo mode, the launched strategy automatically uses `100%` of account capital and ignores the split.

## 2. Build the image

```bash
docker compose -f infra/docker-compose.yml build
```

## 3. Start both strategies on the VPS

```bash
docker compose -f infra/docker-compose.yml up -d
```

## 4. Start a single strategy when needed

Single-strategy launches use the same compose file with an env override:

```bash
STOCK_TRADER_DEPLOY_MODE=iaric docker compose -f infra/docker-compose.yml up -d strategy_iaric
STOCK_TRADER_DEPLOY_MODE=us_orb docker compose -f infra/docker-compose.yml up -d strategy_orb
```

If you start a strategy that is excluded by `STOCK_TRADER_DEPLOY_MODE`, the container exits immediately with a clear error instead of silently using the wrong capital budget.

## 5. Verify the deployment

Check container status:

```bash
docker compose -f infra/docker-compose.yml ps
```

Tail logs:

```bash
docker compose -f infra/docker-compose.yml logs -f strategy_iaric
docker compose -f infra/docker-compose.yml logs -f strategy_orb
```

Verify shared services from a container:

```bash
docker exec stock_trader_strategy_iaric python -c "import socket; s=socket.socket(); s.connect(('127.0.0.1', 4002)); print('ib ok'); s.close()"
docker exec stock_trader_strategy_iaric python -c "import socket; s=socket.socket(); s.connect(('127.0.0.1', 5432)); print('db ok'); s.close()"
docker exec stock_trader_strategy_iaric python -c "import socket; s=socket.socket(); s.connect(('127.0.0.1', 8001)); print('relay ok'); s.close()"
```

Expected signals:

- Strategy heartbeats appear in the shared dashboard.
- Trade, order, missed-opportunity, snapshot, and heartbeat files accumulate under `/app/instrumentation/data`.
- The relay in `_references/swing_trader/relay/` receives signed events and forwards them to `_references/trading_assistant/`.

## Operations

| Action | Command |
| --- | --- |
| Restart `IARIC_v1` | `docker compose -f infra/docker-compose.yml restart strategy_iaric` |
| Restart `US_ORB_v1` | `docker compose -f infra/docker-compose.yml restart strategy_orb` |
| Stop both | `docker compose -f infra/docker-compose.yml down` |
| Rebuild after updates | `git pull && docker compose -f infra/docker-compose.yml build && docker compose -f infra/docker-compose.yml up -d` |

## Troubleshooting

| Problem | Check |
| --- | --- |
| IB connection fails | Host IB Gateway is running and `IB_CLIENT_ID_*` values are unique |
| DB connection fails | PostgreSQL is running on host (`ss -tlnp | grep 5432`) and `DB_HOST=127.0.0.1` in `.env` |
| Relay forwarding fails | Host relay is running on port `8001` and `INSTRUMENTATION_HMAC_SECRET` matches `secrets.json["stock_trader"]` |
| Strategy data not persisted | Confirm both `/app/data/<strategy>` and `/app/instrumentation/data` volumes are mounted |
