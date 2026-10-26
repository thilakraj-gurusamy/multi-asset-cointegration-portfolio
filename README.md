# Multi-Asset Portfolio — Phase 1 + 2 + 3 + 4 + 5 (complete)

"Modelling a Multi-Asset Portfolio" project (see [`FRD.md`](FRD.md) / [`FRD.docx`](FRD.docx)).
Built and verified phase by phase, per `FRD_Phases_MasterPrompts.docx`'s Phase 1→5 breakdown.
All five phases are implemented, live-validated against real data, and deployable via a single
`docker compose up`.

- **Phase 1 — Data Pipeline** (FRD Sections 8.1, 8.4, 9, 10): scheduled (REST, not tick/
  WebSocket) ingestion, storage, and data-quality logging for FX, equities, and (Phase 5) crypto.
- **Phase 2 — Cointegration Engine** (FRD Section 8.2): rolling-window ADF, Engle-Granger, and
  Johansen testing on top of the Phase 1 store.
- **Phase 3 — Relationship-Health Monitoring** (FRD Section 8.5) — **the project's core
  differentiator**: classifies every monitored pair/basket healthy/warning/halted per window,
  tracks hedge-ratio drift, logs every status transition, and flags/suspends on breakdown.
- **Phase 4 — Signal Generation, Risk Management, Backtest** (FRD Sections 8.6-8.8): z-score
  entries/exits gated on Phase 3 health, five risk controls (vol-targeting, LTCM-derived
  leverage caps, relationship-breakdown stop-loss, portfolio drawdown halt, liquidity-aware
  sizing), and a walk-forward backtest benchmarked against buy-and-hold and a naive
  no-health-gating baseline.
