"""Health and liveness endpoints.

`/health/live` is the cheap fly.io check: is the process up. `/health` is the operational
one, and it is written to be *handed to an engineer or an AI agent* mid-incident -- it
carries the failure, the traceback, and a pointer to the runbook, because the person
reading it will not be the person who wrote the app and may well be in a hotel lobby.
"""

from __future__ import annotations

import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.state import STATE

router = APIRouter(tags=["health"])

RUNBOOK_URL = "https://github.com/Tapin42/gap-iq/blob/main/docs/RUNBOOK.md"


@router.get("/health/live", include_in_schema=False)
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health")
async def health() -> JSONResponse:
    settings = get_settings()
    h = STATE.snapshot_health()
    now = time.time()
    allowed, reason = settings.polling_allowed()

    def age(value: float | None) -> float | None:
        return None if value is None else round(now - value, 1)

    # "Idle because we are outside a race window" is healthy. "Idle because the poller
    # died" is not. Conflating them would make the alert useless.
    if h.circuit_open:
        status = "circuit_open"
    elif not allowed:
        status = "idle"
    elif not h.running:
        status = "starting"
    elif h.consecutive_failures > 0:
        status = "degraded"
    else:
        status = "ok"

    payload = {
        "status": status,
        "mode": "replay" if settings.provider == "replay" else "live",
        "now": now,
        "event": {"provider": settings.provider, "edition": settings.edition, "label": settings.event_label},
        "polling": {"allowed": allowed, "reason": reason, "running": h.running},
        # Three separate facts. See app/state.PollerHealth.
        "freshness": {
            "last_upstream_contact_at": h.last_contact_at,
            "last_upstream_contact_age_seconds": age(h.last_contact_at),
            "last_data_change_at": h.last_change_at,
            "last_data_change_age_seconds": age(h.last_change_at),
        },
        "poller": {
            "uptime_seconds": round(now - h.started_at, 1),
            "sweeps_completed": h.sweeps_completed,
            "total_upstream_requests": h.total_requests,
            "consecutive_failures": h.consecutive_failures,
            "restarts": h.restarts,
            "circuit_open": h.circuit_open,
            "circuit_opened_at": h.circuit_opened_at,
        },
        "last_error": {"message": h.last_error, "at": h.last_error_at, "age_seconds": age(h.last_error_at)},
        "runbook": RUNBOOK_URL,
    }

    if status in {"circuit_open", "degraded"}:
        payload["remediation"] = [
            "Press 'Force refresh' in the app header.",
            "fly machine restart --app gap-iq   (or click Restart in the fly.io dashboard)",
            f"Read the runbook: {RUNBOOK_URL}",
        ]

    # 503 when genuinely broken so external monitors notice without parsing the body.
    code = 503 if status == "circuit_open" else 200
    return JSONResponse(payload, status_code=code)
