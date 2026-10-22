# Functional Requirement Document

## 1. Project Title

**Modelling a Multi-Asset Portfolio**

> Investment portfolios typically invest in a range of underlying asset types, each with their own expected return and volatility, and with their interdependence explained by a covariance matrix. This project would first derive an investment can be a problem, particularly when the time series are non-stationary. When dealing with such non-stationary data, cointegration is a useful tool which allows us to investigate the relationship between non-stationary time series in the long term. This project involves studying cointegration and its application and using the technique for time series data such as foreign exchange, cryptocurrencies, or stock market data.

---

## 2. Project Summary

This project builds a working, near-real-time statistical arbitrage research platform that goes beyond standard mean-variance portfolio construction by explicitly modelling the long-run equilibrium relationships between non-stationary asset prices (FX, equities, and — as a secondary module — cryptocurrencies) using cointegration analysis.

The system does three things most academic and retail cointegration projects do not:

1. It treats classical covariance-based portfolio construction and cointegration as complementary, not separate exercises — covariance explains short-run co-movement risk; cointegration explains long-run equilibrium structure that covariance alone cannot capture in non-stationary series.
2. It does not stop at a one-off statistical test. It continuously **re-estimates and monitors the health of each cointegrating relationship over time**, because a relationship that holds in a backtest can and does break down live.
3. It is deployed as a running system with a live dashboard and a paper-trading execution loop, not left as a static notebook.

---

## 3. Scope Decision & Rationale

The original brief, and the first pass at scoping this project, aimed for a fully real-time system treating FX, cryptocurrencies, and equities as three equally weighted asset classes, implying continuous tick-level data ingestion and eventual live execution.

After reviewing the historical evidence on cointegration-based trading (Sections 6–7) and the realistic constraints of building this solo, alongside a full-time job, that scope was deliberately narrowed. This is a judgment call, not a shortfall:

- **Near-real-time, not tick-level streaming.** The strategies this project trades have a spread half-life on the order of 5–60 days (see Section 8.5) — mean reversion that plays out over days, not milliseconds. Tick-level WebSocket ingestion across three asset classes would require building a full streaming-infrastructure project (persistent connections, reconnect/backfill logic, tick-level storage) that buys nothing statistically for a strategy operating on this time horizon. Scheduled refresh every few minutes to hourly captures the same signal at a fraction of the engineering risk.
- **FX and equities as the statistical core; crypto as a secondary, stretch module.** The evidence on crypto cointegration is genuinely mixed and regime-dependent (Section 7) — some studies find it in the large majority of pairs, others find none in smaller, more recent samples, and out-of-sample performance degrades even where in-sample fit looks strong. Building the core system on the asset classes where cointegration is better-documented and more stable, then adding crypto specifically to **demonstrate and quantify that instability**, is a stronger signal of quantitative judgment than presenting all three asset classes as equally reliable.
- **Explicitly paper-trading, not live execution.** Live order routing introduces brokerage integration, order-management, and real-capital risk-control requirements that are a different project. Paper-trading preserves every piece of the quantitative and engineering work (signal generation, risk sizing, live monitoring) without that scope creep.
- **Solo, side-hustle time budget.** Built around full-time work, with a ~10–12 week realistic build horizon (Section 11). The near-real-time, paper-trading scope is sized to actually ship and demo reliably within that time, rather than risk a half-finished tick-streaming/live-execution system.

This is the scope the rest of this document specifies.

---

## 4. Target / Objective

**Problem it solves:** Standard mean-variance portfolio construction assumes return series are stationary and well-behaved. In practice, FX rates, crypto prices, and many equity series are non-stationary — they trend, drift, and don't mean-revert individually — which means naive covariance-based diversification can miss long-run structural relationships between assets (or impose false ones). Cointegration gives a statistically grounded way to find pairs or baskets of assets that, despite individually behaving like random walks, maintain a stable long-run equilibrium — and to trade deviations from that equilibrium while explicitly tracking when the equilibrium itself is breaking down.

