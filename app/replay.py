"""Replay a real race through a virtual clock.

A completed race is turned back into a progressive one by hiding anything that had not
happened yet at the virtual moment: at elapsed time *T*, a checkpoint shows only the
athletes whose own elapsed time there is at or below *T*. That produces a genuine, fully
deterministic race — positions change, fields fill in from the front, and chasers arrive at
mats late — with no network and at whatever speed you like.

**This is a harness, not ground truth.** Finished results have been cleaned: an athlete who
withdrew is erased from every checkpoint, provisional times are revised away, and mats that
were briefly down leave no trace. So a replay contains no withdrawal *event*, no revision
and no outage, and the positions it shows are not exactly the ones that were live. Use it to
exercise the poller, the API and the UI; use synthetic fixtures and captured live frames for
the semantics it cannot express.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, replace
from pathlib import Path

from racedata.core.models import AthleteRef, Race
from racedata.core.standings import (
    SCOPE_AGEGROUP,
    Checkpoint,
    CheckpointStandings,
    Division,
    build_entries,
)
from racedata.providers.datasport.service import RosterEntry, short_label_from_slug

log = logging.getLogger("gapiq.replay")


@dataclass(frozen=True)
class ReplayClock:
    """Maps wall-clock time onto race elapsed time."""

    started_at: float
    speed: float = 60.0
    offset_tenths: int = 0

    def elapsed_tenths(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        return self.offset_tenths + int(max(0.0, now - self.started_at) * self.speed * 10)


class ReplayProvider:
    """Serves a recorded race, progressively revealed.

    Deliberately mirrors only the surface the sweeper uses, so swapping it in exercises the
    real poller and API rather than a parallel code path.
    """

    def __init__(self, snapshot_path: Path, clock: ReplayClock | None = None) -> None:
        raw = json.loads(Path(snapshot_path).read_text())
        self.edition = raw.get("edition", "replay")
        self.clock = clock or ReplayClock(started_at=time.time())
        self._checkpoints: dict[str, list[Checkpoint]] = {}
        self._times: dict[str, dict[str, dict[str, int]]] = {}
        self._athletes: dict[str, AthleteRef] = {}
        self._withdrawn: dict[str, list[str]] = {}
        self.client = _NullClient()

        for athlete in raw.get("athletes", []):
            self._athletes[athlete["profile_id"]] = AthleteRef(
                profile_id=athlete["profile_id"],
                entry_id=athlete.get("entry_id", ""),
                name=athlete.get("name", ""),
                bib=athlete.get("bib", ""),
                country=athlete.get("country", ""),
                last_name=athlete.get("last_name", ""),
            )

        for slug, payload in (raw.get("lists") or {}).items():
            self._checkpoints[slug] = [
                Checkpoint(
                    id=cp["id"],
                    label=cp["label"],
                    order=cp["order"],
                    elapsed_estimate_tenths=cp.get("elapsed_estimate_tenths"),
                    usable_for_gaps=cp.get("usable_for_gaps", True),
                    exclusion_reason=cp.get("exclusion_reason", ""),
                    is_finish=cp.get("is_finish", False),
                )
                for cp in payload.get("checkpoints", [])
            ]
            self._times[slug] = {
                cp_id: {k: int(v) for k, v in times.items()}
                for cp_id, times in (payload.get("times") or {}).items()
            }
            self._withdrawn[slug] = list(payload.get("withdrawn") or [])

    # -- Sweeper surface ---------------------------------------------------------------
    def list_divisions(self, race: Race) -> list[Division]:
        return [
            Division(id=slug, label=slug, short_label=short_label_from_slug(slug))
            for slug in sorted(self._checkpoints)
        ]

    def list_checkpoints(self, race: Race, division: Division) -> list[Checkpoint]:
        return list(self._checkpoints.get(division.id, []))

    def fetch_standings_bundle(
        self,
        race: Race,
        division: Division,
        checkpoint: Checkpoint,
        agegroup_slugs: frozenset[str] = frozenset(),
    ) -> tuple[CheckpointStandings, dict[str, CheckpointStandings]]:
        elapsed = self.clock.elapsed_tenths()
        times = self._times.get(division.id, {}).get(checkpoint.id, {})

        rows = [
            (self._athletes[athlete_id], tenths, None, None, "")
            for athlete_id, tenths in times.items()
            # The whole trick: nothing that had not happened yet is visible.
            if tenths <= elapsed and athlete_id in self._athletes
        ]
        withdrawn = tuple(
            self._athletes[a] for a in self._withdrawn.get(division.id, []) if a in self._athletes
        )

        overall = self._build(checkpoint, division, rows, withdrawn)

        groups: dict[str, CheckpointStandings] = {}
        for slug in agegroup_slugs:
            group_times = self._times.get(slug, {}).get(checkpoint.id, {})
            group_rows = [
                (self._athletes[a], t, None, None, "")
                for a, t in group_times.items()
                if t <= elapsed and a in self._athletes
            ]
            groups[slug] = self._build(
                checkpoint,
                Division(
                    id=slug,
                    label=slug,
                    short_label=short_label_from_slug(slug),
                    scope=SCOPE_AGEGROUP,
                ),
                group_rows,
                withdrawn,
            )
        return overall, groups

    def _build(self, checkpoint, division, rows, withdrawn):
        # Snapshots carry no provider rank, so position within the visible field is the only
        # number available -- and it is what upstream would publish anyway.
        entries = tuple(
            replace(entry, display_rank=entry.index + 1) for entry in build_entries(rows)
        )
        return CheckpointStandings(
            checkpoint=checkpoint,
            division=division,
            entries=entries,
            withdrawn=withdrawn,
            fetched_at=time.time(),
        )

    def fetch_favorites(self, race: Race, favorite_ids: list[str]):
        """Replays have no watch-list endpoint; the roster page falls back to standings."""
        return [], []

    def fetch_roster(self, race: Race, *, division: Division | None = None) -> list[AthleteRef]:
        return list(self._athletes.values())


class _NullClient:
    """Stands in for the HTTP client so request accounting still works."""

    request_count = 0
