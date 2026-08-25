"""JSON API consumed by the SPA.

Grows in step with the poller; see app/poller.py. Endpoints are written so that "we have
no data yet" is an explicit, describable state rather than an empty object, because the
SPA must be able to tell "the race has not started" apart from "something is broken".
"""

from __future__ import annotations

from fastapi import APIRouter

from app.config import get_settings
from app.state import STATE

router = APIRouter()


@router.get("/meta")
async def meta() -> dict:
    """Everything the SPA needs to render its chrome before any race data exists."""
    settings = get_settings()
    allowed, reason = settings.polling_allowed()
    return {
        "event": {
            "label": settings.event_label,
            "edition": settings.edition,
            "provider": settings.provider,
        },
        "polling": {"allowed": allowed, "reason": reason},
        "trend_policy": settings.trend_policy,
        "has_data": STATE.latest is not None,
    }
