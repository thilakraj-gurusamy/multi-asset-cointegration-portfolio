"""Rolling relationship-health monitoring (FRD Section 8.5) -- the project's core
differentiator. Consumes Phase 2's per-window output; computes hedge-ratio drift between
successive windows (which Phase 2 does not), classifies healthy/warning/halted per the FRD's
stated initial-default thresholds (pipeline/health/thresholds.py), logs every window's full
inputs (relationship_health), logs status TRANSITIONS specifically (health_status_transitions),
flags halted relationships for position review (position_review_flags), and fires an alert on
either a halted transition or a failed per-relationship health check (Section 9).

Each relationship has ONE canonical source method for health scoring: Engle-Granger for pairs
(a direct continuous p-value), Johansen for baskets (3+ assets, where EG does not apply --
pipeline/health/pseudo_pvalue.py supplies a documented proxy p-value instead). Phase 2's own
EG-vs-Johansen comparison for bivariate cases (method_disagreements) remains a separate
diagnostic and is not itself a health input here.

"Suspend new signal generation until it re-qualifies" (FRD point 3) needs no extra state
machine: HealthRepository.is_suspended(...) always reads the MOST RECENT window's
overall_status, so once a later window reclassifies back to healthy/warning, suspension lifts
on its own. A future Phase 4 signal generator should call is_suspended(...) before emitting any
new entry for a relationship.
"""
from __future__ import annotations

from dataclasses import dataclass

from pipeline import alerts
from pipeline.health.drift import compute_drift_pct
from pipeline.health.pseudo_pvalue import johansen_pseudo_p_value
from pipeline.health.repository import HealthRepository
from pipeline.health.thresholds import classify_half_life, classify_hedge_ratio_drift, classify_p_value, overall_status
from pipeline.logging_setup import get_logger

logger = get_logger(__name__)

RANK_ZERO_PROXY_P_VALUE = 0.999  # pinned above the warning ceiling: no cointegrating relation at all


@dataclass
class MonitorRunSummary:
    relationships_processed: int = 0
    windows_processed: int = 0
    transitions_logged: int = 0
    halted_transitions: int = 0
    failed_relationships: int = 0


def _handle_transition(
    repo: HealthRepository, asset_class: str, interval: str, relationship_key: str, relationship_type: str,
    window_end, previous_status, new_status, record: dict, alert_webhook_url, summary: MonitorRunSummary,
) -> None:
    if previous_status == new_status:
        return

    reason = {
        "p_value": record["p_value"],
        "p_value_status": record["p_value_status"],
        "hedge_ratio_drift_pct": record["hedge_ratio_drift_pct"],
        "hedge_ratio_drift_status": record["hedge_ratio_drift_status"],
        "half_life_days": record["half_life_days"],
        "half_life_status": record["half_life_status"],
    }
    repo.insert_transition(
        asset_class, interval,
        {
            "relationship_key": relationship_key, "relationship_type": relationship_type,
            "window_end": window_end, "previous_status": previous_status, "new_status": new_status,
            "reason": reason,
        },
    )
    summary.transitions_logged += 1
    logger.info(
        "Health transition: %s/%s %s %s -> %s at window_end=%s (%s)",
        asset_class, interval, relationship_key, previous_status, new_status, window_end, reason,
    )

    if new_status == "halted":
        summary.halted_transitions += 1
        repo.flag_position_for_review(asset_class, interval, relationship_key, window_end, reason)
        alerts.send_alert(
            alert_webhook_url, "relationship_halted",
            f"{asset_class}/{interval} {relationship_key} halted at {window_end}",
            reason,
        )


def _process_pair_series(
    repo: HealthRepository, asset_class: str, interval: str, relationship_key: str,
    windows: list[dict], alert_webhook_url, summary: MonitorRunSummary,
) -> None:
    previous_hedge_ratio = None
    previous_overall_status = None

    for w in windows:
        p_value_status = classify_p_value(w["p_value"])
        drift_pct = (
            compute_drift_pct(previous_hedge_ratio, w["hedge_ratio"]) if previous_hedge_ratio is not None else None
        )
        drift_status = classify_hedge_ratio_drift(drift_pct)
        half_life_status = classify_half_life(w["half_life_days"])
        status = overall_status(p_value_status, drift_status, half_life_status)

        record = {
            "relationship_key": relationship_key, "relationship_type": "pair", "source_method": "engle_granger",
            "window_start": w["window_start"], "window_end": w["window_end"],
            "p_value": w["p_value"], "p_value_is_proxy": False,
            "hedge_ratio_or_vector": w["hedge_ratio"], "hedge_ratio_drift_pct": drift_pct,
            "half_life_days": w["half_life_days"], "p_value_status": p_value_status,
            "hedge_ratio_drift_status": drift_status, "half_life_status": half_life_status,
            "overall_status": status,
        }
        repo.insert_relationship_health(asset_class, interval, record)
        summary.windows_processed += 1

        _handle_transition(
            repo, asset_class, interval, relationship_key, "pair", w["window_end"],
            previous_overall_status, status, record, alert_webhook_url, summary,
        )

        previous_hedge_ratio = w["hedge_ratio"]
        previous_overall_status = status


