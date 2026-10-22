# Multi-Asset Portfolio — Phase 1: Data Pipeline

This is **Phase 1 only** of the "Modelling a Multi-Asset Portfolio" project (see [`FRD.md`](FRD.md)
/ [`FRD.docx`](FRD.docx), Sections 8.1, 8.4, 9, 10). It builds scheduled (REST, not tick/WebSocket)
ingestion, storage, and data-quality logging for **FX and equities only**.

Explicitly **not** in this phase (they are Phases 2–5): crypto ingestion, ADF/Engle-Granger/
Johansen cointegration testing, relationship-health monitoring, signal generation, risk
management, backtesting, paper-trading, and the dashboard.

## Known constraints — read before running

This phase uses two **budget-free data substitutes**, each documented per the FRD's own
transparency principle (Section 10: "actual running cost should be stated transparently"):

| Asset class | Institutional-grade option named in FRD | What's actually used here | Why |
|---|---|---|---|
| Equities | Refinitiv/LSEG, Bloomberg BPIPE, Polygon.io, EODHD | **Alpaca Market Data API, IEX feed** | This is the exact budget-free substitute the FRD names in Section 8.1 ("Alpaca IEX feed, US equities only, single-venue, not consolidated tape"). Free paper-trading credentials work. |
| FX | Refinitiv/LSEG, Bloomberg BPIPE, OANDA, Polygon.io FX | **Twelve Data, free "Basic" tier** | Not named in the FRD's FX list — added here as the budget-free FX substitute, following the same transparency principle. Free tier = 800 requests/day, 8 req/min, delayed/EOD-quality data, "internal, non-display use only" license. |

Other documented limitations (all deliberate, not oversights — see inline comments at the cited
locations):

- **FX cadence is pinned to 15 minutes**, the upper end of the FRD's 5–15 minute band (Section
  8.4), specifically to fit Twelve Data's 800-request/day free cap across an 8-pair universe:
  8 pairs × 96 cycles/day = 768 requests/day. A 10-minute cadence would need 1,152/day and blow
  the quota. See `config/universe.yaml`.
- **Equities universe is US large-caps only.** Alpaca's free IEX feed doesn't cover UK equities
  named in FRD Section 8.1; that would need a paid feed. Logged as a known Phase 1 limitation to
  revisit later, not silently dropped — see `config/universe.yaml`'s `equities.note`.
- **Gap detection is calendar-naive.** It flags any inter-bar gap beyond a configured tolerance,
  but doesn't know about market holidays/trading calendars, so an unusually long (but legitimate)
  holiday closure can still get flagged. See `pipeline/quality/checks.py`.

## Setup

