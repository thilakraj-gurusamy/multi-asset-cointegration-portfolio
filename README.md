# Multi-Asset Portfolio — Phase 1 + 2

"Modelling a Multi-Asset Portfolio" project (see [`FRD.md`](FRD.md) / [`FRD.docx`](FRD.docx)).
Built and verified phase by phase, per `FRD_Phases_MasterPrompts.docx`'s Phase 1→5 breakdown.

- **Phase 1 — Data Pipeline** (FRD Sections 8.1, 8.4, 9, 10): scheduled (REST, not tick/
  WebSocket) ingestion, storage, and data-quality logging for FX and equities.
- **Phase 2 — Cointegration Engine** (FRD Section 8.2): rolling-window ADF, Engle-Granger, and
  Johansen testing on top of the Phase 1 store.

Explicitly **not** in these phases (they are Phases 3–5): crypto ingestion, relationship-health
gating/thresholds, hedge-ratio/half-life drift tracking, signal generation, risk management,
walk-forward backtesting, paper-trading, and the dashboard.

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

## Phase 2: running the cointegration engine

Operates on **daily ("1day") bars only** from the Phase 1 store — a deliberate scope
narrowing, not an oversight; see the `cointegration:` section comment in
`config/universe.yaml`. Backfill daily history first (needs at least `window_bars`, default 90,
aligned trading days across every symbol in the asset class):

```bash
python -m pipeline.backfill --asset-class fx --interval 1day --start 2022-01-01 --end 2024-06-01
python -m pipeline.backfill --asset-class equity --interval 1day --start 2022-01-01 --end 2024-06-01
python -m pipeline.cointegration.run --asset-class fx --start 2022-01-01 --end 2024-06-01
python -m pipeline.cointegration.run --asset-class equity --start 2022-01-01 --end 2024-06-01
```

For every rolling window it: ADF-pre-tests every symbol (excluding non-I(1) series, logged via
`adf_results`); runs Engle-Granger in **both** regressand directions on every pair of
ADF-passing symbols; runs a **bivariate Johansen test on that same pair** specifically to
compare against Engle-Granger (`method_disagreements` flags disagreement); and runs Johansen on
the configured 3+-asset baskets (`cointegrating_vectors`/`adjustment_speeds`, JSONB). No health
gating, no drift tracking, no signals — raw per-window numbers only (Phase 3 consumes these).

**Real findings from validating this against live-backfilled history** (not bugs — each was
independently re-derived outside this codebase before being accepted; see inline comments in
`pipeline/cointegration/johansen.py` and `engle_granger.py`):
- EUR/USD vs GBP/USD showed statistically significant cointegration (p≈0.004) with an
  unrealistic sub-1-day half-life in one window — exactly the kind of result the FRD's Phase 3
  half-life sanity band (5–60 days) exists to catch; significance alone isn't tradeable.
- The EUR/USD–GBP/USD–EUR/GBP triangle (a textbook no-arbitrage relationship) correctly shows
  rank=1 in ~88% of windows, with rare (~5%) full-rank outcomes — a known small-sample Johansen
  trace-test size distortion on short, highly-correlated 3-asset systems, not a code defect.
- Engle-Granger and Johansen disagreed on roughly 15% of overlapping bivariate FX cases — this
  matches the literature cited in FRD Section 6–7 (the two methods are known to disagree) and is
  reported, not resolved, per spec.

## Tests

```bash
pytest -q
```
Phase 1 tests cover quality checks, derived-stats math, the rate limiter, both provider clients
(mocked HTTP, no network/API key needed), payload parsing, and the full ingest_runner
orchestration against an in-memory repository (`tests/fakes.py`) — including the failure
paths (feed down, malformed bar, data gap).