**Who it's for:**
- **Primary audience:** hiring managers / interviewers evaluating a candidate for junior quantitative research, systematic trading, or quant risk roles — this project is the portfolio evidence that the candidate can take a textbook technique (cointegration) and reason about its real-world failure modes, not just implement the statsmodels call.
- **Secondary, functional audience:** the author, as a working research tool for exploring cross-asset statistical relationships and practicing the full lifecycle (research → signal → risk → monitored deployment) of a systematic strategy, on paper capital.

---

## 5. Market Gap Analysis

What already exists, and what it misses:

| What's commonly available | What it misses |
|---|---|
| Academic papers testing cointegration on a fixed historical sample and reporting in-sample alpha | No live/rolling re-estimation; no treatment of out-of-sample decay as the central risk |
| Retail "pairs trading" tutorials (blog posts, Medium, QuantConnect notebooks) using Engle-Granger on one or two pairs | Single static test, no transaction costs, no basket/Johansen extension, never deployed, no risk framework beyond a fixed z-score threshold |
| Open-source pairs-trading repos on GitHub | Mostly backtest-only; very few expose a live dashboard, fewer still track the *stability* of the cointegrating relationship itself over time |
| Institutional stat-arb desks | Do exactly the relationship-health monitoring this project proposes, but that engineering and risk layer is proprietary and not visible in any public teaching material |

**The gap:** there is no widely available, open, single-developer-buildable project that treats cointegration as a *decaying, monitorable relationship* rather than a one-shot test — i.e. a system that knows, continuously, whether the statistical relationship it's trading on is still real. That monitoring layer (hedge-ratio drift, half-life drift, rolling significance gating — Section 8.5) is the differentiator this project is built around, framed as a **Cointegration Relationship Health Monitor + Statistical Arbitrage Signal Engine**, not another pair backtest.

---

## 6. What Has Worked Historically

