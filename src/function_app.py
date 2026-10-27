"""Azure Functions entry point (Python v2 programming model).

Functions
  POST /api/calendly        fn_calendly_receiver: verify, land, acknowledge (function key)
  GET  /api/health          liveness and configuration presence, no secrets (anonymous)
  timer                      fn_spend_fetcher: land new spend files on SPEND_FETCH_SCHEDULE
  GET  /api/spend/fetch     run the spend fetch on demand (function key)
"""

import json
import logging
import os
import time
from datetime import UTC, datetime

import azure.functions as func

from calendly_pipeline.config import load_settings
from calendly_pipeline.events import EventError, envelope, parse_event
from calendly_pipeline.landing import BlobLanding, Landing
from calendly_pipeline.spend_client import SpendFetcher
from calendly_pipeline.verify import HEADER_NAME, SignatureError, verify

app = func.FunctionApp()
log = logging.getLogger("calendly_pipeline")

_landing: Landing | None = None


def get_landing() -> Landing:
    global _landing
    if _landing is None:
        settings = load_settings()
        _landing = BlobLanding(settings.storage_account_url, settings.bronze_container)
    return _landing


def set_landing(landing: Landing | None) -> None:
    """Test hook: inject an in-memory landing zone."""
    global _landing
    _landing = landing


def _json_response(body: dict, status: int) -> func.HttpResponse:
    return func.HttpResponse(json.dumps(body), status_code=status, mimetype="application/json")


def handle_calendly(req: func.HttpRequest, landing: Landing | None = None) -> func.HttpResponse:
    """Receiver logic, separated from the decorator so that tests can call it directly."""
    settings = load_settings()
    started = time.perf_counter()
    raw_body = req.get_body()
    received_at = datetime.now(UTC)
    landing = landing or get_landing()

    verified = False
    if settings.verify_signature:
        try:
            verify(
                req.headers.get(HEADER_NAME),
                raw_body,
                settings.calendly_signing_key,
                settings.signature_tolerance_seconds,
            )
            verified = True
        except SignatureError as exc:
            log.warning(json.dumps({"stage": "verify", "outcome": "rejected", "reason": str(exc)}))
            return _json_response({"error": "invalid signature"}, 401)

    try:
        event = parse_event(raw_body, settings.subscribed_events)
    except EventError as exc:
        # Unsupported or malformed events are acknowledged so Calendly does not retry them.
        log.info(json.dumps({"stage": "parse", "outcome": "skipped", "reason": str(exc)}))
        return _json_response({"status": "skipped", "reason": str(exc)}, 200)

    path = event.landing_path(settings.calendly_landing_prefix)
    try:
        landing.write_json(
            path,
            envelope(event, received_at, verified),
            metadata={
                "event_name": event.event_name,
                "invitee_uuid": event.invitee_uuid,
                "received_at_utc": received_at.isoformat(timespec="seconds"),
            },
        )
    except Exception as exc:  # storage failure: ask Calendly to retry
        log.error(
            json.dumps(
                {
                    "stage": "land",
                    "outcome": "error",
                    "invitee_uuid": event.invitee_uuid,
                    "reason": str(exc),
                }
            )
        )
        return _json_response({"error": "landing failed"}, 500)

    elapsed_ms = round((time.perf_counter() - started) * 1000)
    log.info(
        json.dumps(
            {
                "stage": "land",
                "outcome": "landed",
                "event_name": event.event_name,
                "invitee_uuid": event.invitee_uuid,
                "event_type_uri": event.event_type_uri,
                "path": path,
                "signature_verified": verified,
                "elapsed_ms": elapsed_ms,
            }
        )
    )
    return _json_response({"status": "landed", "path": path}, 200)


@app.function_name(name="fn_calendly_receiver")
@app.route(route="calendly", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def fn_calendly_receiver(req: func.HttpRequest) -> func.HttpResponse:
    return handle_calendly(req)


@app.function_name(name="health")
@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    settings = load_settings()
    body = {
        "status": "ok",
        "utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "storage_configured": bool(settings.storage_account_url),
        "verify_signature": settings.verify_signature,
        "signing_key_present": bool(settings.calendly_signing_key)
        and settings.calendly_signing_key != "pending-from-program",
        "spend_schedule": os.getenv("SPEND_FETCH_SCHEDULE", ""),
        "subscribed_events": list(settings.subscribed_events),
    }
    return _json_response(body, 200)


def run_spend_fetch(landing: Landing | None = None) -> dict:
    settings = load_settings()
    fetcher = SpendFetcher(
        settings.spend_base_url,
        landing or get_landing(),
        settings.spend_landing_prefix,
        settings.spend_quarantine_prefix,
        settings.spend_lookback_days,
    )
    summary = fetcher.run()
    result = {
        "stage": "spend_fetch",
        "index_files": summary.index_files,
        "already_landed": summary.already_landed,
        "landed": summary.landed,
        "quarantined": summary.quarantined,
        "expected_latest": summary.expected_latest,
        "latest_available": summary.latest_available,
        "errors": summary.errors,
    }
    if not summary.latest_available:
        log.warning(json.dumps({**result, "outcome": "latest_missing"}))
    elif summary.errors or summary.quarantined:
        log.warning(json.dumps({**result, "outcome": "partial"}))
    else:
        log.info(json.dumps({**result, "outcome": "ok"}))
    return result


@app.function_name(name="fn_spend_fetcher")
@app.schedule(
    schedule="%SPEND_FETCH_SCHEDULE%", arg_name="timer", run_on_startup=False, use_monitor=True
)
def fn_spend_fetcher(timer: func.TimerRequest) -> None:
    run_spend_fetch()


@app.function_name(name="spend_fetch_now")
@app.route(route="spend/fetch", methods=["GET", "POST"], auth_level=func.AuthLevel.FUNCTION)
def spend_fetch_now(req: func.HttpRequest) -> func.HttpResponse:
    return _json_response(run_spend_fetch(), 200)