1. **Python 3.11+** and a virtualenv:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate   # Windows; use `source .venv/bin/activate` on Linux/macOS
   pip install -r requirements.txt
   ```
2. **Database** — PostgreSQL + TimescaleDB via Docker Compose (applies `db/schema.sql`
   automatically on first start):
   ```bash
   docker compose up -d
   ```
3. **API keys** — copy `.env.example` to `.env` and fill in:
   - `TWELVEDATA_API_KEY` — free signup at twelvedata.com
   - `ALPACA_API_KEY_ID` / `ALPACA_API_SECRET_KEY` — free paper-trading account at alpaca.markets
   - `DATABASE_URL` — defaults already match `docker-compose.yml`
   - `ALERT_WEBHOOK_URL` — optional; leave blank to log-only

## Running it

**Backfill** (historical) — one asset class + interval at a time:
```bash
python -m pipeline.backfill --asset-class fx --interval 1hour --start 2024-01-01 --end 2024-06-01
python -m pipeline.backfill --asset-class equity --interval 1day --start 2022-01-01 --end 2024-01-01
```

**One incremental cycle** (for cron):
```bash
python -m pipeline.run_once --asset-class fx --interval 1hour
```
Example crontab lines for the always-on deployment target (FRD Section 10):
```
*/15 * * * * cd /path/to/repo && .venv/bin/python -m pipeline.run_once --asset-class fx --interval 1hour
0    *    * * * cd /path/to/repo && .venv/bin/python -m pipeline.run_once --asset-class fx --interval 1day
0    *    * * * cd /path/to/repo && .venv/bin/python -m pipeline.run_once --asset-class equity --interval 1hour
30   0    * * * cd /path/to/repo && .venv/bin/python -m pipeline.run_once --asset-class equity --interval 1day
```

**Or the built-in loop-based scheduler** (runs all four jobs on their own configured cadence in
one process — the FRD's other explicitly-allowed MVP option, Section 10):
```bash
python -m pipeline.scheduler
```

## Tests

```bash
pytest -q
```
Tests cover quality checks, derived-stats math, the rate limiter, both provider clients
(mocked HTTP, no network/API key needed), payload parsing, and the full ingest_runner
orchestration against an in-memory repository (`tests/fakes.py`) — including the failure
paths (feed down, malformed bar, data gap) that the checklist below asks you to verify.

## Verifying this phase (per the Phase 1 review checklist)

- **Backfill + incremental land raw and derived data:** run a backfill, then a `run_once`
  incremental cycle, and query `bars` and `derived_bar_stats` in Postgres for the same
  `asset_id`/`interval`.
- **Force a failure and confirm it's logged, not dropped:** temporarily point
  `TWELVEDATA_API_KEY` at an invalid value, or stop your network, and run `run_once` — check
  `data_quality_events` for a `feed_downtime` row, and `logs/pipeline.log` for the matching
  log line. To see a malformed-record case without touching real credentials, run
  `pytest tests/test_ingest_runner.py -v` and read
  `test_malformed_bar_is_excluded_and_logged_not_silently_dropped`.
- **Crypto is not included:** `config/universe.yaml` has no `crypto` section; `pipeline/jobs.py`'s
  `ASSET_CLASSES` is `("fx", "equity")` only.
- **Cadence matches spec:** FX `1hour` interval cadence is 15 minutes, equities `1hour` is 60
  minutes — both scheduled REST pulls (`pipeline/scheduler.py`, `config/universe.yaml`); there is
  no WebSocket/streaming code anywhere in this phase.
- **Budget-free substitutions are documented, not presented as equivalent:** see the table above
  and the inline comments in `.env.example`, `config/universe.yaml`, `pipeline/sources/alpaca_client.py`,
  and `pipeline/sources/twelvedata_client.py`.
- **Runs from a clean checkout:** `pip install -r requirements.txt`, `docker compose up -d`,
  copy `.env.example` → `.env` and fill in keys, then any command under "Running it" above.

## Repository layout

```
config/universe.yaml       FX pairs, equity universe, cadences, provider codes, tolerances
db/schema.sql               PostgreSQL/TimescaleDB schema (bars, derived stats, runs, quality events)
docker-compose.yml           Local TimescaleDB instance
pipeline/
  config.py                  Loads .env + universe.yaml into typed Settings
  exceptions.py               FeedDownError / MalformedPayloadError / RateLimitExceededError / ConfigError
  repository.py                Repository ABC + PostgresRepository (psycopg2)
  sources/
    base.py                    Bar + DataSource interface
    twelvedata_client.py         FX HTTP client (rate-limited, retrying)
    alpaca_client.py              Equities HTTP client (rate-limited, retrying)
    fx_source.py / equity_source.py   Parse provider payloads into Bar objects
  quality/checks.py             validate_bar() + detect_gaps()
  derived/stats.py               log return + rolling mean/std (NOT the cointegration engine)
  ingest_runner.py                Core orchestration: ingest -> validate -> persist -> log
  jobs.py                          Wires Settings -> ingest_runner for a given (asset_class, interval)
  backfill.py / run_once.py / scheduler.py   CLI entrypoints
tests/                            Unit tests, including an in-memory Repository fake
```
