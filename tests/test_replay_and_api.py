"""Replay provider and end-to-end API tests.

The replay snapshot is a real completed race, so these exercise the whole stack -- sweeper,
gap engine, API serialisation -- without a network. What they cannot cover is anything the
finished data no longer contains (withdrawal events, revised times); those live in
tests/test_capture.py and racedata's synthetic gap tests.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from racedata.core.models import Race
from racedata.core.standings import Division

from app.config import REPO_ROOT, reset_settings_cache
from app.replay import ReplayClock, ReplayProvider
from app.roster import reset_roster_cache
from app.state import STATE

SNAPSHOT = REPO_ROOT / "snapshots" / "zofingen-2025-men.json"
GENDER_LIST = "world-triathlon-men-age-group"
AGE_GROUP = "world-triathlon-men-age-group-40-44"
RACE = Race(event_key="replay", display_name="replay", provider="replay")

pytestmark = pytest.mark.skipif(
    not SNAPSHOT.exists(),
    reason="replay snapshot absent; run scripts.snapshot_race to record one",
)


def provider_at(minutes: int) -> ReplayProvider:
    """A frozen virtual clock at a given elapsed race time."""
    return ReplayProvider(
        SNAPSHOT,
        clock=ReplayClock(started_at=time.time(), speed=0.0, offset_tenths=minutes * 600),
    )


def ladder_at(minutes: int, list_slug: str = AGE_GROUP):
    provider = provider_at(minutes)
    division = Division(id=GENDER_LIST, label="men")
    rungs = []
    for checkpoint in provider.list_checkpoints(RACE, division):
        if not checkpoint.usable_for_gaps:
            continue
        overall, groups = provider.fetch_standings_bundle(
            RACE, division, checkpoint, frozenset({AGE_GROUP})
        )
        standings = overall if list_slug == GENDER_LIST else groups[list_slug]
        if standings.entries:
            rungs.append(standings)
    return rungs


# -- The virtual clock ------------------------------------------------------------------
def test_nothing_has_happened_at_the_gun():
    assert ladder_at(0) == []


def test_the_race_reveals_itself_progressively():
    """Each later moment must show at least as much of the race as the one before."""
    counts = [len(ladder_at(minutes)) for minutes in (30, 90, 180, 300, 430)]

    assert counts == sorted(counts), f"checkpoints went backwards: {counts}"
    assert counts[0] < counts[-1], "the race never advanced"


def test_a_checkpoint_only_shows_athletes_who_have_reached_it():
    early = ladder_at(90)
    late = ladder_at(430)

    early_first = early[0]
    late_first = next(s for s in late if s.checkpoint.id == early_first.checkpoint.id)

    assert late_first.field_size >= early_first.field_size
    # And nobody visible early has a time later than the virtual clock allowed.
    assert all(entry.clock_tenths <= 90 * 600 for entry in early_first.entries)


def test_multi_crossing_mats_are_absent_from_the_replay_ladder():
    labels = {standings.checkpoint.label for standings in ladder_at(430)}
    assert "Run2 - WZ OUT" not in labels
    assert "Run2 - WZ IN" not in labels


def test_positions_are_renumbered_for_the_filtered_field():
    rungs = ladder_at(430)
    for standings in rungs:
        ranks = [entry.display_rank for entry in standings.entries]
        assert ranks == list(range(1, len(ranks) + 1)), standings.checkpoint.label


# -- The gap engine over replayed data --------------------------------------------------
def test_gap_view_over_a_replayed_race_matches_the_known_result():
    """Furler finished 2nd in M40-44 -- an independently published fact, so this pins the
    whole chain: parsing, age-group partitioning, renumbering and the gap engine."""
    from racedata.core.gaps import compute_gap_view

    view = compute_gap_view(athlete_id="furler-mark", ladder=ladder_at(430))

    assert view.checkpoint.label == "Finish"
    assert view.display_rank == 2
    assert view.ahead is not None and view.ahead.athlete.last_name == "Ripke"
    assert view.behind is not None and view.behind.athlete.last_name == "Castellano"


def test_mid_race_a_lone_leader_falls_back_to_an_earlier_shared_mat():
    """Reached naturally in replay: at five hours Furler is the only athlete in his age group
    to have crossed Bike - WZ IN, so both neighbours must come from earlier checkpoints and
    be marked as such rather than presented as current."""
    from racedata.core.gaps import compute_gap_view

    view = compute_gap_view(athlete_id="furler-mark", ladder=ladder_at(300))

    assert view.field_size == 1
    for neighbour in (view.ahead, view.behind):
        if neighbour is not None:
            assert neighbour.is_stale
            assert neighbour.measured_at is not None
            assert neighbour.measured_at.id != view.checkpoint.id


# -- End to end through the API ---------------------------------------------------------
@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("GAPIQ_PROVIDER", "replay")
    monkeypatch.setenv("GAPIQ_IGNORE_ACTIVE_WINDOWS", "true")
    monkeypatch.setenv("GAPIQ_ROSTER_FILE", "roster.zofingen-2025.json")
    monkeypatch.setenv("GAPIQ_REPLAY_OFFSET_SECONDS", str(430 * 60))
    monkeypatch.setenv("GAPIQ_REPLAY_SPEED", "0")
    reset_settings_cache()
    reset_roster_cache()

    from app.poller import PollerSupervisor, reset_supervisor

    reset_supervisor()
    from app.config import get_settings
    from app.roster import get_roster_store

    settings = get_settings()
    supervisor = PollerSupervisor(settings=settings, roster=get_roster_store(settings))
    STATE.publish(supervisor.sweeper.sweep())

    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client

    reset_supervisor()
    reset_settings_cache()
    reset_roster_cache()


def test_roster_endpoint_reports_positions_and_statuses(client):
    body = client.get("/api/roster").json()

    assert body["athletes"], "roster should not be empty"
    assert body["race"]["phase"] == "in_progress"
    assert body["race"]["label"] == "Race in progress"
    assert body["race"]["leading_checkpoint"] == "Finish"
    finished = [row for row in body["athletes"] if row["status"] == "finished"]
    assert finished, "the replay is at the end of the race, so some athletes finished"
    assert all(row["position"] for row in finished)


def test_athlete_endpoint_serialises_the_dashboard(client):
    body = client.get("/api/athlete/furler-mark").json()

    assert body["has_data"] is True
    assert body["position"] == 2
    assert body["division"]["label"] == "M40-44"
    assert body["ahead"]["last_name"] == "Ripke"
    assert body["behind"]["last_name"] == "Castellano"
    assert body["is_live_checkpoint"] is True
    # Freshness must be epochs, not pre-rendered prose the client cannot age.
    assert isinstance(body["freshness"]["server_time"], (int, float))
    assert "ago" not in str(body["freshness"])


def test_history_view_is_flagged_as_not_live(client):
    body = client.get("/api/athlete/furler-mark?checkpoint_index=3").json()

    assert body["is_live_checkpoint"] is False
    assert body["checkpoint"]["index"] == 3


def test_a_withdrawn_athlete_is_not_given_a_position(client):
    """Four Team USA athletes withdrew in 2025. They must read as off the course rather than
    being handed a bogus placing."""
    rows = client.get("/api/roster").json()["athletes"]
    withdrawn = [row for row in rows if row["status"] == "withdrawn"]

    assert withdrawn, "the 2025 field includes withdrawals"
    assert all(row["position"] is None for row in withdrawn)


def test_unknown_athlete_is_a_clean_404(client):
    response = client.get("/api/athlete/not-a-real-person")

    assert response.status_code == 404
    assert "roster" in response.json()["detail"]


def test_race_summary_before_any_timing_data():
    from app.api import _race_summary
    from app.state import SweepResult

    assert _race_summary(None)["phase"] == "waiting"
    assert _race_summary(SweepResult(started_at=0.0, finished_at=0.0))["phase"] == "not_started"


def test_race_summary_completed_when_the_field_has_mostly_finished(monkeypatch):
    monkeypatch.setenv("GAPIQ_PROVIDER", "replay")
    monkeypatch.setenv("GAPIQ_IGNORE_ACTIVE_WINDOWS", "true")
    monkeypatch.setenv("GAPIQ_ROSTER_FILE", "roster.zofingen-2025.json")
    monkeypatch.setenv("GAPIQ_REPLAY_OFFSET_SECONDS", str(600 * 60))
    monkeypatch.setenv("GAPIQ_REPLAY_SPEED", "0")
    reset_settings_cache()
    reset_roster_cache()

    from app.config import get_settings
    from app.poller import PollerSupervisor, reset_supervisor
    from app.roster import get_roster_store

    from app.api import _race_summary

    reset_supervisor()
    settings = get_settings()
    supervisor = PollerSupervisor(settings=settings, roster=get_roster_store(settings))
    assert _race_summary(supervisor.sweeper.sweep())["phase"] == "completed"
    reset_supervisor()
    reset_settings_cache()
    reset_roster_cache()


def test_meta_reports_the_event_and_freshness(client):
    body = client.get("/api/meta").json()

    assert body["has_data"] is True
    assert body["roster_count"] > 0
    assert body["freshness"]["polling"]["allowed"] is True


def test_health_is_ok_while_polling_is_permitted(client):
    body = client.get("/health").json()

    assert body["status"] in {"ok", "starting", "degraded"}
    assert body["polling"]["allowed"] is True
    assert body["runbook"].endswith("RUNBOOK.md")


def test_a_withdrawn_athlete_is_not_presented_as_a_history_view(client):
    """An athlete who withdrew has no frontier checkpoint, so there is no 'earlier
    checkpoint' being viewed. Reporting one dressed the screen in history chrome and implied
    the reader had navigated backwards."""
    rows = client.get("/api/roster").json()["athletes"]
    withdrawn = next(row for row in rows if row["status"] == "withdrawn")

    body = client.get(f"/api/athlete/{withdrawn['athlete_slug']}").json()

    assert body["status"] == "withdrawn"
    assert body["on_course"] is False
    assert body["is_live_checkpoint"] is True, "not a history view"
    assert body["checkpoint"]["index"] is None, "nothing to step through"


def test_an_athlete_on_course_still_reports_a_navigable_checkpoint(client):
    body = client.get("/api/athlete/furler-mark").json()

    assert body["on_course"] is True
    assert body["checkpoint"]["index"] is not None
