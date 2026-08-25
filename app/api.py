"""JSON API consumed by the SPA.

Gap views are computed on read rather than during the sweep. They are pure functions over
data already in memory, so recomputing costs nothing and it keeps one important property:
the current checkpoint and its baseline always come from the *same* sweep. Mixing a fresh
checkpoint with a stored older one can invent a change of neighbour that never happened,
because upstream erases withdrawn athletes from earlier checkpoints retroactively.
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from racedata.core.gaps import (
    ABSENT_LAST_PLACE,
    ABSENT_LEADING,
    STATUS_NOT_STARTED,
    GapView,
    NeighborGap,
    compute_gap_view,
)
from racedata.providers.datasport.parse import format_tenths

from app.config import get_settings
from app.freshness import Freshness
from app.poller import get_supervisor
from app.roster import SCOPE_AGEGROUP, SCOPE_OVERALL, TrackedAthlete, get_roster_store, resolve_scope
from app.state import STATE

log = logging.getLogger("gapiq.api")

router = APIRouter()


class ScopeUpdate(BaseModel):
    scope: str


class RosterAddition(BaseModel):
    athlete_slug: str
    name: str = ""
    bib: str = ""
    country: str = ""
    favorite_id: str = ""
    gender_list_slug: str = ""
    agegroup_list_slug: str = ""


def _athlete_payload(athlete: TrackedAthlete) -> dict:
    return {
        "athlete_slug": athlete.athlete_slug,
        "name": athlete.name,
        "last_name": athlete.last_name,
        "bib": athlete.bib,
        "country": athlete.country,
        "contest": athlete.contest,
        "scope": athlete.effective_scope,
        "scope_locked": not athlete.has_agegroup,
        "division_slug": athlete.effective_list_slug,
    }


def _neighbour_payload(gap: NeighborGap | None) -> dict | None:
    if gap is None:
        return None
    return {
        "slot": gap.slot,
        "name": gap.athlete.name,
        "last_name": gap.athlete.last_name,
        "bib": gap.athlete.bib,
        "country": gap.athlete.country,
        "position": gap.display_rank,
        "gap_tenths": gap.gap_tenths,
        "gap_text": format_tenths(gap.gap_tenths),
        "trend": gap.trend,
        "trend_delta_tenths": gap.trend_delta_tenths,
        "trend_delta_text": (
            format_tenths(gap.trend_delta_tenths, signed=True)
            if gap.trend_delta_tenths is not None
            else None
        ),
        "rate_tenths_per_minute": gap.rate_tenths_per_minute,
        "is_new_occupant": gap.is_new_occupant,
        "tied": gap.tied,
        "is_stale": gap.is_stale,
        "checkpoints_back": gap.checkpoints_back,
        "measured_at": gap.measured_at.label if gap.measured_at else None,
        "baseline": gap.baseline_checkpoint.label if gap.baseline_checkpoint else None,
    }


def _absence_copy(view: GapView) -> dict:
    """Human-facing explanations for a missing neighbour.

    Each case reads differently on purpose: leading, genuinely last, and "nobody has
    reached this mat yet" are three different situations that a single "no data" would
    flatten into something misleading.
    """
    out: dict[str, str] = {}
    if view.ahead_absent_reason == ABSENT_LEADING:
        out["ahead"] = f"Leading {view.division.display or 'the division'}."
    elif view.ahead_absent_reason:
        out["ahead"] = "No one ahead has been recorded here yet."
    if view.behind_absent_reason == ABSENT_LAST_PLACE:
        out["behind"] = "Last in the division for now — no one behind to report."
    elif view.behind_absent_reason:
        out["behind"] = "Nobody behind has reached this checkpoint yet."
    return out


def _ladder_for(athlete: TrackedAthlete):
    sweep = STATE.latest
    if sweep is None:
        return None, None
    slug = athlete.effective_list_slug
    by_checkpoint = sweep.standings.get(slug)
    if not by_checkpoint:
        return sweep, None
    return sweep, sorted(by_checkpoint.values(), key=lambda s: s.checkpoint.order)


def _freshness(athlete: TrackedAthlete | None, view: GapView | None) -> Freshness:
    settings = get_settings()
    health = STATE.snapshot_health()
    allowed, reason = settings.polling_allowed()
    sweep = STATE.latest

    last_seen_at = None
    checkpoint_label = ""
    next_expected = ""
    if view is not None and view.checkpoint is not None:
        checkpoint_label = view.checkpoint.label
        # The mat's own timestamp is not published, so the best available statement is when
        # we last saw this data. The checkpoint label is what actually bounds freshness.
        last_seen_at = sweep.finished_at if sweep else None
        if athlete is not None and sweep is not None:
            ladder = sweep.checkpoints.get(athlete.effective_list_slug) or []
            usable = [cp for cp in ladder if cp.usable_for_gaps]
            for index, cp in enumerate(usable):
                if cp.id == view.checkpoint.id and index + 1 < len(usable):
                    next_expected = usable[index + 1].label
                    break

    return Freshness(
        last_upstream_contact_at=health.last_contact_at,
        last_data_change_at=health.last_change_at,
        athlete_last_seen_at=last_seen_at,
        athlete_last_seen_checkpoint=checkpoint_label,
        next_expected_checkpoint=next_expected,
        server_time=time.time(),
        sweep_interval_seconds=settings.sweep_interval_seconds,
        polling_allowed=allowed,
        polling_reason=reason,
        degraded=health.circuit_open,
        degraded_reason=(health.last_error or "") if health.circuit_open else "",
        notes=tuple(sweep.anomalies[:5]) if sweep else (),
    )


# -- Endpoints --------------------------------------------------------------------------
@router.get("/meta")
async def meta() -> dict:
    settings = get_settings()
    store = get_roster_store()
    allowed, reason = settings.polling_allowed()
    sweep = STATE.latest
    return {
        "event": {
            "label": settings.event_label,
            "edition": settings.edition,
            "provider": settings.provider,
        },
        "polling": {"allowed": allowed, "reason": reason},
        "trend_policy": settings.trend_policy,
        "has_data": sweep is not None,
        "roster_count": len(store.list_athletes(resolve_scope())),
        "freshness": _freshness(None, None).as_payload(),
    }


@router.get("/roster")
async def roster() -> dict:
    """The roster page: every tracked athlete with position and progress.

    Backed by one upstream request per sweep for the whole list, and every field here is
    optional because before the gun the upstream response carries no time, progress or rank
    columns at all.
    """
    store = get_roster_store()
    scope = resolve_scope()
    sweep = STATE.latest
    rows = []

    for athlete in store.list_athletes(scope):
        progress = (sweep.roster_progress or {}).get(athlete.athlete_slug) if sweep else None
        view = None
        if sweep is not None:
            _, ladder = _ladder_for(athlete)
            if ladder:
                try:
                    view = compute_gap_view(
                        athlete_id=athlete.athlete_slug,
                        ladder=ladder,
                        min_baseline_separation_tenths=get_settings().min_baseline_separation_seconds * 10,
                        policy=get_settings().trend_policy,
                    )
                except ValueError:
                    view = None

        rows.append(
            {
                **_athlete_payload(athlete),
                "status": view.status if view else STATUS_NOT_STARTED,
                "position": view.display_rank if view else None,
                "field_size": view.field_size if view else None,
                "checkpoint": view.checkpoint.label if view and view.checkpoint else None,
                "elapsed_text": format_tenths(view.clock_tenths) if view and view.clock_tenths else None,
                "progress": getattr(progress, "progress", "") if progress else "",
                "ahead": _neighbour_payload(view.ahead) if view else None,
                "behind": _neighbour_payload(view.behind) if view else None,
            }
        )

    return {
        "athletes": rows,
        "freshness": _freshness(None, None).as_payload(),
        "scope_options": [SCOPE_AGEGROUP, SCOPE_OVERALL],
    }


@router.get("/athlete/{athlete_slug}")
async def athlete_detail(
    athlete_slug: str,
    checkpoint_index: int | None = Query(default=None, ge=0),
) -> dict:
    """The dashboard for one athlete.

    ``checkpoint_index`` selects an earlier checkpoint for the history view. The response
    always says whether it is showing the current checkpoint, so the client can style
    history unmistakably differently rather than relying on the user remembering.
    """
    store = get_roster_store()
    athlete = store.get(athlete_slug, resolve_scope())
    if athlete is None:
        raise HTTPException(status_code=404, detail=f"{athlete_slug} is not on the roster")

    sweep, ladder = _ladder_for(athlete)
    if sweep is None or not ladder:
        return {
            "athlete": _athlete_payload(athlete),
            "status": STATUS_NOT_STARTED,
            "has_data": False,
            "freshness": _freshness(athlete, None).as_payload(),
        }

    settings = get_settings()
    try:
        view = compute_gap_view(
            athlete_id=athlete_slug,
            ladder=ladder,
            at_index=checkpoint_index,
            min_baseline_separation_tenths=settings.min_baseline_separation_seconds * 10,
            policy=settings.trend_policy,
        )
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    usable = [s.checkpoint for s in ladder if s.checkpoint.usable_for_gaps]
    current_index = next(
        (i for i, cp in enumerate(usable) if cp.id == view.checkpoint.id), None
    )
    frontier = None
    for index, standings in enumerate(ladder):
        if standings.contains(athlete_slug):
            frontier = index

    return {
        "athlete": _athlete_payload(athlete),
        "status": view.status,
        "has_data": True,
        "position": view.display_rank,
        "field_size": view.field_size,
        "division": {
            "id": view.division.id,
            "label": view.division.display,
            "scope": view.division.scope,
        },
        "checkpoint": {
            "id": view.checkpoint.id,
            "label": view.checkpoint.label,
            "index": current_index,
            "count": len(usable),
            "is_finish": view.is_finish,
        },
        "is_live_checkpoint": current_index == frontier,
        "elapsed_text": format_tenths(view.clock_tenths) if view.clock_tenths else None,
        "baseline": view.baseline_checkpoint.label if view.baseline_checkpoint else None,
        "ahead": _neighbour_payload(view.ahead),
        "behind": _neighbour_payload(view.behind),
        "absence": _absence_copy(view),
        "withdrawal_notes": list(view.withdrawal_notes),
        "checkpoints": [
            {"index": i, "id": cp.id, "label": cp.label} for i, cp in enumerate(usable)
        ],
        "freshness": _freshness(athlete, view).as_payload(),
    }


@router.post("/refresh")
async def refresh() -> dict:
    """Force an immediate sweep.

    Ignores both the polling window and an open breaker: someone pressing this has more
    context than our schedule does.
    """
    supervisor = get_supervisor()
    ok = await supervisor.refresh_now()
    return {"ok": ok, "freshness": _freshness(None, None).as_payload()}


@router.post("/roster")
async def add_to_roster(addition: RosterAddition) -> dict:
    store = get_roster_store()
    athlete = store.add(
        TrackedAthlete(
            athlete_slug=addition.athlete_slug,
            name=addition.name or addition.athlete_slug,
            bib=addition.bib,
            country=addition.country,
            favorite_id=addition.favorite_id,
            gender_list_slug=addition.gender_list_slug,
            agegroup_list_slug=addition.agegroup_list_slug,
        ),
        resolve_scope(),
    )
    return _athlete_payload(athlete)


@router.delete("/roster/{athlete_slug}")
async def remove_from_roster(athlete_slug: str) -> dict:
    store = get_roster_store()
    if not store.remove(athlete_slug, resolve_scope()):
        raise HTTPException(status_code=404, detail=f"{athlete_slug} is not on the roster")
    return {"removed": athlete_slug}


@router.put("/roster/{athlete_slug}/scope")
async def set_scope(athlete_slug: str, update: ScopeUpdate) -> dict:
    if update.scope not in {SCOPE_AGEGROUP, SCOPE_OVERALL}:
        raise HTTPException(status_code=400, detail="scope must be 'agegroup' or 'overall'")
    store = get_roster_store()
    athlete = store.set_scope(athlete_slug, update.scope, resolve_scope())
    if athlete is None:
        raise HTTPException(status_code=404, detail=f"{athlete_slug} is not on the roster")
    return _athlete_payload(athlete)