- **Pairs trading has historically been profitable, with the edge concentrated in specific conditions rather than being universal.** Gatev, Goetzmann & Rouwenhorst's foundational distance-method study found economically and statistically significant profits (reported around 1%/month in early samples). Do & Faff's follow-on work on US equities (1963–2009) found that after accounting for trading costs, risk-adjusted returns of roughly 30 basis points/month persist for well-matched pairs formed within refined industry groups — modest, but real. ([Do & Faff, "Are Pairs Trading Profits Robust to Trading Costs?"](https://strathprints.strath.ac.uk/41722/))
- **The strategy tends to perform best during turbulent/crisis periods**, including the 2008 financial crisis window, which is consistent with mean-reversion strategies benefiting from dislocation-driven overshoots that later correct. ([Do & Faff, "Does Simple Pairs Trading Still Work?"](https://rpc.cfainstitute.org/research/financial-analysts-journal/2010/does-simple-pairs-trading-still-work))
- **Multivariate (Johansen-based) cointegration portfolios have shown genuine out-of-sample edge**, not just in-sample fit — a key validation point for building on Johansen rather than stopping at pairwise Engle-Granger. ([Gabriel & Kunst, IHS working paper](https://econpapers.repec.org/RePEc:ihs:ihswps:52))
- **Dynamic/rolling cointegration testing improves on static tests** by correctly capturing which relationships are presently coherent enough to trade, rather than relying on a single historical-sample fit. ([Tsoku & Makatjane, Frontiers in Applied Mathematics and Statistics](https://public-pages-files-2025.frontiersin.org/journals/applied-mathematics-and-statistics/articles/10.3389/fams.2026.1749337/pdf))

---

## 7. What Has Failed Historically

- **LTCM (1998) — the canonical cointegration/convergence-trade failure.** LTCM's relative-value convergence trades bet on historically stable price relationships reverting to equilibrium. When Russia defaulted and triggered a global flight to quality, those spreads *widened* instead of converging, and the correlation structure the fund's risk models relied on broke down exactly when it mattered most. Combined with roughly 25:1 leverage on thin-margin trades, a model-risk failure became a systemic one. ([Case study: LTCM](https://bauer.uh.edu/rsusmel/7386/ltcm-2.htm); [Why LTCM Failed](https://daytrading.com/ltcm))
  - **Direct lesson for this project:** a cointegrating relationship is a hypothesis that can fail under regime shift, not a law. Risk sizing must assume the relationship can break, not just fluctuate within its historical range (Section 8.7).
- **Simple cointegration/distance-method pairs trading profitability has decayed substantially since the early 2000s**, largely attributed to markets becoming more efficient and bid-ask spreads narrowing after decimalization; a German-market study covering 2000–2023 found opportunities for basic distance/cointegration methods decreasing sharply after the 2008/09 crisis, while more sophisticated copula/ensemble methods remained profitable. ([Do & Faff, "Are Pairs Trading Profits Robust to Trading Costs?"](https://strathprints.strath.ac.uk/41722/); [Does simple pairs trading still work?](https://researchers.westernsydney.edu.au/en/publications/does-simple-pairs-trading-still-work/))
  - **Direct lesson:** a naive, static Engle-Granger pair screen is not, on its own, a defensible strategy today. This project's differentiator — rolling relationship-health monitoring — exists specifically because the static version of this strategy is known to have decayed.
- **Cointegration in cryptocurrency markets is inconsistent and regime-dependent — a textbook non-stationarity/spurious-regression trap.** One large-sample 2024 study found cointegration in ~79% of pairs tested, while a separate, smaller 2024 study of BTC/ETH/USDT found no cointegration at all over 2017–2024; a VECM-based study found strong in-sample stat-arb performance that did not hold out-of-sample. ([Troian, "Cointegration Analysis of Cryptocurrency Market"](https://heraldes.khmnu.edu.ua/index.php/heraldes/en/article/view/916); [On cointegration and cryptocurrency dynamics](https://edoc.hu-berlin.de/18452/27341))
  - **Direct lesson:** two trending series (e.g. two assets both rising in a bull market) can appear cointegrated by chance — the classic spurious-regression trap non-stationary data invites. This is precisely why crypto is scoped as a secondary module built to *quantify* this instability (via the rolling health checks in Section 8.5) rather than a pillar assumed to behave like FX or equities.
- **Named risks this project's design must defend against:**
  - *Spurious regression* — two non-stationary, trending series can show a statistically significant but meaningless relationship; mandatory ADF/unit-root pre-testing (Section 8.2) exists to guard against this.
  - *Regime shifts* — a relationship can be real and then stop being real (LTCM, crypto out-of-sample decay above); addressed by rolling re-estimation and health gating, not a one-time fit.
  - *Non-stationarity traps* — fitting models that implicitly assume stationarity (e.g. a static hedge ratio, a fixed covariance matrix) onto series that are not stationary produces unstable, overconfident estimates; addressed throughout by using cointegration/VECM methodology rather than raw OLS on price levels, and by treating all estimated parameters (hedge ratios, half-lives) as drifting quantities to be monitored, not constants.

---

## 8. Functional Requirements

### 8.1 Data Sources & Asset Classes

- **Core (statistical backbone): FX and equities.**
  - FX: daily and intraday (e.g. hourly) rates for a basket of major and cross pairs. Realistic institutional-grade sources: Refinitiv/LSEG Eikon, Bloomberg BPIPE, or a broker-grade aggregator (e.g. OANDA, Polygon.io FX). Where budget-free alternatives are used in the actual build, this should be stated as a substitution, not presented as equivalent in quality.
  - Equities: daily/intraday OHLCV across a universe of liquid, sector-matched US and/or UK large-caps. Institutional-grade: Polygon.io, EOD Historical Data (EODHD), Refinitiv. Budget-free substitution: Alpaca (IEX feed, US equities only — note this is single-venue, not consolidated tape) or Stooq/Yahoo Finance for historical backtesting only.
- **Secondary / stretch module: cryptocurrency.**
  - Hourly/daily OHLCV for a liquid top-20-by-volume universe (e.g. via Binance, Coinbase, or an aggregator like CoinGecko/CoinAPI). Explicitly scoped to run the same rolling cointegration and health-monitoring pipeline as the core, with its output used to *demonstrate* instability (Section 7), not to generate a production-weighted signal in the initial release.
- All feeds must support historical backfill (for backtesting) and scheduled incremental pulls (for near-real-time operation, Section 8.4).

### 8.2 Cointegration Methodology

- **Stationarity pre-testing:** every candidate series must pass an Augmented Dickey-Fuller (ADF) test confirming I(1) behaviour (non-stationary in levels, stationary in first differences) before being considered for cointegration testing. Series failing this check are excluded — this is the primary defence against spurious regression.
- **Pairwise screening — Engle-Granger.** Used as a fast, simple first-pass screen within an asset class (e.g. scanning all FX pairs, or sector-matched equity pairs) to shortlist candidates. Acknowledge its limitations explicitly in the implementation: results are not invariant to which series is the regressand, and critical values must come from Engle-Granger/Phillips-Ouliaris tables, not standard Dickey-Fuller tables.
- **Basket-level testing — Johansen procedure.** Used for any candidate set of 3+ assets (e.g. a cross-currency basket, or an equity sector basket). Implemented via a VECM, producing the cointegrating rank, the cointegrating vector(s) (basket weights), and adjustment speeds (how fast each asset error-corrects back toward equilibrium). Lag length selected via AIC/BIC on the underlying VAR; deterministic terms (constant/trend) chosen and documented explicitly, since this choice affects critical values.
- **Explicit acknowledgment of method disagreement:** Engle-Granger and Johansen can and do disagree on the same data (a documented finding: one study found Engle-Granger flagged far more "profitable" relationships than Johansen on the same universe). The system should report both methods' verdicts on overlapping bivariate cases and flag disagreement rather than silently picking one.
- **Rolling re-estimation (feeds directly into 8.5):** all cointegration tests are re-run on a rolling window (e.g. trailing 60–120 trading days), not fit once on the full history.

### 8.3 Covariance / Portfolio Construction Layer

- Standard rolling covariance/correlation matrix estimation across the full asset universe, used for classical mean-variance portfolio construction (expected return, volatility, Sharpe-optimal/minimum-variance weighting) as the baseline diversification layer described in the original project brief.
- This layer is explicitly positioned as complementary to, not a replacement for, the cointegration layer: covariance captures short-run co-movement and diversification benefit; cointegration captures long-run equilibrium structure within non-stationary series that a covariance matrix on price levels cannot validly represent. The FRD should document this distinction clearly as the conceptual bridge between the two halves of the original brief.
- Where a cointegrated basket exists, its cointegrating vector (Section 8.2) is used to construct the stat-arb spread position; the mean-variance layer is applied across the resulting basket-level return stream (the spread) and other independent strategies/assets, not across raw non-stationary price levels.

### 8.4 Near-Real-Time Data Pipeline

- Scheduled ingestion (not persistent tick streaming, per Section 3): pulls run on a fixed cadence — every 5–15 minutes for FX/crypto, hourly or end-of-day for equities, matched to each asset class's realistic update frequency and the strategy's multi-day holding horizon.
- Ingested data lands in a time-series-appropriate store (Section 10) with raw data retained alongside derived fields (returns, rolling statistics) for auditability.
- Pipeline failures (feed downtime, malformed data, gaps) must be logged and surfaced, not silently skipped — a gap in the data must not be allowed to silently distort a rolling cointegration test.
- Orchestration runs the full cycle: ingest → validate → re-run rolling cointegration/health checks (8.5) → update signals (8.6) → refresh dashboard — on the same schedule, end to end.

### 8.5 Relationship-Health / Decay Monitoring (core differentiator)

For every actively monitored pair/basket, track on a rolling basis:
- **Rolling cointegration p-value** (Engle-Granger and/or Johansen trace statistic), computed on the trailing window at each pipeline cycle.
- **Hedge-ratio drift** — the percentage change in the estimated cointegrating vector/hedge ratio between successive rolling windows.
- **Spread half-life** — estimated via AR(1) fit to the spread (half-life = −ln(2)/ln(λ)), tracked over time for drift.
- **Health gating thresholds** (initial defaults, to be calibrated during backtesting, not treated as fixed truths):
  - p-value: healthy < 0.05, warning 0.05–0.10, trading halted > 0.10.
  - Hedge-ratio drift: healthy < 10%, warning 10–25%, halted > 25%.
  - Half-life: healthy 5–60 days, warning 60–120 days (or < 5 days), halted outside that range.
- A relationship that breaches a "halted" threshold must have any open position flagged for risk review (Section 8.7) and new signal generation suspended for that pair/basket until it re-qualifies.
- This is the mechanism that operationalizes the LTCM and crypto-instability lessons from Section 7: the system is designed to *notice* relationship breakdown rather than assume the historically-fit relationship persists.

### 8.6 Signal Generation

- Spread construction from the Johansen cointegrating vector (or the Engle-Granger hedge ratio for simple pairs), converted to a z-score against its rolling mean/standard deviation.
- Entry/exit rules driven by z-score thresholds (e.g. enter at |z| > 2, exit at |z| < 0.5), gated by the health-monitoring status from Section 8.5 — no new entry is permitted on a relationship in "warning" or "halted" status.
- Signals are versioned and logged (which window, which parameters, which health status produced each signal) for auditability and later analysis.

### 8.7 Risk Management

- **Position sizing** scaled inversely to recent spread volatility (vol-targeting), not a fixed notional per trade.
- **Stop-loss on relationship breakdown**, not just price stop-loss: a position must be reduced or closed if its underlying relationship's health status (8.5) deteriorates to "halted," independent of the position's current P&L.
- **Leverage caps** set with reference to the worst plausible historical divergence of the spread (a direct LTCM-derived control), not simply historical volatility.
- **Portfolio-level drawdown limits** that halt new signal generation system-wide if breached, with manual review required to resume.
- **Liquidity awareness**: position sizing and universe selection account for each asset's realistic tradable size, acknowledging (per the LTCM lesson) that liquidity itself is a risk factor, especially under stress.

### 8.8 Backtesting + Paper-Trading Framework

- **Walk-forward backtesting**: all cointegration re-estimation, health gating, and signal generation logic must be tested walk-forward (rolling in-sample fit → out-of-sample test → roll forward), never fit once on the full sample and evaluated in-sample.
- Transaction costs and realistic slippage assumptions included explicitly in all backtest P&L, since the literature (Section 7) shows naive pairs-trading profitability is materially eroded or eliminated by costs.
- **Paper-trading execution loop**: once validated in backtest, the system runs its full pipeline (Section 8.4) against live/near-real-time data and simulates fills at observed prices, tracking live paper P&L on the dashboard — without connecting to any live brokerage or routing real orders.

---

## 9. Non-Functional Requirements

- **Performance/latency:** the system is a near-real-time signal/monitoring platform, not an HFT system. End-to-end pipeline cycle time (ingest → health check → signal → dashboard refresh) should complete well within the chosen refresh cadence (e.g. under 1 minute for a 5-minute cadence), with headroom for the universe to grow.
- **Scalability:** the pipeline should scale to the full intended universe (FX majors/crosses, a few dozen equities, a secondary crypto universe) without architectural change — i.e. adding an asset class or widening the universe should be a configuration change, not a rewrite.
- **Data integrity & auditability:** every signal, health-status change, and simulated trade must be logged with the inputs and parameters that produced it, enabling full after-the-fact reconstruction of "why did the system do this."
- **Observability:** pipeline failures, data gaps, and health-status breaches must be visible on the dashboard and/or alerted (e.g. a simple email/Slack webhook on a halted relationship or a failed ingestion cycle) — not silent.
- **Reproducibility:** the entire system (data pipeline, cointegration engine, backtests) must be runnable from a clean checkout with documented setup, since this is also a hiring artifact a reviewer may want to run themselves.

---

## 10. Tech Stack Recommendations

| Layer | Recommendation | Notes |
|---|---|---|
| Core language | Python 3.11+ | Ecosystem fit for statsmodels/pandas; R is a viable alternative for the econometrics layer specifically |
| Cointegration/statistics | `statsmodels` (`statsmodels.tsa.vector_ar.vecm` for Johansen/VECM, `statsmodels.tsa.stattools.coint` for Engle-Granger, `adfuller` for unit-root pre-tests) | Standard, well-documented, defensible choice |
| Portfolio/covariance | `numpy`/`pandas`, optionally `PyPortfolioOpt` for mean-variance optimization | Keeps the covariance layer (Section 8.3) separable from the cointegration layer |
| Data ingestion | Scheduled REST pulls (not WebSocket) per asset class; realistic institutional-grade options: Polygon.io, EODHD, Refinitiv/LSEG, OANDA (FX); budget-free substitutions (Alpaca IEX, Stooq) explicitly noted as lower-fidelity if used | Matches the near-real-time scope decision in Section 3 |
| Storage | PostgreSQL with TimescaleDB extension | Time-series-appropriate, but still relational for joins against metadata/signals/trade logs |
| Orchestration | Apache Airflow (or a simpler cron + Python scheduler for the MVP) | Airflow is the "real desk" answer; cron is a legitimate, honestly-scoped MVP substitute worth stating as such |
| Dashboard | Streamlit or Plotly Dash | Fast to build, sufficient for a near-real-time monitoring dashboard; not a justification to skip proper backend logging |
| Deployment | Docker Compose locally; a single cloud VM (e.g. AWS EC2/Lightsail or a comparable low-cost VPS) for the always-on near-real-time deployment | No budget constraint was requested for realism, but the actual running cost should be stated transparently (a small VM plus any paid data feed, likely $20–100+/month depending on feed choice) rather than assumed free |
| Version control / CI | Git + GitHub, basic CI (lint + unit tests on the cointegration/health-scoring logic) | Expected baseline for a hiring-facing repo |

---

## 11. Milestones / Phased Roadmap

Sized for a single developer working this as a side project around full-time work; ~10–12 weeks at a sustainable pace.

| Phase | Duration | Deliverable |
|---|---|---|
| 1. Data pipeline | ~2 weeks | Scheduled ingestion for FX + equities core, backfill + incremental pull, storage schema, basic data-quality checks |
| 2. Cointegration engine | ~2–3 weeks | Engle-Granger screening, Johansen/VECM basket testing, rolling-window re-estimation, backtested on historical data |
| 3. Relationship-health monitoring | ~2 weeks | Hedge-ratio drift, half-life tracking, p-value gating, status logging — the core differentiator |
| 4. Signal generation, risk management, backtest | ~2–3 weeks | z-score signal logic gated by health status, position sizing/stop-loss/leverage-cap rules, walk-forward backtest with costs |
| 5. Crypto stretch module + paper-trading dashboard deployment | ~2 weeks | Crypto universe run through the same pipeline to quantify instability; live dashboard; paper-trading loop deployed and running near-real-time |

---

## 12. Success Metrics / Validation Criteria

- **Statistical validity:** cointegration relationships selected for trading must survive out-of-sample walk-forward testing, not just in-sample fit; the health-monitoring layer (8.5) must demonstrably flag at least some historical relationship breakdowns in backtest (e.g. around known regime-shift periods) to prove it isn't just a cosmetic feature.
- **Strategy performance:** risk-adjusted return (Sharpe) after realistic transaction costs, benchmarked against a simple buy-and-hold on the same universe and against a naive static-Engle-Granger baseline — the comparison against the naive baseline is the direct evidence that the health-monitoring layer adds value.
- **Engineering reliability:** pipeline uptime and successful cycle completion rate over a sustained paper-trading run (e.g. ≥ 4 weeks live), with all failures logged and explainable.
- **Portfolio/hiring validation:** the finished system and this document can be presented end-to-end to a reviewer — repo runs from a clean checkout, the live dashboard is demo-able, and the Scope Decision & Rationale (Section 3) and historical evidence (Sections 6–7) show the reasoning behind every design choice, not just the final code.
