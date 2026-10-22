from datetime import datetime, timedelta, timezone

import numpy as np

from pipeline.cointegration.engine import run_rolling_cointegration
from tests.fakes import FakeCointegrationRepository

ASSET_CLASS = "fx"
N_DAYS = 200
WINDOW_BARS = 90
STEP_BARS = 10


def _build_closes():
    rng = np.random.default_rng(21)
    common = np.cumsum(rng.normal(0, 1, N_DAYS))
    series_a = common + rng.normal(0, 0.3, N_DAYS)       # I(1), cointegrated with B
    series_b = 2 * common + rng.normal(0, 0.3, N_DAYS)    # I(1), cointegrated with A
    series_c = rng.normal(0, 1, N_DAYS)                    # stationary in LEVELS -> fails I(1)

    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    dates = [base + timedelta(days=i) for i in range(N_DAYS)]

    return {
        "A": dict(zip(dates, series_a)),
        "B": dict(zip(dates, series_b)),
        "C": dict(zip(dates, series_c)),
    }, dates


def _build_repo():
    closes, dates = _build_closes()
    asset_ids = {("A", ASSET_CLASS): 1, ("B", ASSET_CLASS): 2, ("C", ASSET_CLASS): 3}
    repo = FakeCointegrationRepository(asset_ids, closes)
    return repo, dates


def test_window_count_matches_expected_slicing():
    repo, dates = _build_repo()
    summary = run_rolling_cointegration(
        repo=repo, asset_class=ASSET_CLASS, symbols=["A", "B", "C"], baskets=[["A", "B", "C"]],
        window_bars=WINDOW_BARS, step_bars=STEP_BARS, start=dates[0], end=dates[-1],
    )
    expected_windows = (N_DAYS - WINDOW_BARS) // STEP_BARS + 1
    assert summary.windows_processed == expected_windows


def _excluded_asset_ids_by_window(repo):
    """Recompute, per window, which asset_ids failed the I(1) pre-test -- from the persisted
    adf_results rows themselves, not from re-running the check. This is the ground truth the
    engine actually acted on.
    """
    by_window: dict[tuple, dict[int, dict[str, bool]]] = {}
    for row in repo.adf_results:
        key = (row["window_start"], row["window_end"])
        by_window.setdefault(key, {}).setdefault(row["asset_id"], {})[row["result"].series_type] = row[
            "result"
        ].is_stationary

    excluded: dict[tuple, set[int]] = {}
    for key, per_asset in by_window.items():
        excluded[key] = set()
        for asset_id, flags in per_asset.items():
            levels_stationary = flags.get("levels")
            diff_stationary = flags.get("first_diff")
            is_i1 = (not levels_stationary) and diff_stationary
            if not is_i1:
                excluded[key].add(asset_id)
    return excluded


def test_c_is_excluded_in_the_large_majority_of_windows():
    # C is pure white noise -- stationary in levels, so it fails the I(1) check. ADF is a 5%
    # test on ~90 samples, so an occasional false negative (C wrongly passing) is expected and
    # NOT a bug -- only a persistent failure to exclude C would indicate one.
    repo, dates = _build_repo()
    summary = run_rolling_cointegration(
        repo=repo, asset_class=ASSET_CLASS, symbols=["A", "B", "C"], baskets=[["A", "B", "C"]],
        window_bars=WINDOW_BARS, step_bars=STEP_BARS, start=dates[0], end=dates[-1],
    )
    assert summary.adf_exclusions >= summary.windows_processed - 2


def test_basket_only_runs_in_windows_where_every_member_passed_adf():
    repo, dates = _build_repo()
    run_rolling_cointegration(
        repo=repo, asset_class=ASSET_CLASS, symbols=["A", "B", "C"], baskets=[["A", "B", "C"]],
        window_bars=WINDOW_BARS, step_bars=STEP_BARS, start=dates[0], end=dates[-1],
    )
    excluded_by_window = _excluded_asset_ids_by_window(repo)
    basket_asset_ids = {1, 2, 3}  # A, B, C

    tested_windows = {
        (r["window_start"], r["window_end"]) for r in repo.johansen_results if len(r["asset_ids"]) == 3
    }
    for window_key, excluded in excluded_by_window.items():
        basket_should_run = basket_asset_ids.isdisjoint(excluded)
        assert (window_key in tested_windows) == basket_should_run


def test_every_bivariate_pair_tested_had_both_members_pass_adf():
    repo, dates = _build_repo()
    run_rolling_cointegration(
        repo=repo, asset_class=ASSET_CLASS, symbols=["A", "B", "C"], baskets=[["A", "B", "C"]],
        window_bars=WINDOW_BARS, step_bars=STEP_BARS, start=dates[0], end=dates[-1],
    )
    excluded_by_window = _excluded_asset_ids_by_window(repo)

    bivariate_results = [r for r in repo.johansen_results if len(r["asset_ids"]) == 2]
    assert bivariate_results  # sanity: the A-B pair should have been tested at least once

    for r in bivariate_results:
        window_key = (r["window_start"], r["window_end"])
        excluded = excluded_by_window[window_key]
        assert not set(r["asset_ids"]) & excluded, "a bivariate test ran with an ADF-failed member"

    # Every EG result row is one direction of a pair -- same invariant applies.
    for r in repo.engle_granger_results:
        window_key = (r["window_start"], r["window_end"])
        excluded = excluded_by_window[window_key]
        assert r["regressand_asset_id"] not in excluded
        assert r["regressor_asset_id"] not in excluded
