from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

from pipeline.exceptions import ConfigError

REPO_ROOT = Path(__file__).resolve().parent.parent


EXPECTED_INTERVAL_MINUTES = {"1hour": 60, "1day": 1440}


@dataclass
class IntervalConfig:
    cadence_minutes: int
    provider_code: str  # provider-specific interval/timeframe string
    gap_tolerance_minutes: float


@dataclass
class FxConfig:
    pairs: list[str]
    intervals: dict[str, IntervalConfig]
    daily_request_budget: int


@dataclass
class EquityConfig:
    feed: str
    universe: list[dict]
    intervals: dict[str, IntervalConfig]


@dataclass
class CryptoConfig:
    pairs: list[str]  # Binance's own ticker format, e.g. "BTCUSDT" -- used directly as the
                       # canonical symbol, same convention FX/equities already follow
    intervals: dict[str, IntervalConfig]


@dataclass
class CointegrationAssetClassConfig:
    window_bars: int
    step_bars: int
    baskets: list[list[str]]
    symbols: list[str] | None = None  # explicit override of which symbols to cointegration-test;
                                        # None means "use the full ingestion universe" (FX/equities).
                                        # Crypto sets this to exclude recently-listed symbols whose
                                        # short history would collapse the whole universe's shared-
                                        # date intersection (Phase 2's windowing needs every symbol
                                        # aligned) well below window_bars -- see universe.yaml.


@dataclass
class CointegrationConfig:
    fx: CointegrationAssetClassConfig
    equities: CointegrationAssetClassConfig
    crypto: CointegrationAssetClassConfig


@dataclass
class LiquidityConfig:
    equity_adv_fraction: float
    fx_max_notional_per_position: float


@dataclass
class BacktestConfig:
    starting_equity: float
    z_lookback_bars: int
    z_entry: float
    z_exit: float
    transaction_cost_bps: float
    slippage_bps: float
    target_daily_vol_per_position: float
    max_loss_per_position_pct: float
    portfolio_max_drawdown_pct: float
    liquidity: LiquidityConfig


@dataclass
class Settings:
    database_url: str
    twelvedata_api_key: str
    alpaca_api_key_id: str
    alpaca_api_secret_key: str
    alpaca_data_base_url: str
    alert_webhook_url: str | None
    log_level: str
    fx: FxConfig
    equities: EquityConfig
    crypto: CryptoConfig
    cointegration: CointegrationConfig
    backtest: BacktestConfig


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(
            f"Required environment variable '{name}' is not set. "
            f"Copy .env.example to .env and fill it in."
        )
    return value


def load_settings(
    env_path: str | Path = REPO_ROOT / ".env",
    universe_path: str | Path = REPO_ROOT / "config" / "universe.yaml",
    require_api_keys: bool = True,
) -> Settings:
    load_dotenv(dotenv_path=env_path, override=False)

    with open(universe_path, "r", encoding="utf-8") as f:
        universe = yaml.safe_load(f)

    fx_raw = universe["fx"]
    fx_intervals = {
        name: IntervalConfig(
            cadence_minutes=cfg["cadence_minutes"],
            provider_code=cfg["provider_interval"],
            gap_tolerance_minutes=cfg["gap_tolerance_minutes"],
        )
        for name, cfg in fx_raw["intervals"].items()
    }
    fx = FxConfig(
        pairs=[p["symbol"] for p in fx_raw["pairs"]],
        intervals=fx_intervals,
        daily_request_budget=fx_raw["daily_request_budget"],
    )

    eq_raw = universe["equities"]
    eq_intervals = {
        name: IntervalConfig(
            cadence_minutes=cfg["cadence_minutes"],
            provider_code=cfg["provider_timeframe"],
            gap_tolerance_minutes=cfg["gap_tolerance_minutes"],
        )
        for name, cfg in eq_raw["intervals"].items()
    }
    equities = EquityConfig(
        feed=eq_raw["feed"],
        universe=eq_raw["universe"],
        intervals=eq_intervals,
    )

    crypto_raw = universe["crypto"]
    crypto_intervals = {
        name: IntervalConfig(
            cadence_minutes=cfg["cadence_minutes"],
            provider_code=cfg["provider_interval"],
            gap_tolerance_minutes=cfg["gap_tolerance_minutes"],
        )
        for name, cfg in crypto_raw["intervals"].items()
    }
    crypto = CryptoConfig(
        pairs=[p["symbol"] for p in crypto_raw["pairs"]],
        intervals=crypto_intervals,
    )

    coint_raw = universe["cointegration"]
    cointegration = CointegrationConfig(
        fx=CointegrationAssetClassConfig(
            window_bars=coint_raw["fx"]["window_bars"],
            step_bars=coint_raw["fx"]["step_bars"],
            baskets=coint_raw["fx"]["baskets"],
        ),
        equities=CointegrationAssetClassConfig(
            window_bars=coint_raw["equities"]["window_bars"],
            step_bars=coint_raw["equities"]["step_bars"],
            baskets=coint_raw["equities"]["baskets"],
        ),
        crypto=CointegrationAssetClassConfig(
            window_bars=coint_raw["crypto"]["window_bars"],
            step_bars=coint_raw["crypto"]["step_bars"],
            baskets=coint_raw["crypto"]["baskets"],
            symbols=coint_raw["crypto"].get("symbols"),
        ),
    )

    bt_raw = universe["backtest"]
    backtest = BacktestConfig(
        starting_equity=bt_raw["starting_equity"],
        z_lookback_bars=bt_raw["z_lookback_bars"],
        z_entry=bt_raw["z_entry"],
        z_exit=bt_raw["z_exit"],
        transaction_cost_bps=bt_raw["transaction_cost_bps"],
        slippage_bps=bt_raw["slippage_bps"],
        target_daily_vol_per_position=bt_raw["target_daily_vol_per_position"],
        max_loss_per_position_pct=bt_raw["max_loss_per_position_pct"],
        portfolio_max_drawdown_pct=bt_raw["portfolio_max_drawdown_pct"],
        liquidity=LiquidityConfig(
            equity_adv_fraction=bt_raw["liquidity"]["equity_adv_fraction"],
            fx_max_notional_per_position=bt_raw["liquidity"]["fx_max_notional_per_position"],
        ),
    )

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if require_api_keys and not database_url:
        raise ConfigError("DATABASE_URL is not set.")

    if require_api_keys:
        twelvedata_api_key = _require_env("TWELVEDATA_API_KEY")
        alpaca_api_key_id = _require_env("ALPACA_API_KEY_ID")
        alpaca_api_secret_key = _require_env("ALPACA_API_SECRET_KEY")
    else:
        twelvedata_api_key = os.environ.get("TWELVEDATA_API_KEY", "")
        alpaca_api_key_id = os.environ.get("ALPACA_API_KEY_ID", "")
        alpaca_api_secret_key = os.environ.get("ALPACA_API_SECRET_KEY", "")

    return Settings(
        database_url=database_url,
        twelvedata_api_key=twelvedata_api_key,
        alpaca_api_key_id=alpaca_api_key_id,
        alpaca_api_secret_key=alpaca_api_secret_key,
        alpaca_data_base_url=os.environ.get("ALPACA_DATA_BASE_URL", "https://data.alpaca.markets"),
        alert_webhook_url=os.environ.get("ALERT_WEBHOOK_URL", "").strip() or None,
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
        fx=fx,
        equities=equities,
        crypto=crypto,
        cointegration=cointegration,
        backtest=backtest,
    )