def _process_basket_series(
    repo: HealthRepository, asset_class: str, interval: str, relationship_key: str,
    windows: list[dict], alert_webhook_url, summary: MonitorRunSummary,
) -> None:
    previous_vector = None
    previous_overall_status = None

    for w in windows:
        if w["cointegration_rank"] >= 1 and w["cointegrating_vectors"]:
            p_value = johansen_pseudo_p_value(w["trace_stat"], w["crit_90"], w["crit_95"], w["crit_99"])
            vector = w["cointegrating_vectors"][0]
        else:
            p_value = RANK_ZERO_PROXY_P_VALUE
            vector = None

        p_value_status = classify_p_value(p_value)
        drift_pct = (
            compute_drift_pct(previous_vector, vector)
            if (previous_vector is not None and vector is not None)
            else None
        )
        drift_status = classify_hedge_ratio_drift(drift_pct)
        half_life_status = classify_half_life(w["half_life_days"])
        status = overall_status(p_value_status, drift_status, half_life_status)

        record = {
            "relationship_key": relationship_key, "relationship_type": "basket", "source_method": "johansen",
            "window_start": w["window_start"], "window_end": w["window_end"],
            "p_value": p_value, "p_value_is_proxy": True,
            "hedge_ratio_or_vector": vector if vector is not None else [], "hedge_ratio_drift_pct": drift_pct,
            "half_life_days": w["half_life_days"], "p_value_status": p_value_status,
            "hedge_ratio_drift_status": drift_status, "half_life_status": half_life_status,
            "overall_status": status,
        }
        repo.insert_relationship_health(asset_class, interval, record)
        summary.windows_processed += 1

        _handle_transition(
            repo, asset_class, interval, relationship_key, "basket", w["window_end"],
            previous_overall_status, status, record, alert_webhook_url, summary,
        )

        previous_vector = vector
        previous_overall_status = status


def run_health_monitor(
    repo: HealthRepository, asset_class: str, interval: str, start, end, alert_webhook_url: str | None = None,
) -> MonitorRunSummary:
    summary = MonitorRunSummary()

    pairs_by_key: dict[str, list[dict]] = {}
    for row in repo.get_canonical_pair_windows(asset_class, interval, start, end):
        pairs_by_key.setdefault(row["relationship_key"], []).append(row)

    for relationship_key, windows in pairs_by_key.items():
        try:
            _process_pair_series(repo, asset_class, interval, relationship_key, windows, alert_webhook_url, summary)
            summary.relationships_processed += 1
        except Exception as exc:
            summary.failed_relationships += 1
            logger.exception("Health check failed for pair %s/%s %s", asset_class, interval, relationship_key)
            alerts.send_alert(
                alert_webhook_url, "health_check_failed",
                f"Health check failed for {asset_class}/{interval} {relationship_key}", {"error": str(exc)},
            )

    baskets_by_key: dict[str, list[dict]] = {}
    for row in repo.get_basket_windows(asset_class, interval, start, end):
        baskets_by_key.setdefault(row["relationship_key"], []).append(row)

    for relationship_key, windows in baskets_by_key.items():
        try:
            _process_basket_series(repo, asset_class, interval, relationship_key, windows, alert_webhook_url, summary)
            summary.relationships_processed += 1
        except Exception as exc:
            summary.failed_relationships += 1
            logger.exception("Health check failed for basket %s/%s %s", asset_class, interval, relationship_key)
            alerts.send_alert(
                alert_webhook_url, "health_check_failed",
                f"Health check failed for {asset_class}/{interval} {relationship_key}", {"error": str(exc)},
            )

    return summary