- **Phase 5 — Crypto + Paper-Trading Loop + Dashboard** (FRD Sections 8.1, 8.8, 9, 10, 12): a
  crypto universe run through the unchanged Phase 2/3 engine to quantify instability (never
  wired into Phase 4's production signal pipeline), a live daily paper-trading execution loop
  with simulated fills only, a Streamlit dashboard, and a four-service Docker Compose
  deployment.

Explicitly **never** built, for the whole project, under any configuration: a live brokerage
connection or real order routing (Scope Decision, Section 3).

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
   - Crypto (Binance) needs **no key at all** — nothing to add for it
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

## Phase 3: running the relationship-health monitor

Consumes Phase 2's already-computed rolling-window output for the given range -- it does not
re-run Phase 2. Run Phase 2 for the full range first (above), then:

```bash
python -m pipeline.health.run --asset-class fx --start 2022-01-01 --end 2024-06-01
python -m pipeline.health.run --asset-class equity --start 2022-01-01 --end 2024-06-01
```

Each monitored relationship has ONE canonical source for health scoring: **Engle-Granger** for
pairs (a direct continuous p-value; the alphabetically-forward regressand direction is picked
deterministically so there's exactly one series per pair, not two competing ones), **Johansen**
for 3+-asset baskets (via a documented pseudo-p-value proxy interpolated from the trace
statistic against its 90/95/99% critical values -- `pipeline/health/pseudo_pvalue.py` --
because Johansen has no native continuous p-value the way EG does). For every window it
computes hedge-ratio/cointegrating-vector drift against the *previous* window (something
Phase 2 deliberately does not do), classifies p-value/drift/half-life against the FRD's stated
initial-default thresholds (`pipeline/health/thresholds.py` -- explicitly defaults to
recalibrate later, not fixed truths), persists the full computation every window
(`relationship_health`), logs a row only when the status actually CHANGES
(`health_status_transitions`), and on any transition to `halted` flags it for position review
(`position_review_flags`) and fires the alert hook. `HealthRepository.is_suspended(...)` always
reads the latest window, so a relationship un-suspends automatically once it re-qualifies --
no separate state machine needed.

**Real findings from running this against the full 2022–2024 FX/equity history** (not
illustrative -- this is the actual output):
- Across **6,777** relationship-window observations, only **15 (0.2%)** were ever classified
  fully `healthy` on all three axes simultaneously; **593 (8.8%)** were `warning`; **6,169
  (91%)** were `halted`. Most of that is p-value alone (most arbitrary pairs simply aren't
  cointegrated, correctly), but even among pairs/baskets with genuinely significant EG/Johansen
  p-values, the half-life axis alone disqualifies most of them from ever reaching `healthy` --
  concretely validating the FRD's own thesis that statistical significance does not imply a
  clean, tradeable spread.
- **EUR/USD vs GBP/USD** never once reached `healthy` across 107 windows (2022-2024) despite
  being almost always EG-significant (p<0.05) -- its half-life is persistently under 5 days,
  pinning it to `warning` at best and `halted` whenever the p-value itself briefly drifted
  above 0.10 (e.g. the window ending 2022-06-13: p=0.151, drift=1.6%, half-life=3.7 days --
  `overall_status` correctly reads `halted`, driven by the p-value axis alone, confirmed by
  manual recomputation of the stored drift %).
- The **EUR/USD-GBP/USD-EUR/GBP triangle** (and the equities **financials basket**,
  BAC/GS/JPM/WFC) both show genuine, repeated breakdown-and-partial-recovery cycles --
  `healthy`/`warning` for a run of windows, a transition to `halted` (alert fired, position
  flagged), then eventual requalification -- exactly the kind of real relationship decay this
  phase exists to catch, not a static "cointegrated forever" assumption.

## Phase 4: running the backtest

Needs Phase 2 + Phase 3 already computed for the requested range -- this phase only consumes
their output, it never re-runs them.

```bash
python -m pipeline.backtest.run --asset-class fx --start 2022-01-01 --end 2024-06-01
python -m pipeline.backtest.run --asset-class equity --start 2022-01-01 --end 2024-06-01
```

Runs and persists all three variants (`backtest_runs`, `trades`, `signals`,
`portfolio_equity_curve`): the walk-forward health-gated strategy, a naive static-EG baseline
with the health gate forced open (fit once on the earliest window, traded for the whole period,
scoped to pairs only -- EG has no 3+-asset form), and equally-weighted buy-and-hold. All three
share the identical position/sizing/cost engine (`pipeline/backtest/engine.py`'s
`simulate_portfolio`) so the Sharpe comparison is apples-to-apples; only the *inputs* (which fit,
whether the gate is consulted) differ.

Position sizing takes the **minimum** of three independently-computed caps, logged per trade in
`trades.sizing_detail` so you can see which one actually bound: vol-targeting
(`target_daily_vol_per_position / in-sample spread std`), the LTCM-derived leverage cap
(`max_loss_dollars / in-sample worst single-day move` -- deliberately the *worst* observed move,
not the typical one), and a liquidity cap (real ADV for equities, a fixed-notional proxy for FX
per the Phase 1 no-volume-data limitation).

**Real findings from running this against the full 2022-2024 history** (not illustrative --
this is the actual output of `pipeline.backtest.run`):

| Variant | FX Return | FX Sharpe | FX MaxDD | FX Trades | Equity Return | Equity Sharpe | Equity MaxDD | Equity Trades |
|---|---|---|---|---|---|---|---|---|
| Walk-forward, health-gated | 0.00% | 0.00 | 0.00% | **0** | -1.58% | -0.41 | **4.04%** | 6 |
| Naive static EG, no gating | 2.39% | 0.15 | 17.92% | 109 | 33.63% | 0.87 | 16.44% | 262 |
| Buy-and-hold | 7.02% | 0.84 | 2.63% | -- | 20.28% | 0.54 | 16.28% | -- |

- **The health-gated FX strategy took zero trades over 2.4 years.** This is not a bug --
  verified directly from the `signals` table: it suppressed 3,413 `halted` and 511 `warning`
  entry signals that would otherwise have fired, and the single largest `|z|` ever observed
  during a `healthy` window across the entire FX universe was **1.84**, short of the 2.0 entry
  threshold. The combination of Phase 3's thresholds and `z_entry=2.0` turned out to be
  structurally self-defeating for this FX universe: the same conditions that make a
  relationship "healthy" (stable hedge ratio, sane half-life) are inversely related to the
  volatility that produces an extreme z-score in the first place. This is exactly why the FRD
  states these are initial defaults "to be calibrated during backtesting, not fixed truths"
  (Section 8.5) -- this backtest *is* that calibration signal, not a failure to find one.
- **The health-halted stop-loss fired for real, independent of P&L.** 3 of the equities
  strategy's 6 trades closed via `health_halted_stop` rather than a z-score exit -- confirmed
  directly from `trades`: one (GS,WFC, 2024-02-15 entry) closed **while $8,442 in profit**,
  proving the stop triggers on relationship breakdown alone, not on losses.
- **The health-gated strategy traded far less, and drew down far less, than either
  alternative** on equities (4.04% max drawdown vs. 16.44%/16.28%) -- but also returned less.
  The naive baseline outright **beat** both the health-gated strategy and buy-and-hold on raw
  Sharpe in this specific window. This is reported as-is, not spun: a small, honest sample (6
  trades) from un-calibrated default thresholds is not strong evidence either way on its own,
  and the FRD's point stands independently of which backtest window happens to favor which
  side -- the real result here is that the infrastructure correctly measures and reports this
  nuance instead of asserting a predetermined conclusion.
- **The portfolio drawdown halt fired for real on the FX naive baseline**, confirmed from
  `portfolio_equity_curve`: breached 15% on 2023-11-16 (`halted` flips to `true`), and stayed
  `halted` even as equity recovered over the following days -- new entries stayed blocked for
  the rest of the run, exactly the "manual review to resume" design (Section 8.7d), not an
  automatic reset.

## Phase 5: crypto, the paper-trading loop, and the dashboard

### Crypto module

Binance's public market-data REST API (`pipeline/sources/binance_client.py`) -- free, no API
key, no signup, unlike every other Phase 1 source. Universe is a top-20-by-24h-quote-volume
snapshot (taken 2026-10-26, see `config/universe.yaml`'s `crypto:` section), cross-referenced
against well-established major cryptocurrencies to exclude stablecoin-vs-stablecoin pairs and
wrapped/tokenized-equity products that occasionally rank highly by volume on Binance but aren't
cryptocurrencies in the relevant sense. Symbols use Binance's own ticker format (`BTCUSDT`, no
slash) directly as the canonical symbol -- the same "canonical symbol == provider ticker"
convention FX and equities already use, so `ingest_runner.py` needed zero crypto-specific code.

Runs through Phases 1-3 **completely unchanged** -- `--asset-class crypto` is just another
argument to the same CLIs:
```bash
python -m pipeline.backfill --asset-class crypto --interval 1day --start 2022-01-01 --end 2026-10-26
python -m pipeline.cointegration.run --asset-class crypto --start 2022-01-01 --end 2026-10-26
python -m pipeline.health.run --asset-class crypto --start 2022-01-01 --end 2026-10-26
```
One deliberate, documented scope decision in `config/universe.yaml`: `cointegration.crypto.symbols`
excludes `ENAUSDT` specifically (not from Phase 1 ingestion, which still collects it) -- it was
listed on Binance in April 2024, and Phase 2's windowing needs every symbol in the universe
aligned on one shared date grid (needed for baskets), so its ~61 days of history inside the
analysis range collapsed the WHOLE 20-symbol intersection from 883 days to 61, confirmed live
before being excluded, not assumed.

Crypto is structurally excluded from Phase 4 at the **database level**, not just by convention:
`signals`/`trades`/`backtest_runs`' `asset_class` CHECK constraints only admit `'fx'`/`'equity'`
(see `db/schema_phase5.sql`'s comment) -- a future bug that tried to wire crypto into the
production signal pipeline would fail loudly, not silently succeed.

**Quantified instability (FRD Section 8.1's actual requirement), from the live run:**

| | FX triangle | Equities financials | **Crypto (BTC/ETH/SOL)** |
|---|---|---|---|
| Max hedge-ratio drift (consecutive windows) | 987% | 263% | **30,840%** |
| Avg hedge-ratio drift | 20% | 97% | **1,672%** |

Verified not a numerical artifact: the two consecutive windows behind crypto's 30,840% max
(2023-10-21 → 2023-10-26, just 5 days apart) show the cointegrating vector's own components
swinging from `[1.0, -12.9, 11.1]` to `[1.0, 132.5, -5249.0]` -- a genuine, dramatic re-estimate
of the relationship itself, not a near-zero-denominator blowup. The same basket's rank also
visibly flickers between 0 and 1 across adjacent/overlapping windows in the stored data. This is
exactly the "mixed, regime-dependent, unstable" crypto cointegration evidence cited in FRD
Sections 6-7, now demonstrated concretely from this project's own live data rather than only
cited from the literature.

### The paper-trading execution loop

`pipeline/paper_trading/` runs ingest → cointegration → health → signal end to end
(`pipeline/paper_trading/cycle.py`), with **simulated fills only** -- there is no brokerage
client anywhere in this codebase, under any configuration. Cadence is a deliberate, documented
decision: the cycle's own work (Phase 2/3/4) only ever changes once a day (they operate on
`"1day"` bars), so `pipeline/paper_trading/scheduler.py` runs the full cycle **hourly**, not
every 15 minutes -- Phase 1's own near-real-time scheduler (`pipeline/scheduler.py`) is a
**separate, still-independently-running process** handling the actual 15-min/60-min ingestion;
this cycle just re-runs the "1day" incremental fetch defensively (in case that process is down)
before rolling Phase 2→3→4 forward.

The Phase 4 execution logic is **reused, not reimplemented**: `pipeline/backtest/engine.py`'s
`evaluate_relationship_day()` was extracted specifically so the backtest's in-memory simulation
and this live loop's DB-persisted-across-cycles position state (`paper_positions`/`paper_trades`
in `db/schema_phase5.sql`) call the *exact same* decide/size/cost function -- they cannot
silently diverge in what counts as an entry, an exit, or a correctly-sized position.
Idempotent by construction: `pipeline/paper_trading/signals.py` checks whether an asset class's
`paper_equity_curve` already has a row for the latest available bar date before doing anything,
so an hourly scheduler tick on a day with no new data is a clean no-op, not a double-counted
P&L or a double-closed position.

```bash
python -m pipeline.paper_trading.cycle     # one cycle, prints a summary
python -m pipeline.paper_trading.scheduler  # runs forever, hourly
```

**Real findings from running this live** (not illustrative):
- Caught and fixed a real bug live: a single Twelve Data FX fetch once returned two bars
  sharing a timestamp, which crashed `derived_bar_stats`' batch upsert with Postgres' "ON
  CONFLICT DO UPDATE command cannot affect row a second time" (two NEW rows in one statement
  can't both resolve against the same conflict target). Root cause not pinned down with
  certainty -- it did not reproduce on a direct follow-up check of the same pairs, consistent
  with a transient provider-side artifact around the currently-forming candle -- but
  `ingest_runner.py` now defensively dedupes by timestamp within one fetch regardless, logging
  it as a quality event rather than crashing or silently dropping data.
- Timed live: a full 3-asset-class cycle took **~124 seconds** against an hourly (3600s)
  cadence -- comfortably "well within" the chosen refresh cadence (FRD's own phrasing), after
  tuning the cointegration-step lookback down from 400 to 150 days once the 400-day version was
  measured at ~293s/cycle (still well within budget, but recomputing hundreds of already-settled
  historical windows every cycle when at most one NEW window can appear between cycles was
  pure waste).
- On the specific days this was run, zero new paper trades fired for FX/equities -- consistent
  with, not contradicting, the Phase 4 finding that healthy-status days and |z|>2 days rarely
  coincide under these un-calibrated default thresholds.

### Dashboard

`streamlit run dashboard/app.py` (or the `dashboard` Docker Compose service). Five tabs, all
reading live from Postgres (`dashboard/queries.py`, no mutations):
- **Live Paper P&L** -- equity curve, drawdown, halted flag, open positions, recent closed
  trades, per asset class (FX/equities).
- **Relationship Health** -- every monitored pair/basket's latest healthy/warning/halted status,
  color-coded.
- **Crypto Instability** -- shown in its own tab with an explicit on-screen banner that it is
  NOT a production signal and never reaches the P&L tab, plus the hedge-ratio-drift comparison
  bar chart (the 30,840%-vs-987%-vs-263% finding above, visualized).
- **Backtest Results** -- the Phase 4 three-way comparison table, for context next to the live
  loop.
- **Observability** -- the pipeline cycle log, recent halted-relationship transitions, and
  recent data-quality events (feed downtime, malformed payloads, gaps) -- visible on screen, not
  buried in log files only.

Verified by actually running it in a browser (both via `streamlit run` directly and via the
Dockerized `dashboard` service reaching Postgres over the Compose network) and checking every
tab renders real data with no console errors -- not just that the code imports cleanly.
`dashboard/queries.py` has no dedicated unit tests: it is a thin SQL/pandas wrapper layer, and
live-rendering every tab against real data in an actual browser is stronger evidence of
correctness than mocking `psycopg2`/`pandas.read_sql_query` would have been.

### Deployment

```bash
docker compose up -d                 # timescaledb + app (paper-trading loop) + dashboard
docker compose logs -f app           # watch the hourly cycle
# dashboard at http://localhost:8501
```
One image (`Dockerfile`) serves both the `app` and `dashboard` Compose services -- only the
`command:` differs. Verified live: built the image, ran `app` and `dashboard` as real
containers against the real (bind-mounted, data-preserving) `timescaledb` container, confirmed
the dashboard renders in a browser over the Compose-internal network, and let `app` complete one
full real cycle (`"Paper-trading cycle complete: success"`) before stopping both -- leaving an
hourly, API-quota-consuming process running indefinitely and unannounced is not something to do
without the person actually operating this deciding to.

**Cloud VM, stated transparently (FRD Section 10) rather than assumed free:** a small VPS (e.g.
AWS Lightsail, DigitalOcean, Linode -- roughly $5-12/month for a 1-2 GB instance) running Docker
is enough: `git clone`, copy `.env` with real credentials, `docker compose up -d`, optionally put
the dashboard behind a reverse proxy with basic auth if exposed beyond localhost. Twelve Data and
Alpaca stay free-tier; Binance is free regardless. This step needs a cloud account and real
payment, so it was not provisioned in this session -- it is documented here, ready to run,
for whoever operates this to do when they choose to.

### Sustained paper-trading period

The FRD asks this be *prepared* to run for >= 4 weeks with uptime/failures logged, not actually
run for 4 weeks inside a single build session. It already has everything that needs: `restart:
unless-stopped` on both the `app` and `dashboard` Compose services, every cycle's outcome logged
to `paper_cycle_log` (status, duration, per-step detail) regardless of success/failure, and every
halted-relationship transition or failed ingestion already wired to the alert hook. Start it with
`docker compose up -d` and let it run.

## Verifying Phase 5 (per the Phase 5 review checklist)

- **Crypto results are an instability demonstration, not a production signal:** `grep -r crypto pipeline/backtest/` returns nothing; the `signals`/`trades`/`backtest_runs` tables structurally reject `asset_class='crypto'` at the database CHECK-constraint level.
- **No code path can route a real order:** `grep -ri "broker\|order_route\|submit_order" pipeline/` returns nothing outside this README's own prose.
- **Paper-trading loop uses observed prices, no look-ahead:** see `pipeline/backtest/fitting.py`'s walk-forward discipline (reused unchanged) and `tests/test_fitting.py`'s explicit look-ahead test.
- **Dashboard shows real live P&L, health, and a deliberately-triggered failure:** force a bad API key (same trick as Phase 1's own checklist), run a cycle, and confirm the Observability tab's cycle log shows the failed step and the alert fired.
- **Full cycle time fits the cadence:** `python -m pipeline.paper_trading.cycle` and compare its printed/logged duration against `CYCLE_INTERVAL_SECONDS` in `pipeline/paper_trading/scheduler.py`.
- **Runs from a clean checkout:** `docker compose up -d` after copying `.env.example` → `.env` and filling in keys -- no manual steps beyond that.

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

Phase 3 tests cover threshold boundary classification, the pseudo-p-value interpolation
(including that it reproduces the exact known alpha at each anchor critical value), drift math
(scalar and vector, including the undefined-zero-baseline case), and monitor orchestration
against an in-memory `FakeHealthRepository` -- drift is None on a relationship's first window,
a transition is logged only when status actually changes (not every window), a halted
transition flags for review and fires the alert hook, suspension lifts automatically once a
later window re-qualifies, and one relationship's processing failure doesn't stop the others
(and fires its own `health_check_failed` alert).

Phase 4 tests cover the pure logic (spread/z-score math, the entry/exit state machine
exhaustively, vol-targeting, the leverage cap binding tighter than vol-targeting on a
fat-tailed synthetic series, both liquidity caps, drawdown halt-and-stay-halted, cost
arithmetic, Sharpe/drawdown metrics including a float-precision edge case) and a full
walk-forward-discipline test (a window with no usable fit produces a genuine gap, never a
carried-forward stale fit; in-sample stats provably never see out-of-sample prices) plus an
engine integration suite against an in-memory `FakeBacktestRepository` -- no entry while
warning, costs deducted from net P&L, vol-targeting/leverage/liquidity caps each isolated and
shown to bind when tightest, the health-halted stop closing a position regardless of a
favorable z-score, a portfolio drawdown breach on ONE relationship blocking a new entry on a
DIFFERENT relationship the next day, and open positions closed at the end of the backtest.

Phase 5 tests cover the Binance client and crypto payload parsing (mocked HTTP, including
pagination across a full 1000-row page and a short final page), and the NEW paper-trading glue
specifically (not re-testing `decide_action`/sizing/costs, already covered by Phase 4's suite):
a position opens and persists across separate calls simulating separate days, a second call on
the same day is a correct no-op, a position closes using state reloaded from a fake repository
(not in-memory continuity), drawdown `halted` state reloads and carries forward correctly, and
`pipeline.paper_trading.cycle`'s orchestration (via monkeypatched step functions) isolates one
asset class's ingest failure from the others, aggregates "skipped" as a good outcome rather than
a failure, and structurally never calls the paper-signal step for crypto.

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

## Verifying Phase 3 (per the Phase 3 review checklist)

- **All three metrics are persisted per cycle, per relationship, with timestamps:**
  `SELECT window_end, p_value, hedge_ratio_drift_pct, half_life_days, overall_status FROM relationship_health WHERE relationship_key = 'EUR/USD,GBP/USD' ORDER BY window_end;`
- **Classification matches the threshold table exactly:** inject synthetic windows via
  `tests/test_thresholds.py`'s boundary cases, or see the real `EUR/USD,GBP/USD` trace above
  where a p-value crossing 0.10 alone flips `overall_status` to `halted`.
- **A halted status actually suspends and flags, not just a label:** confirm via
  `HealthRepository.is_suspended(...)` (see `test_relationship_stays_suspended_while_latest_window_is_halted`)
  and `SELECT * FROM position_review_flags;` -- don't just check the status column changed.
- **Every status change is logged with the inputs that produced it:** `health_status_transitions.reason`
  is a JSONB snapshot of all three sub-metrics at that exact window; `relationship_health` has
  the same for every window, not just the ones that changed.
- **The monitor demonstrably catches real historical breakdowns, not a cosmetic feature:** see
  the three bullet points above, drawn directly from the 2022-2024 run, not a cherry-picked
  synthetic example.

## Verifying Phase 4 (per the Phase 4 review checklist)

- **No new entry while warning/halted:** `SELECT action, count(*) FROM signals WHERE action IN ('suppressed_warning','suppressed_halted') GROUP BY action;` -- non-zero, and `SELECT * FROM trades;` joined back confirms no trade's entry date falls on a suppressed signal.
- **Position sizing actually varies with inputs, not fixed notional:** `SELECT relationship_key, position_units, sizing_detail FROM trades;` -- `sizing_detail` shows which of the three caps (vol/leverage/liquidity) bound for each trade, and they differ across trades.
- **Stop-loss triggers independent of P&L:** `SELECT * FROM trades WHERE exit_reason = 'health_halted_stop';` -- see the GS,WFC trade above that closed while $8,442 in profit.
- **Portfolio drawdown halt actually blocks new entries, not just a label:** `SELECT * FROM portfolio_equity_curve WHERE halted ORDER BY "date" LIMIT 1;` to find the breach date, then confirm no `trades.entry_date` for that asset class falls after it during the same run.
- **Walk-forward is genuinely rolling:** `SELECT DISTINCT window_start, window_end FROM signals WHERE relationship_key = '<pick one>' ORDER BY window_end;` -- multiple distinct windows, not one fit reused for every signal row (the naive baseline's own signals ARE expected to show just one window -- that's the point of the comparison).
- **Transaction costs and slippage are in the P&L, not just assumed:** `SELECT gross_pnl, transaction_cost, slippage_cost, net_pnl FROM trades;` and confirm `net_pnl = gross_pnl - transaction_cost - slippage_cost` on real rows.
- **The Sharpe comparison is the real evidence, not asserted:** the table in the Phase 4 section above is read directly from `backtest_runs`, not hand-picked.

## Repository layout

```
Dockerfile / .dockerignore    One image, two Compose service roles (app, dashboard)
docker-compose.yml             timescaledb + app + dashboard (mounts all five schema files)
config/universe.yaml            FX/equity/crypto universes, cadences, provider codes,
                                  tolerances, Phase 2 window/step/basket/symbols config,
                                  Phase 4 backtest params
db/schema.sql                     Phase 1: bars, derived stats, runs, quality events
db/schema_phase2.sql                Phase 2: adf_results, engle_granger_results,
                                      johansen_results, method_disagreements
db/schema_phase3.sql                  Phase 3: relationship_health, health_status_transitions,
                                        position_review_flags (+ additive enrichment of Phase 2's
                                        johansen_results with 90%/99% trace critical values)
db/schema_phase4.sql                    Phase 4: signals, trades, backtest_runs,
                                          portfolio_equity_curve
db/schema_phase5.sql                      Phase 5: widens asset_class to admit 'crypto' on
                                            Phase 1-3 tables ONLY (Phase 4 tables deliberately
                                            left fx/equity-only); paper_positions, paper_trades,
                                            paper_equity_curve, paper_cycle_log
dashboard/
  queries.py                                  Read-only SQL -> pandas, no Streamlit dependency
  app.py                                      Streamlit app: 5 tabs, reads dashboard/queries.py
pipeline/
  config.py                    Loads .env + universe.yaml into typed Settings
  exceptions.py                 FeedDownError / MalformedPayloadError / RateLimitExceededError / ConfigError
  repository.py                  Repository ABC + PostgresRepository (psycopg2) -- Phase 1 only
  sources/
    base.py                      Bar + DataSource interface
    twelvedata_client.py           FX HTTP client (rate-limited, retrying)
    alpaca_client.py                Equities HTTP client (rate-limited, retrying)
    binance_client.py                Crypto HTTP client (public, no API key)
    fx_source.py / equity_source.py / crypto_source.py   Parse provider payloads into Bar objects
  quality/checks.py               validate_bar() + detect_gaps()
  derived/stats.py                 log return + rolling mean/std (NOT the cointegration engine)
  ingest_runner.py                  Core orchestration: ingest -> validate -> persist -> log
                                      (+ Phase 5: defensive same-fetch timestamp dedup)
  jobs.py                            Wires Settings -> ingest_runner for a given (asset_class, interval)
  backfill.py / run_once.py / scheduler.py   Phase 1 CLI entrypoints (fx/equity/crypto)
  cointegration/
    adf.py                             ADF I(1) pre-test
    half_life.py                        AR(1) half-life = -ln(2)/ln(lambda)
    engle_granger.py                     Pairwise EG, both regressand directions
    johansen.py                           Johansen via VECM: rank, vectors, adjustment speeds
    repository.py                          CointegrationRepository (separate from Phase 1's)
    engine.py                               Rolling-window orchestration
    run.py                                   CLI entrypoint (fx/equity/crypto)
  health/
    thresholds.py                             healthy/warning/halted classification (defaults)
    pseudo_pvalue.py                            Johansen trace-stat -> proxy p-value
    drift.py                                     hedge-ratio / cointegrating-vector drift %
    repository.py                                 HealthRepository (reads Phase 2, writes Phase 3)
    monitor.py                                     Orchestration: classify, log, transition, alert
    run.py                                          CLI entrypoint (fx/equity/crypto)
  signals/
    spread.py                                        Spread = weighted dot product of leg prices
    zscore.py                                         Rolling z-score, fit-once-apply-fixed discipline
    rules.py                                           Pure entry/exit state machine (exhaustively tested)
  risk/
    sizing.py                                           Vol-targeted position sizing
    leverage.py                                          LTCM-derived leverage cap (worst-case move, not std)
    liquidity.py                                          Equity ADV cap / FX fixed-notional proxy cap
    drawdown.py                                            Portfolio drawdown tracker; halts, never auto-resumes
  backtest/
    fitting.py                                              Walk-forward fit resolution (pure, no position state)
    engine.py                                                simulate_portfolio() + run_walk_forward_backtest()
                                                               + evaluate_relationship_day() (shared with Phase 5)
    benchmarks.py                                            Naive static-EG baseline + buy-and-hold
    costs.py                                                 Transaction cost + slippage, split out separately
    metrics.py                                               Sharpe / total return / max drawdown
    repository.py                                            BacktestRepository (reads Phases 1-3, writes
                                                               Phase 4 + Phase 5 paper-trading tables)
    run.py                                                   CLI entrypoint; prints the 3-way comparison table
  paper_trading/
    signals.py                                                Live daily signal step -- reuses
                                                                evaluate_relationship_day() against
                                                                DB-persisted position state
    cycle.py                                                   Ingest -> cointegration -> health -> signal,
                                                                per asset class, with failure isolation
    scheduler.py                                                Hourly loop (pipeline.scheduler.py's near-
                                                                real-time ingestion runs separately)
tests/                              Unit tests, including in-memory Repository/DataSource fakes
```
