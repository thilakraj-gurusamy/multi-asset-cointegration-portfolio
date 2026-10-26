"""Wires Settings -> concrete clients/sources/repository. Kept separate from ingest_runner so
tests can construct an FxDataSource/EquityDataSource directly against fakes without touching
this module.
"""
from __future__ import annotations

from pipeline.config import Settings
from pipeline.repository import PostgresRepository
from pipeline.sources.alpaca_client import AlpacaClient
from pipeline.sources.binance_client import BinanceClient
from pipeline.sources.crypto_source import CryptoDataSource
from pipeline.sources.equity_source import EquityDataSource
from pipeline.sources.fx_source import FxDataSource
from pipeline.sources.twelvedata_client import TwelveDataClient


def build_fx_source(settings: Settings) -> FxDataSource:
    client = TwelveDataClient(
        api_key=settings.twelvedata_api_key,
        daily_request_budget=settings.fx.daily_request_budget,
    )
    return FxDataSource(client)


def build_equity_source(settings: Settings) -> EquityDataSource:
    client = AlpacaClient(
        api_key_id=settings.alpaca_api_key_id,
        api_secret_key=settings.alpaca_api_secret_key,
        base_url=settings.alpaca_data_base_url,
        feed=settings.equities.feed,
    )
    return EquityDataSource(client)


def build_crypto_source(settings: Settings) -> CryptoDataSource:
    client = BinanceClient()  # no API key -- public market data
    return CryptoDataSource(client)


def build_source_for_asset_class(settings: Settings, asset_class: str):
    if asset_class == "fx":
        return build_fx_source(settings)
    if asset_class == "equity":
        return build_equity_source(settings)
    if asset_class == "crypto":
        return build_crypto_source(settings)
    raise ValueError(f"Unknown asset_class {asset_class!r}")


def build_repository(settings: Settings) -> PostgresRepository:
    return PostgresRepository(settings.database_url)
