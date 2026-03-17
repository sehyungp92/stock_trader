# ATRSS Multi-Strategy Trading System — Implementation Guide

Complete guide to deploying, operating, and extending the swing_trader system: five algorithmic strategies (ATRSS, S5_PB, S5_DUAL, SWING_BREAKOUT_V3, AKC_HELIX) with shared OMS, risk management, IB Gateway integration, PostgreSQL persistence, a purpose-built Next.js trading dashboard, and a full instrumentation layer with relay service for centralized analysis.

## Table of Contents

**Deployment Guide** (follow in order):
- [Part 1: Current System Status](#part-1-current-system-status)
- [Part 2: Pre-Deployment Checklist](#part-2-pre-deployment-checklist-local)
- [Part 3: VPS Provisioning](#part-3-vps-provisioning)
- [Part 4: IB Gateway Installation](#part-4-ib-gateway-installation-headless)
- [Part 5: Docker Stack Deployment](#part-5-docker-stack-deployment)
- [Part 6: Relay Service Deployment](#part-6-relay-service-deployment)
- [Part 7: Post-Deployment Verification](#part-7-post-deployment-verification)
- [Part 8: Cron Jobs & Maintenance](#part-8-cron-jobs--maintenance)
- [Part 9: Monitoring & Alerting](#part-9-monitoring--alerting)
- [Part 10: Paper-to-Live Transition](#part-10-paper-to-live-transition)
- [Part 11: Operational Runbook](#part-11-operational-runbook)

**Appendices** (reference material, consult as needed):
- [Appendix A: Trading Dashboard](#appendix-a-trading-dashboard)
- [Appendix B: Instrumentation Layer](#appendix-b-instrumentation-layer)
- [Appendix C: Relay Service Internals](#appendix-c-relay-service-internals)
- [Appendix D: Key Configuration Reference](#appendix-d-key-configuration-reference)
- [Appendix E: Future Work](#appendix-e-future-work)
- [Appendix F: Implementation History](#appendix-f-implementation-history)

---

## Part 1: Current System Status

### What's Implemented

| Component | Status | Description |
|-----------|--------|-------------|
| **ATRSS** (Strategy 1) | Complete | ETF Trend-Regime Swing System — pullback/breakout/reverse entries, pyramiding (add-on A/B), chandelier trailing, partial profit-taking, stall detection |
| **S5_PB** (Strategy 4 — Pullback) | Complete | Keltner Momentum Pullback — daily-bar Keltner channel + ROC momentum on IBIT, ATR trailing stops |
| **S5_DUAL** (Strategy 4 — Dual) | Complete | Keltner Momentum Dual — daily-bar dual-entry mode on GLD/IBIT, RSI-gated longs, Keltner channel |
| **AKC_HELIX** (Strategy 2) | Complete | Divergence-based swing system — 4H/1H hidden & classic divergence, MACD momentum, corridor-cap trailing, DIRTY re-entry |
| **SWING_BREAKOUT_V3** (Strategy 3) | Complete | Compression breakout system — squeeze detection, displacement scoring, adaptive L-bucket sizing, re-entry campaigns |
| **OMS** | Complete | Intent-based order management — risk gateway, execution router, fill processor, timeout monitor, event bus, reconciliation |
| **Risk Management** | Complete | Pre-trade risk gates — daily stops, heat caps, priority reservations, per-strategy ceilings, event blackout calendar, market holiday/half-day calendar |
| **IBKR Adapter** | Complete | Async IB Gateway integration — order submission, fill handling, position reconciliation, error classification, heartbeat |
| **Cross-Strategy Coordination** | Complete | Shared coordinator — ATRSS entry tightens Helix stop to BE, size boost (1.25x) when ATRSS active same direction |
| **Backtesting** | Complete | Full framework — SimBroker, portfolio engine, walk-forward, Bayesian optimization, ablation, per-strategy diagnostics |
| **Docker Infrastructure** | Complete | PostgreSQL 16, Next.js dashboard, portfolio launcher, and optional standalone strategy profiles |
| **Trading Dashboard** | Complete | Next.js 14 dark terminal UI — live positions, orders, strategy health, equity curve, 30-second polling |
| **Database** | Complete | PostgreSQL with role separation (admin/writer/reader), auto-init SQL, retention jobs |
| **Instrumentation** | Complete | Event logging layer — market snapshots, trade events, missed opportunities, process quality scoring, daily aggregates, regime classification, sidecar forwarder |
| **Relay Service** | Complete | FastAPI event buffer — HMAC-signed ingest, SQLite store, watermark-based pull/ack, rate limiting, systemd/nginx deployment templates |

### Architecture

```
Ubuntu VPS
├── IB Gateway (systemd service, port 4002)
│   └── via IBC 3.19.0 + Xvfb (headless)
│
├── Trading Relay (systemd service, port 8001)
│   ├── FastAPI + SQLite event buffer
│   ├── HMAC auth (ingest) + API key auth (pull/admin)
│   └── nginx HTTPS proxy ──► home orchestrator (trading_assistant) polls
│
├── Instrumentation (shared context, in-process with main_multi.py)
│   ├── Per-strategy kits (×5) write to 15 JSONL dirs
│   ├── Sidecar (background thread) ──► relay:8001
│   └── 5 asyncio tasks: daily snapshot, backfill, heartbeat, config check, post-exit
│
└── Docker
    ├── postgres (127.0.0.1:5432)
    │   └── trading database (OMS state, trades, risk)
    ├── dashboard (port 3000, Next.js 14)
    ├── atrss strategy ────────► IB Gateway:4002
    ├── akc_helix strategy ────► IB Gateway:4002
    ├── swing_breakout strategy ► IB Gateway:4002
    ├── s5_pb (KeltnerEngine) ──► IB Gateway:4002
    └── s5_dual (KeltnerEngine) ► IB Gateway:4002
```

Each strategy container runs its own engine (`python -m strategy`, `python -m strategy_2`, `python -m strategy_3`). The multi-strategy launcher (`main_multi.py`) runs all five strategies (ATRSS, S5_PB, S5_DUAL, Breakout, Helix) in a single process with a shared OMS, `StrategyCoordinator`, `MarketCalendar`, and `InstrumentationContext`.

## Part 2: Pre-Deployment Checklist (Local)

### 2.1 IBKR Paper Account Prerequisites

1. **Paper trading account** — Log into [IBKR Account Management](https://www.interactivebrokers.com/) and ensure paper trading is enabled (account ID starts with `DU`).
2. **API access** — Account Management → Settings → API → Enable ActiveX and Socket Clients. Set "Trusted IPs" to include `127.0.0.1`.
3. **Market data subscriptions** — Subscribe to data for your target instruments:
   - ETFs (QQQ, GLD, USO, IBIT): US Securities Snapshot and Futures Value Bundle, or US Equity & Options Add-On
   - Micro Futures (MNQ, MCL, MGC, MBT): CME/COMEX/NYMEX market data bundles
   - Paper accounts get 15-minute delayed data by default; real-time requires subscriptions

### 2.2 Local Python Environment

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

pip install -r requirements.txt
```

**requirements.txt contents:**
```
numpy>=1.26
pandas>=2.3
pyarrow>=15.0
matplotlib>=3.10
ib_async>=2.1
asyncpg>=0.31
pydantic>=2.12
pyyaml>=6.0
requests>=2.31
```

The relay service has separate dependencies (installed in its own venv on the VPS): `fastapi`, `uvicorn[standard]`, `aiosqlite`, `pydantic`.

### 2.3 Run Backtests Locally

Validate strategy logic before deploying:

```bash
# ATRSS backtest
python -m backtest run --start 2020-01-01 --end 2024-12-31

# Walk-forward validation
python -m backtest walk-forward --test-months 12

# Parameter sensitivity
python -m backtest ablation --filter momentum_filter
```

Review output in the generated reports (equity curves, trade summaries, drawdown analysis).

### 2.4 Verify Configuration Files

**`config/contracts.yaml`** — Ensure all target symbols are defined with correct `tick_size`, `multiplier`, `exchange`:

| Symbol | Type | Exchange | Multiplier | Tick Size |
|--------|------|----------|------------|-----------|
| MNQ | FUT | CME | 2.0 | 0.25 |
| MCL | FUT | NYMEX | 100.0 | 0.01 |
| MGC | FUT | COMEX | 10.0 | 0.10 |
| MBT | FUT | CME | 0.1 | 5.0 |
| QQQ | STK | SMART | 1.0 | 0.01 |
| USO | STK | SMART | 1.0 | 0.01 |
| GLD | STK | SMART | 1.0 | 0.01 |
| IBIT | STK | SMART | 1.0 | 0.01 |

**`config/ibkr_profiles.yaml`** — Update `account_id` to your paper account:
```yaml
host: "127.0.0.1"
port: 4002
client_id: 7
account_id: "DU1234567"   # ← your paper account ID
```

**`config/routing.yaml`** — Futures exchange routing. No changes needed unless adding new instruments.

### 2.5 Test IB Connection Locally

1. Start TWS or IB Gateway on your desktop
2. Enable API connections (Edit → Global Configuration → API → Settings → Enable, port 4002)
3. Test:
```bash
python -c "
import asyncio
from ib_async import IB
async def test():
    ib = IB()
    await ib.connectAsync('127.0.0.1', 4002, clientId=99)
    print('Connected:', ib.isConnected())
    print('Accounts:', ib.managedAccounts())
    ib.disconnect()
asyncio.run(test())
"
```

---

## Part 3: VPS Provisioning

### 3.1 Recommended Specs (DigitalOcean)

| Resource | Minimum (Basic Droplet) | Recommended (Regular Droplet) |
|----------|-------------------------|-------------------------------|
| CPU | 2 vCPU — **Basic $18/mo** | 4 vCPU — **Regular $48/mo** |
| RAM | 4 GB | 8 GB |
| Disk | 80 GB SSD (included) | 160 GB SSD (included) |
| OS | Ubuntu 22.04 LTS | Ubuntu 24.04 LTS |
| Region | **NYC1** or **NYC3** | **NYC1** or **NYC3** |

> **Why NYC?** IBKR's primary US equities data center is in Secaucus, NJ. DigitalOcean's NYC1/NYC3 regions are the closest available — expect <5ms latency. For CME futures (Aurora, IL), latency is ~20ms from NYC, which is fine for swing trading.

### 3.2 DigitalOcean Setup

**Droplet creation:**
1. [cloud.digitalocean.com](https://cloud.digitalocean.com/) → Create → Droplets
2. Region: **New York — NYC1** (or NYC3)
3. Image: **Ubuntu 24.04 LTS**
4. Droplet type: **Basic** (shared CPU) is sufficient for swing trading — strategies are I/O-bound, not CPU-bound
5. Size: **4 GB / 2 vCPU / 80 GB SSD** minimum; upgrade to 8 GB if running backtests on the same box
6. Authentication: **SSH keys** (add your public key during creation)
7. Enable **weekly backups** ($1/mo for Basic) — cheap insurance against VPS issues
8. Hostname: `trading-vps` or similar

**Networking:**
- Enable **VPC** (default in NYC regions) — isolates your Droplet from other tenants
- Reserve a **floating IP** ($5/mo) if you want a stable IP across Droplet rebuilds — optional for swing trading
- DigitalOcean Cloud Firewall (free) can supplement UFW as an external layer:
  - Allow inbound: SSH (22), HTTPS (443), Dashboard (3000) from your home IP only
  - Allow outbound: all (needed for IBKR, apt, Docker Hub)

**Monitoring:**
- Enable built-in **DigitalOcean Monitoring** (free) — CPU, memory, disk, bandwidth graphs
- Set up **alert policies**: CPU > 90% for 5 min, disk > 80%, memory > 90%
- These complement the application-level monitoring in Part 9

### 3.3 Initial Server Setup

SSH into your new Droplet (`ssh root@<droplet-ip>`) and run the following:

```bash
# System update
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl wget unzip software-properties-common ufw

# Timezone — match IBKR's US Eastern for log readability
sudo timedatectl set-timezone America/New_York

# Firewall
sudo ufw allow OpenSSH
sudo ufw allow 3000/tcp    # Trading dashboard (restrict to your IP in production)
sudo ufw allow from 172.16.0.0/12 to any port 4002  # Docker containers → IB Gateway
sudo ufw enable
```

### 3.4 SSH Hardening

```bash
# Generate SSH key on your local machine (if you haven't already)
ssh-keygen -t ed25519 -C "trading-vps"
ssh-copy-id -i ~/.ssh/id_ed25519.pub user@your-vps-ip

# On the VPS — disable password authentication
sudo nano /etc/ssh/sshd_config
```

Set these values:
```
PasswordAuthentication no
PubkeyAuthentication yes
PermitRootLogin no
```

```bash
sudo systemctl restart sshd
```

### 3.5 Upload Repository

Upload the codebase to the VPS before proceeding — Parts 4 and 5 reference config files from the repo.

```bash
sudo mkdir -p /opt/trading
sudo chown $USER:$USER /opt/trading
cd /opt/trading

# Option A: git clone
git clone <YOUR_REPO_URL> swing_trader

# Option B: scp from local machine (run this on your local machine, not the VPS)
scp -r /path/to/swing_trader user@your-vps-ip:/opt/trading/swing_trader
```

---

## Part 4: IB Gateway Installation (Headless)

IB Gateway runs headlessly on the VPS using IBC (IB Controller) to automate login, and Xvfb to provide a virtual display.

> **IBC path resolution (important):** IBC's `gatewaystart.sh` sets default paths at the top of the script, and its internal `ibcstart.sh` constructs the gateway path as `<TWS_PATH>/ibgateway/<version>/` on Linux. The systemd service file should **not** pass path flags (they conflict with the script variables). All path configuration belongs in the `gatewaystart.sh` variables only — see section 4.4.

### 4.1 Install Java and Xvfb

```bash
sudo apt install -y default-jre xvfb
java -version   # confirm Java 11+
```

### 4.2 Install IB Gateway

IBC looks for the installation at `<TWS_PATH>/IB Gateway <version>/`. Install and create the expected directory structure:

```bash
cd /tmp
wget -O ibgateway-stable-standalone-linux-x64.sh \
  "https://download2.interactivebrokers.com/installers/ibgateway/stable-standalone/ibgateway-stable-standalone-linux-x64.sh"
chmod +x ibgateway-stable-standalone-linux-x64.sh

# Install IB Gateway (adjust 1037 if version differs)
sudo mkdir -p /opt/ibgateway
sudo sh ibgateway-stable-standalone-linux-x64.sh -q -dir /opt/ibgateway/1037

# IBC expects path: /opt/ibgateway/IB Gateway 1037/ — create symlink
sudo ln -s /opt/ibgateway/1037 "/opt/ibgateway/IB Gateway 1037"
```

> **Tip:** To check the installed version number, look at the jar filename: `ls /opt/ibgateway/1037/jars/jts4launch-*.jar`. If the version differs from 1037, adjust the install dir and symlink accordingly.

### 4.3 Install IBC 3.19.0

```bash
cd /tmp
wget https://github.com/IbcAlpha/IBC/releases/download/3.19.0/IBCLinux-3.19.0.zip
sudo mkdir -p /opt/ibc
sudo unzip IBCLinux-3.19.0.zip -d /opt/ibc
sudo chmod +x /opt/ibc/*.sh /opt/ibc/*/*.sh
```

### 4.4 Configure IBC

**Set IBC script paths** — edit the variables at the top of `gatewaystart.sh`:

```bash
sudo nano /opt/ibc/gatewaystart.sh
```

Change these lines near the top of the file:

```bash
TWS_MAJOR_VRSN=1037
IBC_INI=/opt/ibc/config/config.ini
TRADING_MODE=paper
TWS_PATH=/opt
TWS_SETTINGS_PATH=/opt/ibgateway/1037
```

> **Note:** `TWS_MAJOR_VRSN` must match the installed IB Gateway version. Check with `ls /opt/ibgateway/1037/jars/jts4launch-*.jar` — the number in the filename is the major version. On Linux, IBC resolves the gateway path as `<TWS_PATH>/ibgateway/<version>/`, so `TWS_PATH=/opt` makes it find `/opt/ibgateway/1037/`.

**Create the IBC config file** with your IBKR credentials:

```bash
sudo mkdir -p /opt/ibc/config
sudo cp /opt/trading/swing_trader/infra/ibc/config.ini.example /opt/ibc/config/config.ini
sudo nano /opt/ibc/config/config.ini
```

Edit these fields with your paper trading credentials:

```ini
# IBKR Credentials (paper trading)
IbLoginId=YOUR_IBKR_USERNAME
IbPassword=YOUR_IBKR_PASSWORD

# Paper trading mode
TradingMode=paper

# Auto-accept non-brokerage account warning
AcceptNonBrokerageAccountWarning=yes

# Existing session handling
ExistingSessionDetectedAction=primary

# Auto-restart (IBKR resets connections daily ~midnight ET)
AutoRestartTime=00:00

# Accept incoming API connections
AcceptIncomingConnectionAction=accept
ReadOnlyApi=no

# Dismiss popups
DismissPasswordExpiryWarning=yes
DismissNSEComplianceNotice=yes

# Gateway port for paper trading
OverrideTwsApiPort=4002

# Gateway mode (not TWS)
FIX=no
```

Secure the file:
```bash
sudo chmod 600 /opt/ibc/config/config.ini
```

### 4.5 Install systemd Service

The service file (`infra/systemd/ibgateway.service`) starts Xvfb on display `:1` then launches IBC in gateway mode. All IBC paths and settings are configured in `gatewaystart.sh` (section 4.4), so the service file only needs `-inline`:

```bash
sudo cp /opt/trading/swing_trader/infra/systemd/ibgateway.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable ibgateway
sudo systemctl start ibgateway
```

**Service definition** (already in `infra/systemd/ibgateway.service` — no need to create manually, shown here for reference):
```ini
[Unit]
Description=IB Gateway (Paper Trading) via IBC
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
Environment="DISPLAY=:1"
ExecStartPre=/bin/bash -c '/usr/bin/Xvfb :1 -screen 0 1024x768x24 &'
ExecStart=/opt/ibc/gatewaystart.sh -inline
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

### 4.6 Verify IB Gateway

Wait ~60 seconds for startup, then verify:

```bash
# Check port is listening
ss -tlnp | grep 4002

# Check service status
sudo systemctl status ibgateway

# Check logs
sudo journalctl -u ibgateway --no-pager -n 50
```

Port 4002 should be in LISTEN state. If not, see troubleshooting below.

### 4.7 IB Gateway API Access (TrustedIPs)

IB Gateway defaults to `TrustedIPs=127.0.0.1` in `jts.ini` and **overwrites this file on every startup**, so editing it directly is unreliable. The production portfolio container uses `network_mode: host` in `docker-compose.yml` to connect from `127.0.0.1`, bypassing this restriction entirely.

The standalone strategy containers (atrss, akc_helix, swing_breakout) still use Docker bridge networking. If you run them for isolated debugging and they can't connect to IB Gateway, you may need to temporarily add Docker IPs via the IB Gateway GUI (Configure → API → Trusted IPs).

### 4.8 Troubleshooting IB Gateway

| Problem | Solution |
|---------|----------|
| **Credentials rejected** | Verify username/password in `/opt/ibc/config/config.ini`. Paper account usernames are the same as live, but the password may differ. Log in via web first to confirm. |
| **Java not found** | Run `java -version`. Install with `sudo apt install -y default-jre`. |
| **Xvfb not starting** | Check `ps aux \| grep Xvfb`. If display `:1` is taken, change to `:2` in the service file. |
| **2FA prompt blocking login** | Use IBC's `--on2fa:second-factor-device` flag (already in service file). Alternatively, configure IBKR to use a security device that IBC can handle, or pre-authenticate via web. |
| **Port not listening after 2 minutes** | Check `journalctl -u ibgateway -n 100`. Common: wrong IBC path, missing Java, firewall blocking localhost. |

---

## Part 5: Docker Stack Deployment

### 5.1 Install Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
exit   # re-login for group change
```

Verify:
```bash
docker --version
docker compose version
```

### 5.2 Upload Repository

Already done in section 3.5. Verify the repo is in place:

```bash
ls /opt/trading/swing_trader/main_multi.py
```

### 5.3 Configure Environment

```bash
cd /opt/trading/swing_trader
cp .env.example .env
nano .env
```

Set all variables:

```bash
# Environment: dev | backtest | paper | live
SWING_TRADER_ENV=paper

# IBKR connection
IB_ACCOUNT_ID=DU1234567          # Your paper account ID
IB_HOST=host.docker.internal     # Docker's host gateway
IB_PORT=4002                     # Paper trading port

# Database (PostgreSQL)
POSTGRES_PASSWORD=<strong-password>
POSTGRES_READER_PASSWORD=<strong-password>
POSTGRES_WRITER_PASSWORD=<strong-password>
DB_HOST=postgres                 # Docker service name
DB_PORT=5432
DB_NAME=trading
DB_USER=trading_writer
DB_PASSWORD=<same-as-writer-password>

# Strategy symbol sets (optional overrides)
# ATRSS_SYMBOL_SET=etf            # etf | micro | full | all
# AKCHELIX_SYMBOL_SET=etf         # etf | micro_futures | full_futures | all
```

Secure the file:
```bash
chmod 600 .env
```

### 5.4 Start PostgreSQL and Dashboard

```bash
cd /opt/trading/swing_trader

# Build dashboard image (first time or after dashboard code changes)
docker compose -f infra/docker-compose.yml build dashboard

# Start infrastructure
docker compose -f infra/docker-compose.yml up -d postgres dashboard

# Wait for health check
docker compose -f infra/docker-compose.yml ps
# postgres should show "healthy"; dashboard should show "Up"

# Verify postgres is ready
docker exec trading_postgres pg_isready -U trading_admin -d trading

# Verify dashboard started
docker compose -f infra/docker-compose.yml logs dashboard | tail -5
# Expect: "ready - started server on 0.0.0.0:3000"
```

### 5.5 Update Default Database Passwords

The `infra/init-db.sql` creates roles with placeholder passwords. Update them to match your `.env`:

```bash
docker exec -it trading_postgres psql -U trading_admin -d trading -c \
  "ALTER USER trading_writer WITH PASSWORD 'your_actual_writer_password';"

docker exec -it trading_postgres psql -U trading_admin -d trading -c \
  "ALTER USER trading_reader WITH PASSWORD 'your_actual_reader_password';"
```

### 5.6 Build and Start Portfolio Launcher (Default Deployment)

```bash
# Build the portfolio launcher (`main_multi.py`)
docker compose -f infra/docker-compose.yml \
  --profile portfolio build portfolio

# Start the portfolio launcher
docker compose -f infra/docker-compose.yml \
  --profile portfolio up -d portfolio

# Verify
docker compose -f infra/docker-compose.yml \
  --profile portfolio ps portfolio
```

This is the production deployment path that preserves the portfolio-level heat cap, priorities, and coordination rules from `main_multi.py` and the portfolio backtests.

**Standalone strategy containers (isolated debugging only):**
```bash
# ATRSS only
docker compose -f infra/docker-compose.yml --profile atrss up -d atrss

# ATRSS + Breakout (skip Helix)
docker compose -f infra/docker-compose.yml --profile atrss --profile swing_breakout up -d atrss swing_breakout
```

Do not run the standalone profiles alongside the portfolio launcher in production, or you will duplicate strategies and change portfolio behavior.

### 5.7 Verify Strategy→IB Gateway Connectivity

```bash
docker exec -it trading_portfolio python -c \
  'import socket; s = socket.socket(); s.connect(("127.0.0.1", 4002)); print("Connected!"); s.close()'
```

The portfolio launcher uses `network_mode: host` to connect directly to IB Gateway on `127.0.0.1:4002`. The standalone strategy containers use `extra_hosts: host.docker.internal:host-gateway` instead.

---

## Part 6: Relay Service Deployment

The relay is a lightweight FastAPI app (~100 lines of meaningful code) that buffers events from all trading bots and serves them to the home orchestrator on demand. It runs on the same VPS as the bot, backed by SQLite. See Appendix C for API details, component internals, and maintenance commands.

Deploy the relay service and configure the instrumentation sidecar to forward events from the trading bots.

### 6.1 Service Installation

```bash
# 1. Create relay directory and copy files
sudo mkdir -p /opt/trading-relay/data
sudo useradd -r -s /usr/sbin/nologin trading-relay
sudo chown trading-relay:trading-relay /opt/trading-relay /opt/trading-relay/data

rsync -avz relay/ run_relay.py user@vps:/opt/trading-relay/
# Or if repo is already on the VPS:
sudo mkdir -p /opt/trading-relay/relay/db
sudo cp /opt/trading/swing_trader/relay/__init__.py /opt/trading-relay/relay/
sudo cp /opt/trading/swing_trader/relay/app.py /opt/trading-relay/relay/
sudo cp /opt/trading/swing_trader/relay/auth.py /opt/trading-relay/relay/
sudo cp /opt/trading/swing_trader/relay/rate_limiter.py /opt/trading-relay/relay/
sudo cp /opt/trading/swing_trader/relay/db/* /opt/trading-relay/relay/db/
sudo cp /opt/trading/swing_trader/run_relay.py /opt/trading-relay/
sudo cp /opt/trading/swing_trader/relay/start.sh /opt/trading-relay/
sudo cp /opt/trading/swing_trader/relay/trading-relay.service /opt/trading-relay/
sudo cp /opt/trading/swing_trader/relay/nginx-trading-relay.conf /opt/trading-relay/

# Fix ownership and permissions (start.sh must be executable by trading-relay)
sudo chown -R trading-relay:trading-relay /opt/trading-relay
sudo chmod +x /opt/trading-relay/start.sh

# 2. Create Python venv and install dependencies
cd /opt/trading-relay
sudo -u trading-relay python3 -m venv venv
sudo -u trading-relay venv/bin/pip install fastapi 'uvicorn[standard]' aiosqlite pydantic

# 3. Generate HMAC shared secret (same secret used by bot + relay)
python3 -c "import secrets; print(secrets.token_hex(32))"

# 4. Create secrets.json mapping bot_id → HMAC secret
cat > /opt/trading-relay/secrets.json <<'EOF'
{"swing_multi_01": "<paste-secret-here>"}
EOF
chmod 600 /opt/trading-relay/secrets.json

# 5. Create .env for relay API key (used by trading_assistant to pull events)
cat > /opt/trading-relay/.env <<'EOF'
RELAY_SECRETS_FILE=/opt/trading-relay/secrets.json
RELAY_DB_PATH=/opt/trading-relay/data/relay.db
RELAY_API_KEY=<generate-another-secret-for-pull-api>
EOF
chmod 600 /opt/trading-relay/.env

# 6. Install and start systemd service
sudo cp /opt/trading-relay/trading-relay.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now trading-relay

# 7. Verify
curl -s http://127.0.0.1:8001/health
# {"status": "ok", "pending_events": 0, ...}
```

### 6.2 Nginx HTTPS Reverse Proxy (for remote trading_assistant access)

```bash
# 1. Install nginx + certbot
sudo apt install -y nginx certbot python3-certbot-nginx

# 2. Copy and customize nginx config
sudo cp /opt/trading-relay/nginx-trading-relay.conf /etc/nginx/sites-available/trading-relay
sudo nano /etc/nginx/sites-available/trading-relay
# Replace relay.yourdomain.com with your actual domain

# 3. Enable site and get TLS cert
sudo ln -s /etc/nginx/sites-available/trading-relay /etc/nginx/sites-enabled/
sudo certbot --nginx -d relay.yourdomain.com

# 4. Open HTTPS port
sudo ufw allow 443/tcp

# 5. Verify HTTPS
curl -s https://relay.yourdomain.com/health
```

### 6.3 Bot-Side Configuration

Add to `.env` on the VPS:

```bash
# HMAC secret — must match the relay's secrets.json entry for "swing_multi_01"
INSTRUMENTATION_HMAC_SECRET=<same-secret-as-relay>
```

The `env_file: ../.env` directive in docker-compose loads this into all strategy containers. Do **not** add `INSTRUMENTATION_HMAC_SECRET` to the compose `environment:` section — the `${...}` expansion resolves from the host shell (where it's unset) and would override the `env_file` value with empty string.

`RELAY_URL` is already set per-service in docker-compose.yml (`http://127.0.0.1:8001/events` for portfolio with host networking, `http://host.docker.internal:8001/events` for standalone containers with bridge networking). No `.env` entry needed.

The sidecar in `instrumentation/src/sidecar.py` checks `RELAY_URL` env var first, then falls back to `relay_url` in `instrumentation/config/instrumentation_config.yaml`.

### 6.4 Firewall Rules

```bash
# Relay port 8001 should only be accessible locally (sidecar → relay on same host)
# Do NOT expose 8001 externally — use nginx HTTPS proxy for remote access
# The existing UFW rules only allow SSH and 443 (HTTPS)
```

### 6.5 Relay Maintenance Cron

```bash
# Add relay event purge to crontab (daily at 02:00 UTC, purge acked events older than 30 days)
(crontab -l 2>/dev/null; echo "0 2 * * * curl -s -X POST -H 'X-Api-Key: <your-api-key>' http://127.0.0.1:8001/admin/purge") | crontab -
```

### 6.6 Deployment Verification Checklist

- [ ] Relay service running: `sudo systemctl status trading-relay`
- [ ] Relay health endpoint: `curl -s http://127.0.0.1:8001/health`
- [ ] HMAC secret matches between `.env` (`INSTRUMENTATION_HMAC_SECRET`) and relay's `secrets.json`
- [ ] Sidecar forwarding events: check relay health for non-zero `pending_events` after bot starts
- [ ] HTTPS proxy working (if using remote trading_assistant): `curl -s https://relay.yourdomain.com/health`
- [ ] Trading_assistant can pull events: `GET /events?since=0&limit=1` with `X-Api-Key` header
- [ ] Instrumentation data directories created: `ls instrumentation/data/` should show `trades/`, `missed/`, `scores/`, etc.
- [ ] Post-exit backfill running: check for `post_exit/` JSONL files 4+ hours after first trade exit
- [ ] Daily snapshots generating: check `daily/daily_YYYY-MM-DD.json` after 16:05 ET on a trading day
- [ ] Heartbeat events flowing: check `heartbeat/` dir for JSONL files within 60 seconds of bot start

---

## Part 7: Post-Deployment Verification

### 7.1 Check Strategy Logs

```bash
# Portfolio launcher (all five strategies run inside this one container)
docker compose -f infra/docker-compose.yml --profile portfolio logs -f portfolio
```

**Successful bootstrap sequence** — you should see:
1. Database bootstrap (pool created, or fallback to in-memory)
2. IB Gateway connection established
3. Strategy engine started
4. Heartbeat messages (periodic)
5. During market hours: bar data received, indicator computation, signal evaluation

### 7.2 Verify Database Tables

```bash
docker exec -it trading_postgres psql -U trading_admin -d trading -c \
  "SELECT * FROM strategy_state;"
```

**Expected tables** (created by OMS on first boot):
- `strategy_state` — strategy health (mode, heartbeat, heat_r, daily_pnl_r)
- `adapter_state` — broker connection state (connected, disconnect_count_24h)
- `orders` — order lifecycle tracking
- `order_events` — order state transitions
- `fills` — execution fills
- `trades` — completed trade records
- `trade_marks` — MAE/MFE metrics per trade
- `risk_daily_strategy` — daily risk metrics per strategy
- `risk_daily_portfolio` — portfolio-level daily risk

### 7.3 First Signal Generation

Wait for market hours (ETF: 09:30–16:00 ET, Futures: nearly 24h) and observe:
- ATRSS: hourly cycle logs showing `compute_daily_state()`, `compute_hourly_state()`, candidate evaluation
- Helix: divergence scanning, MACD momentum checks
- Breakout: squeeze detection, displacement scoring

### 7.4 Verify Order Submission Flow

When a strategy generates a signal during paper trading:
1. Strategy creates an `Intent` (type=`NEW_ORDER`)
2. `IntentHandler` validates and routes to `RiskGateway`
3. `RiskGateway` runs pre-trade checks (daily stop, heat cap, max working orders)
4. If approved: `ExecutionRouter` queues the order (stops > cancels > replaces > entries)
5. `IBKRExecutionAdapter` submits to IB Gateway
6. Fill events flow back through `FillProcessor` → `EventBus` → strategy

Monitor the flow in strategy logs. Look for `RISK_APPROVED`, `ROUTED`, `WORKING`, `FILLED` state transitions.

### 7.5 Check Trading Dashboard

Open `http://YOUR_VPS_IP:3000` — see Appendix A for dashboard details. The dashboard connects to the `trading` database as `trading_reader` and starts polling immediately. Expect the strategy grid to populate once the portfolio launcher has written its first heartbeats to `strategy_state`.

---

## Part 8: Cron Jobs & Maintenance

### 8.1 Data Retention Cron Job

The retention script runs `infra/retention.sql` daily — deleting old order events (60 days), resetting disconnect counters, and vacuuming tables.

```bash
# Create log directory
sudo mkdir -p /var/log/trading
sudo chown $USER:$USER /var/log/trading

# Make script executable
chmod +x /opt/trading/swing_trader/infra/cron/retention.sh

# Add to crontab (daily at 00:05 UTC)
(crontab -l 2>/dev/null; echo "5 0 * * * /opt/trading/swing_trader/infra/cron/retention.sh") | crontab -
```

**What `infra/retention.sql` does:**
```sql
-- Delete old order events (60 days)
DELETE FROM order_events WHERE event_ts < now() - INTERVAL '60 days';

-- Reset daily disconnect counters
UPDATE adapter_state SET disconnect_count_24h = 0;

-- Vacuum for performance
VACUUM ANALYZE order_events;
VACUUM ANALYZE fills;
VACUUM ANALYZE trades;
```

### 8.2 Log Rotation

Docker handles log rotation for containers. For system logs:

```bash
# /etc/logrotate.d/trading
cat <<'EOF' | sudo tee /etc/logrotate.d/trading
/var/log/trading/*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
}
EOF
```

### 8.3 Database Backup

```bash
# Daily backup script
cat <<'SCRIPT' > /opt/trading/backup-db.sh
#!/bin/bash
set -euo pipefail
BACKUP_DIR="/opt/trading/backups"
mkdir -p "$BACKUP_DIR"
DATE=$(date +%Y%m%d_%H%M%S)
docker exec trading_postgres pg_dump -U trading_admin trading | gzip > "$BACKUP_DIR/trading_${DATE}.sql.gz"
# Keep last 30 days
find "$BACKUP_DIR" -name "*.sql.gz" -mtime +30 -delete
SCRIPT
chmod +x /opt/trading/backup-db.sh

# Schedule daily at 01:00 UTC
(crontab -l 2>/dev/null; echo "0 1 * * * /opt/trading/backup-db.sh") | crontab -
```

---

## Part 9: Monitoring & Alerting

### 9.1 Strategy Health Monitoring

The `strategy_state` table tracks each strategy's health:

| Column | Meaning |
|--------|---------|
| `mode` | `RUNNING`, `STAND_DOWN`, `HALTED` |
| `last_heartbeat_ts` | Last heartbeat timestamp |
| `heat_r` | Current open risk in R |
| `daily_pnl_r` | Today's realized P&L in R |
| `last_error` | Most recent error message |
| `last_seen_bar_ts` | Timestamp of last processed bar |

**Quick health check:**
```bash
docker exec -it trading_postgres psql -U trading_admin -d trading -c \
  "SELECT strategy_id, mode, age(now(), last_heartbeat_ts) as heartbeat_age, heat_r, daily_pnl_r FROM strategy_state;"
```

### 9.2 IB Gateway Connection Monitoring

The `adapter_state` table tracks broker connectivity:

| Column | Meaning |
|--------|---------|
| `connected` | Current connection status |
| `last_heartbeat_ts` | Last successful heartbeat |
| `disconnect_count_24h` | Disconnections in last 24 hours |
| `last_error_code` | Last IB error code |

### 9.3 Log Monitoring

```bash
# All strategy logs (last 100 lines, follow)
docker compose -f infra/docker-compose.yml \
  --profile portfolio logs -f --tail=100 portfolio

# IB Gateway logs
sudo journalctl -u ibgateway --no-pager -n 50
```

### 9.4 Suggested External Monitoring

- **Process liveness**: Use [UptimeRobot](https://uptimerobot.com/) or [Healthchecks.io](https://healthchecks.io/) to ping a health endpoint or monitor cron jobs.
- **Port monitoring**: Monitor port 4002 (IB Gateway) and 5432 (PostgreSQL) availability.
- **Simple heartbeat script** (add to crontab every 5 minutes):
```bash
#!/bin/bash
# Check if strategies are running and heartbeats are fresh
STALE=$(docker exec trading_postgres psql -U trading_admin -d trading -t -c \
  "SELECT count(*) FROM strategy_state WHERE last_heartbeat_ts < now() - interval '5 minutes';")
if [ "$STALE" -gt 0 ]; then
  echo "WARNING: $STALE strategies have stale heartbeats" | mail -s "Trading Alert" you@email.com
fi
```

### 9.5 Daily IBKR Reset Handling

IBKR resets all connections daily around midnight ET. The system handles this automatically:
- **IBC config**: `AutoRestartTime=00:00` — IBC auto-restarts IB Gateway after the daily reset
- **systemd**: `Restart=on-failure`, `RestartSec=30` — restarts if IB Gateway crashes
- **Docker**: `restart: unless-stopped` — strategy containers restart automatically
- **OMS**: Reconnection logic in `IBSession` detects disconnection and re-establishes the connection
- **Reconciliation**: On reconnect, the reconciliation orchestrator syncs OMS state with IB's actual state

---

## Part 10: Paper-to-Live Transition

### 10.1 Minimum Paper Trading Duration

**Recommended: 2–4 weeks minimum** of paper trading before going live. During this period, validate:

- [ ] Strategies connect to IB Gateway and stay connected across daily resets
- [ ] Orders submit correctly (correct symbol, quantity, price, order type)
- [ ] Fills process correctly (position tracking, P&L computation)
- [ ] Stop orders execute at expected prices
- [ ] Partial profit-taking (TP1/TP2) works correctly
- [ ] Trailing stops adjust as expected
- [ ] Risk gates fire correctly (daily stop, heat cap, max working orders)
- [ ] Cross-strategy coordination works (ATRSS entry → Helix stop tightening)
- [ ] Overnight restarts are seamless (no orphaned orders, no missed fills)
- [ ] Trading dashboard at `:3000` shows accurate real-time positions, orders, and strategy health
- [ ] Database tables grow at expected rates
- [ ] Fill quality and slippage are within acceptable ranges
- [ ] Instrumentation JSONL files generated in `instrumentation/data/` (trades, missed, scores, heartbeat)
- [ ] Sidecar forwarding events to relay (check `curl http://127.0.0.1:8001/health` for pending events)
- [ ] Post-exit backfill populating `post_exit_1h_pct`/`post_exit_4h_pct` on trade exit records
- [ ] Daily snapshots generating at 16:05 ET
- [ ] Process quality scores attached to trade exit records

### 10.2 Configuration Changes for Live

| Setting | Paper | Live |
|---------|-------|------|
| `.env` `SWING_TRADER_ENV` | `paper` | `live` |
| IBC `config.ini` `TradingMode` | `paper` | `live` |
| IBC `config.ini` `OverrideTwsApiPort` | `4002` | `4001` |
| systemd service `--mode` | `paper` | `live` |
| `.env` `IB_PORT` | `4002` | `4001` |
| `.env` `IB_ACCOUNT_ID` | `DU1234567` | `U1234567` (live) |

### 10.3 Risk Parameter Review

Before going live, review and confirm these risk parameters in `main_multi.py`. These match the **optimized_v2** backtest preset ($10K: +191.2% return, -11.8% max DD, 1.22 Sharpe):

| Parameter | ATRSS | S5_PB | S5_DUAL | SWING_BREAKOUT_V3 | AKC_HELIX |
|-----------|-------|-------|---------|-------------------|-----------|
| `unit_risk_pct` | **1.20%** | 0.80% | 0.80% | 0.50% | 0.50% |
| `daily_stop_R` | 2.0 | 2.0 | 2.0 | 2.0 | 2.5 |
| `max_heat_R` | 1.00 | 1.50 | 1.50 | 0.65 | 0.85 |
| `max_working_orders` | 4 | 2 | 2 | 2 | 4 |
| `priority` | 0 (highest) | 1 | 2 | 3 | 4 (lowest) |

**Portfolio-level:**
- `heat_cap_R` = **2.0** (total open risk across all strategies)
- `portfolio_daily_stop_R` = 3.0 (portfolio-wide daily loss limit)

**Note:** All five strategies (ATRSS, S5_PB, S5_DUAL, Breakout, Helix) have complete live engines and are wired into `main_multi.py` with instrumentation.

**Backtest validation:** `python -m backtest.run_unified --preset optimized_v1 --equity 10000`

Consider starting with **reduced risk** (e.g., 50% of target `unit_risk_pct`) for the first 1–2 weeks of live trading, then scaling up once you confirm live execution quality matches paper.

### 10.4 Portfolio-Preserving Rollout

To keep live deployment aligned with the default portfolio configuration, priorities, and backtested coordination rules, keep the runtime topology fixed: run `main_multi.py` as the portfolio launcher.

```bash
# Default production topology
docker compose -f infra/docker-compose.yml up -d postgres dashboard
docker compose -f infra/docker-compose.yml --profile portfolio up -d portfolio
```

If you want a softer live rollout, reduce risk inputs or capital allocation inside the existing portfolio configuration. Do not swap to standalone strategy containers if you want behavior to remain comparable to the portfolio backtests.

---

## Part 11: Operational Runbook

### 11.1 Common Operations

| Action | Command |
|--------|---------|
| **Restart portfolio launcher** | `docker compose -f infra/docker-compose.yml --profile portfolio restart portfolio` |
| **Stop portfolio launcher** | `docker compose -f infra/docker-compose.yml stop portfolio` |
| **Stop everything** | `docker compose -f infra/docker-compose.yml down && sudo systemctl stop ibgateway && sudo systemctl stop trading-relay` |
| **Start everything** | `sudo systemctl start ibgateway && sudo systemctl start trading-relay && sleep 60 && docker compose -f infra/docker-compose.yml up -d postgres dashboard && docker compose -f infra/docker-compose.yml --profile portfolio up -d portfolio` |
| **View portfolio logs** | `docker compose -f infra/docker-compose.yml --profile portfolio logs -f --tail=100 portfolio` |
| **View portfolio launcher log** | `docker compose -f infra/docker-compose.yml --profile portfolio logs -f portfolio` |
| **View dashboard logs** | `docker compose -f infra/docker-compose.yml logs -f dashboard` |
| **Rebuild portfolio after code changes** | `git pull && docker compose -f infra/docker-compose.yml --profile portfolio build portfolio && docker compose -f infra/docker-compose.yml --profile portfolio up -d portfolio` |
| **Rebuild dashboard after code changes** | `git pull && docker compose -f infra/docker-compose.yml build dashboard && docker compose -f infra/docker-compose.yml restart dashboard` |
| **Check IB Gateway status** | `sudo systemctl status ibgateway` |
| **Check IB Gateway logs** | `sudo journalctl -u ibgateway --no-pager -n 30` |
| **Check database health** | `docker exec trading_postgres pg_isready -U trading_admin -d trading` |
| **Query strategy state** | `docker exec -it trading_postgres psql -U trading_admin -d trading -c "SELECT * FROM strategy_state;"` |
| **Query today's trades** | `docker exec -it trading_postgres psql -U trading_admin -d trading -c "SELECT * FROM v_today_trades;"` |
| **Query working orders** | `docker exec -it trading_postgres psql -U trading_admin -d trading -c "SELECT * FROM v_working_orders;"` |
| **Manual DB backup** | `/opt/trading/backup-db.sh` |
| **Check relay status** | `sudo systemctl status trading-relay` |
| **View relay logs** | `journalctl -u trading-relay --since "1 hour ago"` |
| **Restart relay** | `sudo systemctl restart trading-relay` |
| **Check relay DB size** | `du -h /opt/trading-relay/data/relay.db` |
| **Purge acked relay events** | `sqlite3 /opt/trading-relay/data/relay.db "DELETE FROM events WHERE acked = 1; VACUUM;"` |
| **Check relay pending events** | `curl -s http://127.0.0.1:8001/health` |
| **View today's instrumentation trades** | `cat instrumentation/data/trades/trades_$(date +%Y-%m-%d).jsonl \| python -m json.tool --no-ensure-ascii` |
| **View today's daily snapshot** | `cat instrumentation/data/daily/daily_$(date +%Y-%m-%d).json \| python -m json.tool` |
| **Run instrumentation tests** | `PYTHONPATH="$(pwd):$PYTHONPATH" python -m pytest instrumentation/tests/ relay/tests/ -v` |

### 11.2 Troubleshooting Guide

| Problem | Diagnosis | Solution |
|---------|-----------|----------|
| **Strategy can't connect to IB Gateway** | `ss -tlnp \| grep 4002` (port not listening) | Check `sudo systemctl status ibgateway`. Restart: `sudo systemctl restart ibgateway`. Verify `extra_hosts` in docker-compose. |
| **IB Gateway won't start** | `journalctl -u ibgateway -n 100` | Check Java (`java -version`), credentials in `/opt/ibc/config/config.ini`, Xvfb (`ps aux \| grep Xvfb`). |
| **Database connection refused** | `docker compose -f infra/docker-compose.yml ps` — postgres not healthy | Restart postgres: `docker compose -f infra/docker-compose.yml restart postgres`. Check `POSTGRES_PASSWORD` matches `.env`. |
| **Dashboard shows "Database error"** | API route returns 500 | Check `docker compose logs dashboard`. Verify `trading_reader` password: `docker exec -it trading_postgres psql -U trading_admin -d trading -c "ALTER USER trading_reader WITH PASSWORD 'correct_password';"`. Ensure OMS has run `PgStore.init_schema()` to create tables. |
| **Dashboard shows empty strategy grid** | No rows in `strategy_state` | OMS has not written a heartbeat yet. Start the portfolio launcher and wait for its first heartbeat cycle. |
| **IB Gateway disconnects overnight** | Expected — IBKR daily reset ~midnight ET | `AutoRestartTime=00:00` handles reconnection. Strategies have `restart: unless-stopped`. Check `disconnect_count_24h` in `adapter_state`. |
| **"No security definition found"** | IB error code 200 | Market may be closed. Paper data is 15min delayed and unavailable outside hours. For futures, check contract expiry (roll to next front month). |
| **Orders rejected by risk gateway** | Strategy logs show `RISK_REJECTED` | Check `risk_daily_strategy` for halt status. Check heat cap: `SELECT * FROM strategy_state WHERE heat_r > 0;`. Verify `unit_risk_dollars` is computed correctly. |
| **Strategy shows HALTED mode** | `strategy_state.mode = 'HALTED'` | Strategy hit `daily_stop_R`. Will auto-resume next trading day. To manually clear (use caution): update `mode` in DB. |
| **Stale heartbeats** | `heartbeat_age_sec > 300` in dashboard strategy cards | The portfolio launcher may be stuck. Check logs for errors. Restart `portfolio`. |
| **Disk space running low** | Docker images + DB growth | Run `docker system prune -f`. Check `docker volume ls`. Verify retention cron is running. |
| **Relay returns 401** | HMAC signature mismatch | Verify `INSTRUMENTATION_HMAC_SECRET` matches the bot's entry in `/opt/trading-relay/secrets.json`. Ensure sidecar uses `sort_keys=True` canonicalization. |
| **Relay not accepting events** | `systemctl status trading-relay` shows inactive | Restart: `sudo systemctl restart trading-relay`. Check logs: `journalctl -u trading-relay -n 50`. |
| **Sidecar not forwarding** | Events in JSONL but not in relay | Check sidecar config `relay_url` in `instrumentation_config.yaml`. Verify relay is reachable: `curl http://127.0.0.1:8001/health`. |
| **Missing instrumentation data** | No JSONL files in `instrumentation/data/` | Verify `main_multi.py` bootstrapped instrumentation successfully (check logs for "Instrumentation context created"). Ensure `instrumentation/config/instrumentation_config.yaml` exists with valid `data_dir`. Heartbeat JSONL should appear within 60s of bot start. |
| **Relay DB growing large** | `du -h /opt/trading-relay/data/relay.db` shows >1GB | Purge acked events: `sqlite3 relay.db "DELETE FROM events WHERE acked = 1; VACUUM;"`. Check home orchestrator is acking. |

### 11.3 Emergency Procedures

#### Global Standdown (Stop All New Entries)

```bash
# Set global standdown flag in database
docker exec -it trading_postgres psql -U trading_admin -d trading -c \
  "UPDATE strategy_state SET mode = 'STAND_DOWN', stand_down_reason = 'Manual emergency standdown' WHERE mode = 'RUNNING';"
```

Strategies will stop entering new positions but continue managing existing ones (stops, trailing, exits).

#### Flatten All Positions

If you need to close everything immediately:

1. **Via IB Gateway/TWS directly**: Log into the IB Gateway web interface or TWS and close all positions manually — this is the fastest and most reliable method.

2. **Via strategy**: Each strategy's `FLATTEN` intent type closes all positions for that strategy through the OMS.

#### Full System Shutdown

```bash
# Stop the portfolio launcher first (allows graceful shutdown)
docker compose -f infra/docker-compose.yml stop portfolio

# Wait for containers to stop
sleep 10

# Stop IB Gateway
sudo systemctl stop ibgateway

# Stop relay service
sudo systemctl stop trading-relay

# Stop infrastructure (optional — keeps DB available for queries)
docker compose -f infra/docker-compose.yml down
```

### 11.4 Code Update Workflow

```bash
cd /opt/trading/swing_trader

# Pull latest code
git pull

# Rebuild the portfolio launcher image
docker compose -f infra/docker-compose.yml \
  --profile portfolio build portfolio

# Restart the portfolio launcher
docker compose -f infra/docker-compose.yml --profile portfolio up -d portfolio

# Verify
docker compose -f infra/docker-compose.yml \
  --profile portfolio ps portfolio
```

**Important**: Avoid updating during market hours when positions are open. If you must, the OMS reconciliation will re-sync state on restart, but there's a brief window where stops may not be monitored.

---

## Appendix A: Trading Dashboard

### A.1 Overview

The dashboard is a Next.js 14 application in the `infra/dashboard/` directory. It connects directly to the `trading` PostgreSQL database as `trading_reader` (SELECT-only) and replaces the previous Metabase service on port 3000.

**Design:** Dark terminal aesthetic (`#0a0b0d` background, green/red P&L, amber warnings), full `font-mono`, responsive up to 1800px wide.

**Polling:**
- **Live** (every 30s): portfolio, strategies, positions, trades, orders, health — via `Promise.allSettled`
- **Charts** (every 5 min): 90-day equity curve, 30-day daily P&L bars

### A.2 Dashboard Layout

```
PortfolioHeader     ← today P&L + heat gauge + broker pills + halt banner
StrategyGrid        ← 5 cards (2/3/5 col responsive)
PositionsTable | TradesTable
OrdersTable    | SystemHealth
EquityCurve    | DailyPnlBars
RefreshIndicator    ← fixed bottom-right, countdown + last update time
```

**PortfolioHeader zones:**
1. `daily_realized_r` in `text-3xl` green/red + USD sub-line
2. Heat gauge — Progress bar (`heat_r / 2.0`); green <60%, amber 60–90%, red >90%
3. Broker adapter pills (CONNECTED green / DISCONNECTED red)
4. Halt banner — amber/red; hidden when no active halts

**StrategyCard fields:** status badge (RUNNING/HALTED/STALE/STAND_DOWN), mini heat bar vs `maxHeatR`, daily realized R, entry count, daily stop remaining (`2.0 - |daily_pnl_r|`), heartbeat age.

### A.3 API Routes and Database Views

All routes use `export const dynamic = 'force-dynamic'` and return `Cache-Control: no-store`.

| Route | Source | Notes |
|-------|--------|-------|
| `/api/portfolio` | `risk_daily_portfolio` + `positions` | Subquery for unrealized sum + heat; default zeros on weekend/no-data |
| `/api/strategies` | `v_strategy_health` LEFT JOIN `risk_daily_strategy` | COALESCE risk columns to 0 |
| `/api/positions` | `positions` table directly | `WHERE net_qty != 0`; queries table (not `v_live_positions`) to include `open_risk_r` / `open_risk_dollars` |
| `/api/trades` | `v_today_trades` | `LIMIT 50`; view joins `trades` + `trade_marks` |
| `/api/orders` | `v_working_orders` | Filters to active statuses, computes `age_minutes` |
| `/api/health` | `v_strategy_health` + `v_adapter_health` + `v_active_halts` | 3 queries merged into one response |
| `/api/equity-curve` | `risk_daily_portfolio` | 90-day window, `SUM(...) OVER` for cumulative R |
| `/api/daily-pnl` | `risk_daily_portfolio` | 30-day window |

### A.4 Local Development

```bash
cd infra/dashboard
npm install          # generates package-lock.json
npm run dev          # http://localhost:3000

# Point at local postgres:
# Edit infra/dashboard/.env.local — DB_HOST=localhost, DB_PASSWORD=your_local_reader_password
```

The `.env.local` file is gitignored. Copy values from the root `.env` for `POSTGRES_READER_PASSWORD`.

### A.5 Docker Deployment

```bash
cd /opt/trading/swing_trader

# Build dashboard image
docker compose -f infra/docker-compose.yml build dashboard

# Start (postgres must be healthy first)
docker compose -f infra/docker-compose.yml up -d dashboard

# Verify startup
docker compose -f infra/docker-compose.yml logs dashboard
# Expect: "ready - started server on 0.0.0.0:3000"

# Rebuild after code changes
docker compose -f infra/docker-compose.yml build dashboard && \
  docker compose -f infra/docker-compose.yml restart dashboard
```

**Important:** Run `npm install` locally before first Docker build to generate `package-lock.json` (required for `npm ci` in the Dockerfile).

### A.6 Database Connection

The dashboard connects as `trading_reader` (read-only). Credentials flow:

```
infra/init-db.sql  → creates trading_reader (hardcoded placeholder password)
root .env          → POSTGRES_READER_PASSWORD=<your_actual_password>
infra/docker-compose.yml dashboard service → DB_PASSWORD=${POSTGRES_READER_PASSWORD}
```

Update the placeholder password after first container start:

```bash
docker exec -it trading_postgres psql -U trading_admin -d trading -c \
  "ALTER USER trading_reader WITH PASSWORD 'your_actual_reader_password';"
```

The `trading_reader` role has SELECT on all tables and views in the `public` schema, including the OMS views created at runtime by the OMS process (`trading_writer`). This is guaranteed by the `ALTER DEFAULT PRIVILEGES FOR ROLE trading_writer` grants in `init-db.sql`.

### A.7 Dashboard Panels Reference

| Section | Data Source | Refresh |
|---------|-------------|---------|
| Portfolio header (P&L, heat, halts) | `/api/portfolio` + `/api/health` | 30s |
| Strategy cards (5 strategies) | `/api/strategies` | 30s |
| Open positions table | `/api/positions` | 30s |
| Today's trades table | `/api/trades` | 30s |
| Working orders table | `/api/orders` | 30s |
| System health (heartbeats, errors) | `/api/health` | 30s |
| 90-day equity curve | `/api/equity-curve` | 5 min |
| 30-day daily P&L bars | `/api/daily-pnl` | 5 min |

---

## Appendix B: Instrumentation Layer

The instrumentation layer captures structured event data from all strategies for downstream analysis. It runs in-process alongside each strategy engine — no separate containers. All data is written to disk first (JSONL), then forwarded to the relay service by the sidecar.

### B.1 Architecture

```
main_multi.py
└── InstrumentationContext (shared, one per process)
     ├── Sidecar (background thread, polls every 60s)
     │    └── reads all JSONL dirs ──► HMAC signs ──► POST relay:8001/events
     ├── MarketSnapshotService, RegimeClassifier, DrawdownTracker
     ├── OvernightGapTracker, SessionClassifier, ExperimentRegistry
     ├── ConfigWatcher, DailySnapshotBuilder
     │
     └── Per-strategy InstrumentationKit (×5: ATRSS, Helix, Breakout, S5_PB, S5_DUAL)
          ├── TradeLogger ──────► trades/trades_YYYY-MM-DD.jsonl
          ├── MissedOpportunityLogger ► missed/missed_YYYY-MM-DD.jsonl
          ├── ProcessScorer ────► scores/scores_YYYY-MM-DD.jsonl
          ├── CoordinationLogger ► coordination/coord_YYYY-MM-DD.jsonl
          ├── OrderLogger ──────► orders/orders_YYYY-MM-DD.jsonl
          ├── IndicatorLogger ──► indicators/ind_YYYY-MM-DD.jsonl
          ├── FilterLogger ─────► filter_decisions/filter_YYYY-MM-DD.jsonl
          └── OrderBookLogger ──► orderbook/ob_YYYY-MM-DD.jsonl

Asyncio Tasks (5, created after bootstrap):
├── _run_daily_snapshot  → 16:05 ET weekdays → daily/daily_YYYY-MM-DD.json
├── _run_backfill        → every 5 min → missed opportunity outcome backfill via IBKR
├── _run_heartbeat       → every 60s → heartbeat/hb_YYYY-MM-DD.jsonl (all 5 kits)
├── _run_config_check    → every 5 min → config_changes/cfg_YYYY-MM-DD.jsonl
└── _run_post_exit_backfill → every 30 min → post_exit/post_exit_YYYY-MM-DD.jsonl
```

**Shared context**: `bootstrap_instrumentation()` creates one `InstrumentationContext` with a single sidecar, snapshot service, regime classifier, and trackers. `bootstrap_kit(strategy_id=X, shared_ctx=ctx)` creates per-strategy kits that share the parent context's sidecar and services but have their own trade/missed/order loggers with `bot_id = strategy_id`.

### B.2 Core Modules

| Module | File | Purpose |
|--------|------|---------|
| **Facade** | `kit.py` | `InstrumentationKit` — single entry point: `log_entry`, `log_exit`, `log_missed`, `classify_regime`, `capture_snapshot`, `on_order_event`, `on_indicator_snapshot`, `on_filter_decision`, `on_orderbook_context`, `emit_heartbeat`, `check_config_changes` |
| **Context** | `context.py` | `InstrumentationContext` — bundles all services, owns `start()`/`stop()` (sidecar lifecycle) |
| **Bootstrap** | `bootstrap.py` | `bootstrap_instrumentation()` and `bootstrap_kit()` factories; `_bootstrap_kit_from_shared()` for per-strategy contexts |
| **Event Metadata** | `event_metadata.py` | Deterministic event IDs (SHA256 truncated to 16 hex chars), dual timestamps (exchange + local), clock skew computation |
| **Trade Logger** | `trade_logger.py` | Entry/exit events with full context (signal, filters, regime, slippage, params snapshot); `amend_last_event()` for retroactive score injection; `bot_id` and process quality alias fields for trading_assistant compatibility |
| **Missed Opportunity** | `missed_opportunity.py` | Logs blocked signals with hypothetical outcome backfill (simulated TP/SL from candle walk via `run_backfill()`) |
| **Process Scorer** | `process_scorer.py` | Rules-based quality scoring (0–100) with 21 controlled root-cause tags; `score_and_write()` writes to `scores/` JSONL; per-strategy rule overrides |
| **Market Snapshot** | `market_snapshot.py` | Captures bid/ask/mid/spread/ATR/volume at trade time and on interval |
| **Daily Snapshot** | `daily_snapshot.py` | End-of-day rollup at 16:05 ET: trade counts, PnL, profit factor, regime breakdown, missed stats, process quality distribution |
| **Regime Classifier** | `regime_classifier.py` | Deterministic rules: MA slope + ADX + ATR percentile → trending_up/trending_down/ranging/volatile/unknown |
| **Session Classifier** | `session_classifier.py` | Returns `{market_session, minutes_into_session}` — PRE/RTH/ETH_POST/WEEKEND |
| **Drawdown Tracker** | `drawdown_tracker.py` | Tracks peak equity, drawdown %, tier (NORMAL/CAUTION/DANGER/HALT at 5/10/15%), position size multiplier |
| **Overnight Gap Tracker** | `overnight_gap_tracker.py` | `record_close()` + `compute_gap()` → `{overnight_gap_pct, prev_close_price}` |
| **Post-Exit Tracker** | `post_exit_tracker.py` | Scans trade JSONL for exits missing post-exit data; fetches +1h/+4h prices via `IBKRHistoricalProvider`; amends trade records in-place and writes to `post_exit/` JSONL |
| **Coordination Logger** | `coordination_logger.py` | Cross-strategy events (ATRSS entry → Helix stop tightening) to `coordination/` JSONL |
| **Order Logger** | `order_logger.py` | Order lifecycle events (NEW/MODIFY/CANCEL) to `orders/` JSONL |
| **Indicator Logger** | `indicator_logger.py` | Per-bar indicator snapshots with decision outcome to `indicators/` JSONL |
| **Filter Logger** | `filter_logger.py` | Per-filter pass/fail decisions to `filter_decisions/` JSONL |
| **OrderBook Logger** | `orderbook_logger.py` | Bid/ask depth at entry and exit to `orderbook/` JSONL |
| **Experiment Registry** | `experiment_registry.py` | Reads `experiments.yaml`, assigns A/B variant by trade_id hash, tracks active experiments |
| **Config Watcher** | `config_watcher.py` | Detects config/module-level parameter changes, logs to `config_changes/` JSONL |
| **IBKR Provider** | `ibkr_provider.py` | Thread-safe bridge between sync instrumentation backfill and async IBKR event loop; implements `get_price_at()` and `get_ohlcv()` |
| **PG Bridge** | `pg_bridge.py` | `InstrumentedTradeRecorder` — decorator over `TradeRecorder` (PostgreSQL), calls `kit.log_entry/log_exit` best-effort after PG writes |
| **Hooks** | `hooks.py` | `safe_instrument()` — exception-swallowing wrapper used by kit methods |
| **Sidecar** | `sidecar.py` | Background forwarder: reads all 15 JSONL dirs via watermark tracking, wraps in relay envelope with `bot_id`, HMAC-SHA256 signs, gzip compresses, sends with retry + exponential backoff |

### B.3 Configuration Files

| File | Purpose |
|------|---------|
| `instrumentation/config/instrumentation_config.yaml` | Central config: bot_id (`swing_multi_01`), data_dir, snapshot intervals, sidecar relay URL, batch size, retry settings |
| `instrumentation/config/simulation_policies.yaml` | Per-strategy assumptions for missed opportunity backfill: entry fill model, slippage (all 2 bps for IBKR), fees, TP/SL logic |
| `instrumentation/config/regime_classifier_config.yaml` | ADX/MA/ATR thresholds for regime classification |
| `instrumentation/config/process_scoring_rules.yaml` | Scoring rules per dimension (regime fit, signal strength, entry latency, slippage, exit reason) with per-strategy overrides |

### B.4 Process Quality Root Causes (Controlled Taxonomy)

The process scorer uses exactly 21 fixed tags — no free-form text:

| Category | Tags |
|----------|------|
| Regime | `regime_mismatch`, `regime_aligned`, `regime_unknown` |
| Signal | `weak_signal`, `strong_signal`, `conflicting_signals` |
| Entry | `late_entry`, `early_entry`, `good_entry` |
| Slippage | `high_entry_slippage`, `high_exit_slippage`, `low_slippage` |
| Exit | `premature_exit`, `late_exit`, `good_exit`, `stop_loss_hit`, `take_profit_hit` |
| Result | `normal_win`, `normal_loss`, `exceptional_win` |
| Misc | `oversize_position`, `funding_drag` |

### B.5 Data Directory Structure

```
instrumentation/data/
├── trades/            # Trade entry/exit events (JSONL)
├── missed/            # Blocked signal events (JSONL)
├── scores/            # Process quality scores (JSONL)
├── snapshots/         # Market snapshots (JSONL)
├── daily/             # Daily aggregate snapshots (JSON)
├── post_exit/         # Post-exit price tracking (+1h/+4h) (JSONL)
├── coordination/      # Cross-strategy coordination events (JSONL)
├── orders/            # Order lifecycle events (JSONL)
├── indicators/        # Per-bar indicator snapshots (JSONL)
├── filter_decisions/  # Per-filter pass/fail decisions (JSONL)
├── orderbook/         # Bid/ask depth at entry/exit (JSONL)
├── heartbeat/         # Strategy heartbeat events (JSONL)
├── config_changes/    # Config parameter change events (JSONL)
├── errors/            # Instrumentation error events (JSONL)
└── .sidecar_buffer/   # Sidecar watermark state
```

**Sidecar priority ladder** (lower = more urgent): errors=1, trade exits=2, trades/missed/daily/orders=3, scores/post_exit/coordination/heartbeat/orderbook=4, indicators/filter_decisions=5.

### B.6 Docker Deployment

The `Dockerfile` copies `instrumentation/` into strategy containers. Each strategy container in `docker-compose.yml` has:

- **Named volume** for `instrumentation/data/` — persists JSONL files across container restarts so the sidecar can forward them
- **`INSTRUMENTATION_HMAC_SECRET`** env var — loaded from `.env` via `env_file` for sidecar → relay HMAC signing. Do **not** duplicate this in the `environment:` section — compose `${...}` expansion resolves from the host shell (where it's unset) and would override the `env_file` value with empty string.
- **`RELAY_URL`** — set in the `environment:` section to override the `.env` default. The portfolio launcher (host networking) uses `http://127.0.0.1:8001/events`; standalone strategy containers use `http://host.docker.internal:8001/events`.

```yaml
# Per-strategy container additions (already in docker-compose.yml):
env_file:
  - ../.env          # provides INSTRUMENTATION_HMAC_SECRET (+ all other vars)
environment:
  RELAY_URL: "http://host.docker.internal:8001/events"  # or 127.0.0.1 for host networking
volumes:
  - instrumentation_<strategy>:/app/instrumentation/data
```

**Relay URL handling:** The sidecar checks `RELAY_URL` env var first, then falls back to `relay_url` in the config YAML. The docker-compose sets `RELAY_URL` per service: `http://127.0.0.1:8001/events` for the portfolio launcher (host networking) and `http://host.docker.internal:8001/events` for standalone strategy containers (bridge networking). The config YAML defaults to `http://127.0.0.1:8001/events` for non-Docker runs. No manual config changes needed for either deployment mode.

### B.7 Key Design Decisions

- **Fault tolerant**: All instrumentation code is wrapped in try/except via `safe_instrument()`. A logger failure never blocks trade execution.
- **Disk first**: Events are written to local JSONL files immediately. The sidecar forwards them asynchronously.
- **Shared context, per-strategy kits**: One `InstrumentationContext` per process, with per-strategy `InstrumentationKit` instances that share the sidecar, snapshot service, and trackers but have independent trade/missed/order loggers keyed by `bot_id = strategy_id`.
- **bot_id mapping**: Each event's `bot_id` field carries the strategy name (e.g. `"ATRSS"`, `"AKC_HELIX"`). The sidecar's relay envelope uses the shared context's `bot_id` (`"swing_multi_01"`). The relay enforces envelope-level bot_id matching for HMAC auth.
- **Process quality integration**: On trade exit, `kit.log_exit()` scores the trade via `ProcessScorer`, writes to `scores/`, then amends the trade record with `process_quality_score`, `root_causes`, and `evidence_refs` via `amend_last_event()`. Default score of 100 prevents trading_assistant Pydantic validation failures.
- **Post-exit tracking**: `PostExitTracker` waits 4+ hours after exit, fetches +1h/+4h prices via `IBKRHistoricalProvider` (thread-safe bridge to async IBKR event loop), amends trade records in-place, and writes separate `post_exit/` JSONL files.
- **Deterministic event IDs**: `SHA256(bot_id|timestamp|event_type|payload_key)[:16]` prevents duplicate processing downstream.
- **HMAC canonicalization**: Sidecar uses `json.dumps(data, sort_keys=True)` before signing. Mismatch causes silent 401 rejections.
- **Per-strategy simulation policies**: Missed opportunity backfill uses strategy-specific assumptions (ATRSS uses atr_offset entry fill, S5_PB uses market fill, etc.).

### B.8 Tests

19 instrumentation test files + 1 relay test file:

| Test File | Coverage |
|-----------|----------|
| `test_kit.py` | Kit facade methods, fault tolerance, log_entry/log_exit flow |
| `test_bootstrap.py` | bootstrap_instrumentation, bootstrap_kit, shared context wiring |
| `test_trade_logger.py` | Entry/exit, PnL (long+short), fault tolerance, slippage, amend_last_event, bot_id |
| `test_missed_opportunity.py` | Event creation, assumption tags, simulation policy, backfill queue |
| `test_process_scorer.py` | Perfect/bad trades, taxonomy enforcement, bounds, classification, per-strategy overrides |
| `test_event_metadata.py` | Determinism, uniqueness, hex format, clock skew, factory |
| `test_market_snapshot.py` | Capture, file writing, degraded mode, caching, dict provider |
| `test_daily_snapshot.py` | Trades, no data, missed, scores, regime breakdown, profit factor |
| `test_regime_classifier.py` | Valid regime, trending, insufficient data, caching, crash safety |
| `test_session_classifier.py` | PRE/RTH/ETH_POST/WEEKEND classification |
| `test_drawdown_tracker.py` | Peak tracking, tier thresholds, size multiplier |
| `test_overnight_gap_tracker.py` | Close recording, gap computation |
| `test_post_exit_tracker.py` | Backfill scheduling, price fetching, record amendment |
| `test_coordination_logger.py` | Cross-strategy event logging |
| `test_order_logger.py` | Order lifecycle events |
| `test_sidecar.py` | Wrap event, watermark, HMAC signing, canonical sort_keys, gzip |
| `test_pg_bridge.py` | InstrumentedTradeRecorder decorator |
| `test_bot_side_changes.py` | bot_id field, trading_assistant alias fields |
| `test_integration.py` | Full day lifecycle, fault tolerance, unique event IDs |
| `test_relay.py` | Store CRUD, HMAC auth, rate limiting, full API (ingest/pull/ack/duplicates, gzip, priority coercion, API key auth, health enrichment) |

```bash
# Run all instrumentation + relay tests
PYTHONPATH="$(pwd):$PYTHONPATH" python -m pytest instrumentation/tests/ relay/tests/ -v
```

---

## Appendix C: Relay Service Internals

The relay is a lightweight FastAPI app (~100 lines of meaningful code) that buffers events from all trading bots and serves them to the home orchestrator on demand. It runs on the same VPS as the bot, backed by SQLite. For deployment steps, see Part 6.

### C.1 API Endpoints

| Method | Endpoint | Auth | Purpose |
|--------|----------|------|---------|
| `POST /events` | HMAC-SHA256 (`X-Signature`) | Bots push event batches (gzip supported) |
| `GET /events?since=<watermark>&limit=100&bot_id=<id>` | API key (`X-Api-Key`) | Home orchestrator pulls un-acked events |
| `POST /ack` | API key (`X-Api-Key`) | Home orchestrator confirms receipt up to a watermark |
| `POST /admin/purge` | API key (`X-Api-Key`) | Purge acked events older than retention period |
| `GET /health` | None | Health check with enriched stats (pending count, DB size, per-bot breakdown) |

### C.2 Components

| File | Purpose |
|------|---------|
| `relay/app.py` | FastAPI app factory with Pydantic request/response models |
| `relay/auth.py` | HMAC-SHA256 verification — per-bot secrets from JSON file; auth disabled if no secrets configured |
| `relay/db/store.py` | SQLite store: `insert_events()` (duplicate rejection via UNIQUE event_id), `get_events()` (watermark + bot_id filter), `ack_up_to()` |
| `relay/db/schema.sql` | `events` table with indexes on `acked`, `bot_id`, `event_id`, `received_at` |
| `relay/rate_limiter.py` | Sliding window rate limiter (default 60 req/min per bot) |

### C.3 Testing the Relay

```bash
# Health check
curl -s http://127.0.0.1:8001/health
# {"status": "ok", "pending_events": 0}

# HMAC-signed ingest test
python3 -c "
import hashlib, hmac, json, urllib.request
secret = 'your-secret-here'
payload = {'bot_id': 'swing_multi_01', 'events': [{'event_id': 'test-001', 'bot_id': 'swing_multi_01', 'event_type': 'heartbeat', 'payload': '{}'}]}
canonical = json.dumps(payload, sort_keys=True)
sig = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
req = urllib.request.Request('http://127.0.0.1:8001/events', data=canonical.encode(), headers={'Content-Type': 'application/json', 'X-Signature': sig}, method='POST')
print(json.loads(urllib.request.urlopen(req).read()))
"
# {"accepted": 1, "duplicates": 0}
```

### C.4 Maintenance

| Action | Command |
|--------|---------|
| Check status | `sudo systemctl status trading-relay` |
| View logs | `journalctl -u trading-relay --since "1 hour ago"` |
| Check DB size | `du -h /opt/trading-relay/data/relay.db` |
| Purge acked events | `sqlite3 /opt/trading-relay/data/relay.db "DELETE FROM events WHERE acked = 1; VACUUM;"` |
| Restart after code update | `sudo systemctl restart trading-relay` |

---

## Appendix D: Key Configuration Reference

### D.1 Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SWING_TRADER_ENV` | `paper` | Environment mode: `dev`, `backtest`, `paper`, `live` |
| `IB_ACCOUNT_ID` | `DU_PLACEHOLDER` | IBKR account ID (DU prefix = paper, U prefix = live) |
| `IB_HOST` | `host.docker.internal` | IB Gateway hostname (from Docker container's perspective) |
| `IB_PORT` | `4002` | IB Gateway port (4002 = paper, 4001 = live) |
| `POSTGRES_PASSWORD` | `changeme` | PostgreSQL admin password |
| `POSTGRES_READER_PASSWORD` | `changeme` | Read-only user password (trading dashboard) |
| `POSTGRES_WRITER_PASSWORD` | `changeme` | Writer user password (OMS) |
| `DB_HOST` | `postgres` | PostgreSQL host (Docker service name) |
| `DB_PORT` | `5432` | PostgreSQL port |
| `DB_NAME` | `trading` | Database name |
| `DB_USER` | `trading_writer` | Database user for OMS writes |
| `DB_PASSWORD` | `changeme` | Database password for OMS writes |
| `ATRSS_SYMBOL_SET` | `etf` | ATRSS symbols: `etf` (QQQ,GLD), `micro` (MNQ,MCL,MGC,MBT), `full` (NQ,CL,GC,BRR), `all` |
| `AKCHELIX_SYMBOL_SET` | `etf` | Helix symbols: `etf` (QQQ,GLD,IBIT), `micro_futures`, `full_futures`, `all` |
| `INSTRUMENTATION_HMAC_SECRET` | — | HMAC-SHA256 shared secret for sidecar → relay signing |
| `RELAY_SECRETS_FILE` | `/opt/trading-relay/secrets.json` | Path to bot_id → HMAC secret mapping (relay service) |
| `RELAY_DB_PATH` | `/opt/trading-relay/data/relay.db` | SQLite database path for relay event buffer |
| `RELAY_API_KEY` | — | API key for relay read/admin endpoints (`X-Api-Key` header); bypass in dev if empty |
| `RELAY_URL` | — | Relay URL (sidecar: `http://127.0.0.1:8001/events`; Docker: `http://host.docker.internal:8001/events`) |

### D.2 Risk Parameters (optimized_v2)

**Per-Strategy (from `main_multi.py` / `backtest/config_unified.py`):**

| Parameter | ATRSS | S5_PB | S5_DUAL | SWING_BREAKOUT_V3 | AKC_HELIX | Description |
|-----------|-------|-------|---------|-------------------|-----------|-------------|
| `unit_risk_pct` | **1.20%** | 0.80% | 0.80% | 0.50% | 0.50% | Base risk per trade as % of NAV |
| `daily_stop_R` | 2.0 | 2.0 | 2.0 | 2.0 | 2.5 | Max daily loss in R before strategy halts |
| `max_heat_R` | 1.00 | 1.50 | 1.50 | 0.65 | 0.85 | Per-strategy heat ceiling (max open risk in R) |
| `max_working_orders` | 4 | 2 | 2 | 2 | 4 | Max concurrent working orders |
| `priority` | 0 | 1 | 2 | 3 | 4 | Priority for heat reservation (0 = highest) |

**Portfolio-Level:**

| Parameter | Value | Description |
|-----------|-------|-------------|
| `heat_cap_R` | **2.0** | Total open risk across all strategies in R |
| `portfolio_daily_stop_R` | 3.0 | Portfolio-wide daily loss limit in R |

**Per-Symbol Risk (ATRSS `base_risk_pct`):**

| Symbol | base_risk_pct | Notes |
|--------|--------------|-------|
| QQQ | 0.60% | Shorts disabled, Dec size reduction 50% |
| GLD | 0.65% | Shorts disabled |
| MNQ | 1.00% | Default |
| MCL | 1.00% | Higher slippage tolerance |
| MGC | 1.00% | Default |
| MBT | 0.75% | Reduced due to volatility |

### D.3 Symbol Sets and Supported Instruments

**ETFs:**

| Symbol | Exchange | Description | Used By |
|--------|----------|-------------|---------|
| QQQ | SMART/NASDAQ | Nasdaq 100 ETF | ATRSS, Helix, Breakout |
| GLD | SMART/ARCA | Gold ETF | ATRSS, Helix, Breakout, S5_DUAL |
| USO | SMART/ARCA | Oil ETF | Helix, Breakout |
| IBIT | SMART/NASDAQ | Bitcoin ETF | Helix, Breakout, S5_PB, S5_DUAL |

**Micro Futures:**

| Symbol | Exchange | Multiplier | Tick Size | Used By |
|--------|----------|------------|-----------|---------|
| MNQ | CME | 2.0 | 0.25 | ATRSS, Helix |
| MCL | NYMEX | 100.0 | 0.01 | ATRSS, Helix |
| MGC | COMEX | 10.0 | 0.10 | ATRSS, Helix |
| MBT | CME | 0.1 | 5.0 | ATRSS, Helix |

**Full-Size Futures:**

| Symbol | Exchange | Multiplier | Tick Size | Used By |
|--------|----------|------------|-----------|---------|
| NQ | CME | 20.0 | 0.25 | ATRSS, Helix |
| CL | NYMEX | 1000.0 | 0.01 | ATRSS, Helix |
| GC | COMEX | 100.0 | 0.10 | ATRSS, Helix |
| BT | CME | 5.0 | 5.0 | Helix |

### D.4 Important File Paths (VPS)

| Path | Purpose |
|------|---------|
| `/opt/trading/swing_trader/` | Application root |
| `/opt/trading/swing_trader/.env` | Environment configuration |
| `/opt/trading/swing_trader/infra/docker-compose.yml` | Docker service definitions |
| `/opt/ibgateway/` | IB Gateway installation |
| `/opt/ibc/` | IBC installation |
| `/opt/ibc/config/config.ini` | IBC credentials and settings |
| `/etc/systemd/system/ibgateway.service` | systemd service for IB Gateway |
| `/opt/trading/swing_trader/instrumentation/data/` | Instrumentation JSONL event files |
| `/opt/trading/swing_trader/instrumentation/config/` | Instrumentation configuration |
| `/opt/trading-relay/` | Relay service installation |
| `/opt/trading-relay/data/relay.db` | Relay SQLite event buffer |
| `/opt/trading-relay/secrets.json` | Bot HMAC shared secrets |
| `/etc/systemd/system/trading-relay.service` | systemd service for relay |
| `/var/log/trading/` | Application logs (retention, backups) |
| `/opt/trading/backups/` | Database backups |

### D.5 Database Roles

| Role | Permissions | Used By |
|------|-------------|---------|
| `trading_admin` | Superuser (creates tables, manages roles) | PostgreSQL admin, init-db.sql |
| `trading_writer` | SELECT, INSERT, UPDATE, DELETE on `public` schema | OMS, strategy containers |
| `trading_reader` | SELECT only on `public` schema | Trading dashboard (Next.js API routes) |

### D.6 Docker Services

| Service | Container Name | Profile | Port | Image |
|---------|----------------|---------|------|-------|
| postgres | `trading_postgres` | (always) | 5432 | `postgres:16-alpine` |
| dashboard | `trading_dashboard` | (always) | 3000 | Built from `infra/dashboard/Dockerfile` |
| portfolio | `trading_portfolio` | `portfolio` | — | Built from `Dockerfile`; runs `main_multi.py` |
| atrss | `trading_atrss` | `atrss` | — | Built from `Dockerfile` |
| akc_helix | `trading_akc_helix` | `akc_helix` | — | Built from `Dockerfile` |
| swing_breakout | `trading_swing_breakout` | `swing_breakout` | — | Built from `Dockerfile` |

**Non-Docker Services (systemd):**

| Service | Unit File | Port | Description |
|---------|-----------|------|-------------|
| IB Gateway | `ibgateway.service` | 4002 | Headless IB Gateway via IBC + Xvfb |
| Trading Relay | `trading-relay.service` | 8001 | FastAPI event buffer (SQLite-backed) |

---

## Appendix E: Future Work

### E.1 Automated Data Pipeline

**Historical note (superseded):**

Schedule historical data refresh for backtesting:

- Daily download of OHLCV data for all tracked symbols
- Update parquet cache in `data/` directory
- Run on the VPS or a separate machine (not during trading hours to avoid API rate limits)

```bash
# Example cron (weekdays at 18:00 ET, after market close)
0 18 * * 1-5 cd /opt/trading/swing_trader && python -m backtest download --duration "1 M"
```

### E.2 Enhanced Monitoring — Slack/Telegram Alerts

**Priority: Medium**

Add real-time alerts for critical events:

- **Fills**: Notify on every fill (entry, exit, partial)
- **Halts**: Notify when any strategy or the portfolio hits a daily stop
- **Disconnections**: Notify when IB Gateway disconnects (beyond the expected daily reset)
- **Errors**: Notify on order rejections, reconciliation discrepancies
- **Daily summary**: End-of-day P&L summary across all strategies

### E.3 Crash Recovery — State Checkpointing

**Priority: Medium**

Add strategy state persistence to PostgreSQL for crash recovery:

- Checkpoint position state, pending orders, and indicator buffers to the database periodically
- On restart, load the last checkpoint and resume from the correct state
- Currently, strategies rely on IB reconciliation to rebuild state — explicit checkpointing would improve recovery time and accuracy

### E.4 Strategy 3 Tuning — Resolve TUNE_* Flags

**Historical note (superseded):**

`strategy_3/config.py` has several tuning flags, some reverted to baseline:

| Flag | Status | Notes |
|------|--------|-------|
| `TUNE_COMPRESSION` | `True` | Active — relaxed squeeze/containment thresholds |
| `TUNE_DISPLACEMENT` | `True` | Active — lowered displacement quantile |
| `TUNE_SCORE` | `True` | Active — lowered score threshold |
| `TUNE_ENTRY_UNLOCK` | `True` | Active — relaxed entry gates, neutral regime allowed |
| `TUNE_TP_TARGETS` | `False` | **Reverted** — baseline TPs now achievable with tighter stops |
| `TUNE_REENTRY` | `True` | Active — relaxed re-entry cooldown, DIRTY gates |
| `TUNE_CONTINUATION` | `False` | **Reverted** — blocks Entry A/B by entering continuation too early |
| `TUNE_PORTFOLIO` | `True` | Active — wider portfolio heat/pending/hard block |
| `TUNE_REGIME_MULT` | `False` | **Reverted** — marginal sizing-only, risks larger caution losses |
| `TUNE_STALE` | `False` | **Reverted** — hurts 3/4 symbols (only helps GLD) |

Further backtesting and walk-forward analysis may identify opportunities to re-enable reverted flags or tune active ones.

---

## Appendix F: Implementation History

### F.1 Strategy 4 Live Engine (S5_PB / S5_DUAL) — DONE

**Status: Complete**

`strategy_4/engine.py` implements `KeltnerEngine` — the simplest live engine in the system (daily bars only, no intraday). A single class is instantiated twice: once as S5_PB (IBIT pullback) and once as S5_DUAL (GLD+IBIT dual mode).

**Implementation:**

- `strategy_4/engine.py` (751 lines) — `KeltnerEngine` with daily scheduler at 16:15 ET, `_compute_state()` producing `DailyState`, entry/exit signal evaluation via `strategy_4/signals.py`, risk-based position sizing, trailing stop ratcheting at R >= 1.0, and OMS event processing for fills/cancels.
- `strategy_4/config.py` — `S5_PB_CONFIGS` (IBIT pullback, ema=10, roc=5, stop=1.5 ATR, risk=0.8%) and `S5_DUAL_CONFIGS` (GLD+IBIT dual, ema=15, no shorts, rsi_long=45, risk=0.8%). Includes `build_instruments()` for InstrumentRegistry.
- `main_multi.py` — Both engines wired with priority ordering: ATRSS(0), S5_PB(1), S5_DUAL(2), Breakout(3), Helix(4).

**Live configs verified against `portfolio_optimized_v2.txt`:**

| Parameter | Backtest | Live | Match |
|-----------|----------|------|-------|
| S5_PB symbols | IBIT | IBIT | Yes |
| S5_PB entry_mode | pullback | pullback | Yes |
| S5_PB kelt_ema | 10 | 10 | Yes |
| S5_PB roc_period | 5 | 5 | Yes |
| S5_PB atr_stop_mult | 1.5 | 1.5 | Yes |
| S5_PB risk_pct | 0.008 | 0.008 | Yes |
| S5_PB priority | 1 | 1 | Yes |
| S5_PB max_heat_R | 1.50 | 1.50 | Yes |
| S5_DUAL symbols | GLD, IBIT | GLD, IBIT | Yes |
| S5_DUAL entry_mode | dual | dual | Yes |
| S5_DUAL kelt_ema | 15 | 15 | Yes |
| S5_DUAL shorts_enabled | False | False | Yes |
| S5_DUAL rsi_entry_long | 45.0 | 45.0 | Yes |
| S5_DUAL risk_pct | 0.008 | 0.008 | Yes |
| S5_DUAL priority | 2 | 2 | Yes |
| S5_DUAL max_heat_R | 1.50 | 1.50 | Yes |
| heat_cap_R | 2.0 | 2.0 | Yes |
| portfolio_daily_stop_R | 3.0 | 3.0 | Yes |

**Deployment note:** `infra/docker-compose.yml` already includes the multi-strategy launcher as service `portfolio`. That is the default production deployment because it preserves the portfolio-level coordinator.

### F.2 Unit Test Suite — DONE

**Status: Complete (884 tests passing)**

Full pytest coverage across all strategies, OMS integration, and paper trading:

```
tests/
├── conftest.py                  # Shared OHLCV data generators
├── test_strategy1_atrss.py      # 88 tests — indicators, signals, stops, allocator
├── test_strategy2_helix.py      # 98 tests — indicators, signals, stops, allocator, gates
├── test_strategy3_breakout.py   # 87 tests — indicators, signals, stops, allocator, gates
├── test_strategy4_keltner.py    # 74 tests — indicators, models, signals (4 entry modes, 3 exit modes), config
├── test_oms_integration.py      # 263 tests — risk gateway, fill processor, state machine, intent handler, event bus
├── test_paper_trading.py        # 219 tests — IBKR adapter, contract factory, execution, reconciliation
└── test_market_calendar.py      # 55 tests — holiday/half-day calendar (see F.3)
```

**Strategy 4 test coverage** (`test_strategy4_keltner.py`, 74 tests across 17 classes):
- **Indicators**: EMA (SMA seed, convergence, lag), ATR (Wilder smoothing, volatility), RSI (bounds, monotonic, zero-loss), ROC (percentage, boundary), Keltner Channel (symmetry, band width), Volume SMA (expanding window, rolling)
- **Models**: Direction (arithmetic, negation), DailyState (defaults, 12 fields)
- **Signals — Entry**: Breakout (long/short, condition gating, shorts_enabled), Pullback (crossover, boundary), Momentum (RSI crossover, midline gate), Dual (breakout-first fallthrough), Volume Filter (block/pass/disabled/zero-SMA/equality)
- **Signals — Exit**: Trail-only (always false), Midline (cross detection), Reversal (full conditions only)
- **Config**: SYMBOL_CONFIGS keys, S5_PB/S5_DUAL variants, frozen dataclass, build_instruments

### F.3 Market Calendar Integration — DONE

**Status: Complete**

`shared/market_calendar.py` provides holiday and half-day awareness using pure Python stdlib (no external dependencies). Year-cached via `@lru_cache`.

**Asset classes:**
- `AssetClass.EQUITY` — NYSE/NASDAQ: 10 holidays/year (New Year's, MLK, Presidents', Good Friday, Memorial, Juneteenth, Independence, Labor, Thanksgiving, Christmas)
- `AssetClass.CME_FUTURES` — CME/COMEX/NYMEX: 7 holidays/year (excludes MLK, Presidents', Juneteenth)
- Half days (3/year): day before Independence Day, Black Friday, Christmas Eve — early close 1:00 PM ET

**Public API:** `MarketCalendar` class with `is_market_holiday()`, `is_half_day()`, `is_trading_day()`, `next_trading_day()`, `market_close_time_et()`, `is_entry_blocked()`.

**Integration points:**
- `shared/oms/risk/gateway.py` — New check between event blackout and session block. Uses `order.instrument.venue` to select EQUITY vs CME_FUTURES calendar, so CME futures aren't blocked on equity-only holidays.
- `shared/oms/services/factory.py` — Both `build_oms_service()` and `build_multi_strategy_oms()` accept optional `market_calendar` parameter, wired to `RiskGateway`.
- Engine schedulers — `strategy_3/engine.py` and `strategy_4/engine.py` daily schedulers skip holidays in addition to weekends. `strategy/engine.py` `_is_rth()` helper checks holidays to avoid bar fetch attempts on closed days.
- `main_multi.py` — Creates one shared `MarketCalendar()` instance, passes to OMS factory and all five engine constructors.

**Tests:** `test_market_calendar.py` (55 tests) — Easter/Good Friday (2024-2030), observed rules (Sat→Fri, Sun→Mon), floating holidays, holiday counts, half-days, entry blocking (holiday/half-day noon cutoff/normal), trading day logic, CME vs equity differences (MLK: equity closed, CME open), year caching, market close times.

### F.4 Next.js Trading Dashboard — DONE

**Status: Complete**

Purpose-built Next.js 14 dashboard in `infra/dashboard/` replaces Metabase on port 3000. Connects directly to the `trading` PostgreSQL database as `trading_reader`.

**Tech stack:** Next.js 14 (`output: 'standalone'`), TypeScript, Tailwind CSS, Recharts, node-postgres (`pg`).

**File structure:**
```
infra/dashboard/
├── Dockerfile                    ← multi-stage build (deps → builder → runner)
├── package.json                  ← next 14.2, pg 8.12, recharts 2.12, lucide-react
├── next.config.ts                ← output: 'standalone', serverExternalPackages: ['pg']
├── src/app/
│   ├── layout.tsx / page.tsx     ← client component, dual-interval polling (30s / 5min)
│   └── api/                      ← 8 API routes (see §A.3)
├── src/components/               ← 10 React components (see §A.2)
└── src/lib/
    ├── db.ts                     ← pg Pool singleton, NUMERIC/INT8 type parsers
    ├── types.ts                  ← TypeScript interfaces + STRATEGY_CONFIG constants
    └── formatters.ts             ← fmtR, fmtUSD, fmtAge, fmtHoldTime, fmtDate, fmtTime
```

**STRATEGY_CONFIG** (embedded in `types.ts`, authoritative source for dashboard heat/priority display):
```ts
ATRSS:             { maxHeatR: 1.00, riskPct: 1.2, priority: 0 }
S5_PB:             { maxHeatR: 1.50, riskPct: 0.8, priority: 1 }
S5_DUAL:           { maxHeatR: 1.50, riskPct: 0.8, priority: 2 }
SWING_BREAKOUT_V3: { maxHeatR: 0.65, riskPct: 0.5, priority: 3 }
AKC_HELIX:         { maxHeatR: 0.85, riskPct: 0.5, priority: 4 }
```

These match the live risk configs in `main_multi.py` and the backtest `optimized_v2` preset.

See Appendix A for deployment, local dev, and API route details.

### F.5 Instrumentation & Relay Service — DONE

**Status: Complete — fully implemented, wired, and tested**

Full instrumentation layer (24 modules) in `instrumentation/` with relay service in `relay/`, fully integrated into `main_multi.py`. See Appendix B and Appendix C for detailed documentation.

**What was built:**
- **24 source modules** (`instrumentation/src/`): kit facade, context/bootstrap, trade logger (with `bot_id` and trading_assistant alias fields), missed opportunity logger (with hypothetical backfill), process quality scorer (21 root-cause taxonomy with per-strategy overrides), daily aggregates, regime/session/drawdown classifiers, overnight gap tracker, post-exit tracker (+1h/+4h price backfill via IBKR), coordination/order/indicator/filter/orderbook loggers, experiment registry, config watcher, IBKR provider (thread-safe async bridge), PG bridge, sidecar forwarder (HMAC-signed, gzip, priority-based batching, watermark tracking across 15 JSONL directories)
- **4 config files** (`instrumentation/config/`): central config, per-strategy simulation policies, regime classifier thresholds, process scoring rules with per-strategy overrides
- **Relay service** (`relay/`): FastAPI app with SQLite store, HMAC auth, API key auth for read/admin endpoints, rate limiting, watermark-based pull/ack, event purge, enriched health endpoint, systemd/nginx deployment templates
- **19 instrumentation test files + 1 relay test file**: comprehensive coverage of all modules
- **Codebase audit** (`instrumentation/audit_report.md`): documented all 5 strategies, 9 filters, exit triggers, 8 hook points
- **Full `main_multi.py` integration**: shared `InstrumentationContext` with per-strategy `InstrumentationKit` instances, 5 asyncio tasks (daily snapshot, missed opportunity backfill, heartbeat, config check, post-exit backfill), graceful shutdown with final snapshot
- **trading_assistant compatibility**: `TradeEvent` and `MissedOpportunityEvent` include `bot_id` top-level field plus process quality fields; `process_quality_score` defaults to 100 for Pydantic validation safety
