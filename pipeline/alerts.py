"""Minimal alert hook (FRD Section 9, Observability).

Every call always logs at ERROR/CRITICAL. If ALERT_WEBHOOK_URL is configured, it also makes a
best-effort POST to that URL -- a failure to deliver the webhook must never crash the pipeline,
so network errors here are caught and logged, not raised.
"""
from __future__ import annotations

import requests

from pipeline.logging_setup import get_logger

logger = get_logger(__name__)


def send_alert(webhook_url: str | None, event_type: str, message: str, details: dict | None = None) -> None:
    logger.error("ALERT [%s] %s | details=%s", event_type, message, details or {})

    if not webhook_url:
        return

    payload = {"event_type": event_type, "message": message, "details": details or {}}
    try:
        requests.post(webhook_url, json=payload, timeout=5)
    except requests.RequestException:
        logger.warning("Failed to deliver alert webhook for event_type=%s", event_type, exc_info=True)