Phase 2 tests cover ADF/half-life/Engle-Granger/Johansen against synthetic series with known
ground truth (a constructed cointegrated pair, independent random walks, a 3-asset common-trend
basket), plus engine-orchestration invariants (ADF exclusion actually prevents a symbol from
entering EG/Johansen that window; a basket only runs when every member passed) against an
in-memory `FakeCointegrationRepository` — no live DB needed for any of this.

## Verifying Phase 1 (per the Phase 1 review checklist)

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

## Verifying Phase 2 (per the Phase 2 review checklist)

- **ADF exclusion actually excludes:** `pytest tests/test_cointegration_engine.py -v` and read
  `test_basket_only_runs_in_windows_where_every_member_passed_adf` / the bivariate-pair
  equivalent — both check the real per-window invariant from persisted `adf_results` rows, not
  a mocked assertion.
- **Engle-Granger uses EG/Phillips-Ouliaris critical values, not plain Dickey-Fuller:** see the
  `statsmodels.tsa.stattools.coint(...)` call in `pipeline/cointegration/engle_granger.py` — it
  is the function that returns MacKinnon's EG p-values, not `adfuller` called directly on a
  residual.
- **Johansen documents lag length + deterministic term per basket, not a blind default:** every
  row in `johansen_results` stores `lag_order` (AIC-selected) and `deterministic_term`
  alongside the rank/vectors.
- **EG vs Johansen disagreement is reported, not silently resolved:** query
  `SELECT * FROM method_disagreements WHERE disagree = true LIMIT 5;` — ~15% of bivariate FX
  cases in testing.
- **Rolling re-estimation is real, not a single fit presented repeatedly:**
  `SELECT count(DISTINCT window_end) FROM engle_granger_results;` should be in the dozens (107
  for the FX range tested), not 1.
- **No gating/thresholds leaked in from Phase 3:** `db/schema_phase2.sql` has no
  healthy/warning/halted columns anywhere, and no code path classifies a result into a
  health status or suspends anything. (A few comments in `pipeline/cointegration/*.py`
  mention "gating" and "halted" only to explain what was deliberately left for Phase 3 —
  that's the one place those words should turn up.)

## Repository layout

```
config/universe.yaml       FX pairs, equity universe, cadences, provider codes, tolerances,
                             Phase 2 window/step/basket config
db/schema.sql                Phase 1: bars, derived stats, runs, quality events
db/schema_phase2.sql          Phase 2: adf_results, engle_granger_results, johansen_results,
                                method_disagreements
docker-compose.yml             Local TimescaleDB instance (mounts both schema files)
pipeline/
  config.py                    Loads .env + universe.yaml into typed Settings
  exceptions.py                 FeedDownError / MalformedPayloadError / RateLimitExceededError / ConfigError
  repository.py                  Repository ABC + PostgresRepository (psycopg2) -- Phase 1 only
  sources/
    base.py                      Bar + DataSource interface
    twelvedata_client.py           FX HTTP client (rate-limited, retrying)
    alpaca_client.py                Equities HTTP client (rate-limited, retrying)
    fx_source.py / equity_source.py     Parse provider payloads into Bar objects
  quality/checks.py               validate_bar() + detect_gaps()
  derived/stats.py                 log return + rolling mean/std (NOT the cointegration engine)
  ingest_runner.py                  Core orchestration: ingest -> validate -> persist -> log
  jobs.py                            Wires Settings -> ingest_runner for a given (asset_class, interval)
  backfill.py / run_once.py / scheduler.py   Phase 1 CLI entrypoints
  cointegration/
    adf.py                             ADF I(1) pre-test
    half_life.py                        AR(1) half-life = -ln(2)/ln(lambda)
    engle_granger.py                     Pairwise EG, both regressand directions
    johansen.py                           Johansen via VECM: rank, vectors, adjustment speeds
    repository.py                          CointegrationRepository (separate from Phase 1's)
    engine.py                               Rolling-window orchestration
    run.py                                   CLI entrypoint
tests/                              Unit tests, including in-memory Repository/DataSource fakes
```
