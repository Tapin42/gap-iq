"""Sweep replayed race time and check gap-view invariants for every tracked athlete.

The replay snapshot is a completed 2025 race stepped forward minute by minute. At each
virtual moment this script builds the same ladder the poller would, runs ``compute_gap_view``
for every roster athlete, and flags anything that would look wrong on the dashboard.

Errors are logic bugs (duplicate neighbours, stale rows contradicting current standings).
Warnings are suspicious but intentional cases (``of 1 in division`` when the athlete is
solely recorded at the current mat while rivals are still racing elsewhere).

    python -m scripts.validate_replay
    python -m scripts.validate_replay --step 5 --max-minutes 430
    python -m scripts.validate_replay --athlete furler-mark --verbose

Exit code 0 when no errors; 1 when any invariant fails.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from racedata.core.gaps import (
    AHEAD,
    BEHIND,
    compute_gap_view,
)
from racedata.core.models import Race
from racedata.core.standings import CheckpointStandings, Division

from app.config import CONFIG_DIR, REPO_ROOT
from app.replay import ReplayClock, ReplayProvider
from app.roster import TrackedAthlete, load_roster_document

SNAPSHOT = REPO_ROOT / "snapshots" / "zofingen-2025-men.json"
DEFAULT_ROSTER = "roster.zofingen-2025.json"

ERROR = "ERROR"
WARN = "WARN"


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    minute: int
    athlete_slug: str
    checkpoint: str
    detail: str


def _pass_confirmed_at_current(
    usable: list[CheckpointStandings],
    athlete_id: str,
    slot: str,
    current: int,
    neighbour_id: str,
) -> bool:
    """Mirror of racedata.core.gaps._pass_confirmed_at_current for validation."""
    mine = usable[current].find(athlete_id)
    theirs = usable[current].find(neighbour_id)
    if mine is None or theirs is None:
        return False
    if slot == AHEAD:
        return theirs.index > mine.index
    return theirs.index < mine.index


def _division_finish_sizes(provider: ReplayProvider, list_slugs: set[str]) -> dict[str, int]:
    """How many athletes finish in each division list (full snapshot, no clock filter)."""
    race = Race(event_key="replay", display_name="replay", provider="replay")
    sizes: dict[str, int] = {}
    for slug in sorted(list_slugs):
        division = Division(id=slug, label=slug)
        checkpoints = provider.list_checkpoints(race, division)
        finish = next((cp for cp in reversed(checkpoints) if cp.is_finish), None)
        if finish is None:
            continue
        _, groups = provider.fetch_standings_bundle(race, division, finish, frozenset({slug}))
        standings = groups.get(slug)
        if standings is not None:
            sizes[slug] = standings.field_size
    return sizes


def _build_ladder(
    provider: ReplayProvider,
    list_slug: str,
    gender_slug: str,
) -> list[CheckpointStandings]:
    race = Race(event_key="replay", display_name="replay", provider="replay")
    gender_division = Division(id=gender_slug, label=gender_slug)
    checkpoints = provider.list_checkpoints(race, gender_division)
    ladder: list[CheckpointStandings] = []
    for checkpoint in checkpoints:
        if not checkpoint.usable_for_gaps:
            continue
        _, groups = provider.fetch_standings_bundle(
            race, gender_division, checkpoint, frozenset({list_slug})
        )
        standings = groups.get(list_slug)
        if standings and standings.entries:
            ladder.append(standings)
    return ladder


def _check_view(
    *,
    minute: int,
    athlete: TrackedAthlete,
    ladder: list[CheckpointStandings],
    division_finish_size: int | None,
) -> list[Finding]:
    if not ladder:
        return []

    try:
        view = compute_gap_view(athlete_id=athlete.athlete_slug, ladder=ladder)
    except ValueError:
        return []

    if view.display_rank is None or view.field_size == 0:
        return []

    findings: list[Finding] = []
    slug = athlete.athlete_slug
    cp = view.checkpoint.label

    usable = [s for s in ladder if s.checkpoint.usable_for_gaps]
    current = next(
        (i for i, s in enumerate(usable) if s.checkpoint.id == view.checkpoint.id),
        None,
    )

    # Duplicate neighbour — the bug we fixed for mat-order crossings.
    if (
        view.ahead is not None
        and view.behind is not None
        and view.ahead.athlete.profile_id == view.behind.athlete.profile_id
    ):
        name = view.ahead.athlete.last_name or view.ahead.athlete.profile_id
        findings.append(
            Finding(
                ERROR,
                "duplicate_neighbour",
                minute,
                slug,
                cp,
                f"{name} appears as both stale/fresh ahead and behind",
            )
        )

    for slot_name, neighbour, absent in (
        ("ahead", view.ahead, view.ahead_absent_reason),
        ("behind", view.behind, view.behind_absent_reason),
    ):
        if neighbour is None:
            continue

        if neighbour.is_stale and neighbour.measured_at is not None:
            if neighbour.measured_at.id == view.checkpoint.id:
                findings.append(
                    Finding(
                        ERROR,
                        "stale_at_current_mat",
                        minute,
                        slug,
                        cp,
                        f"stale {slot_name} neighbour measured at the current checkpoint",
                    )
                )

            if current is not None and _pass_confirmed_at_current(
                usable,
                athlete.athlete_slug,
                AHEAD if slot_name == "ahead" else BEHIND,
                current,
                neighbour.athlete.profile_id,
            ):
                name = neighbour.athlete.last_name or neighbour.athlete.profile_id
                findings.append(
                    Finding(
                        ERROR,
                        "stale_contradicts_current",
                        minute,
                        slug,
                        cp,
                        f"stale {slot_name} {name} is on the opposite side at {cp}",
                    )
                )

        if not neighbour.is_stale and neighbour.measured_at is not None:
            if neighbour.measured_at.id != view.checkpoint.id:
                findings.append(
                    Finding(
                        ERROR,
                        "fresh_from_wrong_mat",
                        minute,
                        slug,
                        cp,
                        f"fresh {slot_name} neighbour measured at {neighbour.measured_at.label}",
                    )
                )

    rank = view.display_rank
    if rank < 1 or rank > view.field_size:
        findings.append(
            Finding(
                ERROR,
                "rank_out_of_bounds",
                minute,
                slug,
                cp,
                f"position {rank} outside field of {view.field_size}",
            )
        )

    if view.ahead is not None and not view.ahead.is_stale and view.ahead.display_rank >= rank:
        findings.append(
            Finding(
                ERROR,
                "ahead_not_ahead",
                minute,
                slug,
                cp,
                f"fresh ahead rank {view.ahead.display_rank} is not better than {rank}",
            )
        )

    if view.behind is not None and not view.behind.is_stale and view.behind.display_rank <= rank:
        findings.append(
            Finding(
                ERROR,
                "behind_not_behind",
                minute,
                slug,
                cp,
                f"fresh behind rank {view.behind.display_rank} is not worse than {rank}",
            )
        )

    # Dashboard shows "of 1 in {division}" — reads like sole division member.
    if (
        view.field_size == 1
        and division_finish_size is not None
        and division_finish_size > 1
        and view.status not in {"withdrawn", "not_started"}
    ):
        findings.append(
            Finding(
                WARN,
                "lone_at_mat",
                minute,
                slug,
                cp,
                f"of 1 in {view.division.display} while division finishes {division_finish_size}",
            )
        )

    return findings


def run(
    *,
    snapshot: Path,
    roster_file: str,
    step_minutes: int,
    max_minutes: int,
    athlete_filter: set[str] | None,
    verbose: bool,
) -> list[Finding]:
    document = load_roster_document(CONFIG_DIR / roster_file)
    athletes = document.athletes
    if athlete_filter:
        athletes = [a for a in athletes if a.athlete_slug in athlete_filter]

    finish_provider = ReplayProvider(
        snapshot,
        clock=ReplayClock(started_at=time.time(), speed=0.0, offset_tenths=999_999_999),
    )
    list_slugs = {a.effective_list_slug for a in athletes}
    gender_by_list = {a.effective_list_slug: a.gender_list_slug for a in athletes}
    division_finish_sizes = _division_finish_sizes(finish_provider, list_slugs)

    # Cache ladders per (minute, list_slug) — many athletes share a division.
    ladder_cache: dict[tuple[int, str], list[CheckpointStandings]] = {}
    findings: list[Finding] = []

    for minute in range(0, max_minutes + 1, step_minutes):
        provider = ReplayProvider(
            snapshot,
            clock=ReplayClock(
                started_at=time.time(), speed=0.0, offset_tenths=minute * 600
            ),
        )
        for athlete in athletes:
            list_slug = athlete.effective_list_slug
            cache_key = (minute, list_slug)
            if cache_key not in ladder_cache:
                ladder_cache[cache_key] = _build_ladder(
                    provider, list_slug, gender_by_list[list_slug]
                )
            ladder = ladder_cache[cache_key]
            if not any(s.contains(athlete.athlete_slug) for s in ladder):
                continue
            findings.extend(
                _check_view(
                    minute=minute,
                    athlete=athlete,
                    ladder=ladder,
                    division_finish_size=division_finish_sizes.get(list_slug),
                )
            )
            if verbose and minute % (step_minutes * 10) == 0:
                print(f"  {minute:4d} min  {athlete.athlete_slug}", file=sys.stderr)

    return findings


def _summarize(findings: list[Finding]) -> None:
    errors = [f for f in findings if f.severity == ERROR]
    warnings = [f for f in findings if f.severity == WARN]

    by_code: dict[str, list[Finding]] = defaultdict(list)
    for finding in findings:
        by_code[f"{finding.severity}:{finding.code}"].append(finding)

    for key in sorted(by_code):
        group = by_code[key]
        sample = group[0]
        print(f"\n[{sample.severity}] {sample.code}  ({len(group)} occurrence(s))")
        for finding in group[:5]:
            print(
                f"  {finding.minute:4d} min  {finding.athlete_slug:20s}  "
                f"{finding.checkpoint:22s}  {finding.detail}"
            )
        if len(group) > 5:
            print(f"  … and {len(group) - 5} more")

    print()
    print(
        f"{len(errors)} error(s), {len(warnings)} warning(s)"
        + (" (lone-at-mat copy is expected mid-race)" if warnings else "")
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay dashboard invariant sweep.")
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=SNAPSHOT,
        help="Completed race snapshot JSON",
    )
    parser.add_argument("--roster", default=DEFAULT_ROSTER)
    parser.add_argument(
        "--step",
        type=int,
        default=1,
        metavar="MINUTES",
        help="Virtual clock step (default: every minute)",
    )
    parser.add_argument(
        "--max-minutes",
        type=int,
        default=430,
        help="Stop after this elapsed race minute",
    )
    parser.add_argument(
        "--athlete",
        action="append",
        dest="athletes",
        metavar="SLUG",
        help="Limit to one or more athlete slugs (repeatable)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print progress to stderr",
    )
    args = parser.parse_args(argv)

    if not args.snapshot.exists():
        print(f"Snapshot missing: {args.snapshot}", file=sys.stderr)
        print("Run: python -m scripts.snapshot_race …", file=sys.stderr)
        return 1

    athlete_filter = set(args.athletes) if args.athletes else None
    if args.verbose:
        print(
            f"Sweeping {args.snapshot.name} every {args.step} min "
            f"for {args.max_minutes} min…",
            file=sys.stderr,
        )

    findings = run(
        snapshot=args.snapshot,
        roster_file=args.roster,
        step_minutes=args.step,
        max_minutes=args.max_minutes,
        athlete_filter=athlete_filter,
        verbose=args.verbose,
    )
    _summarize(findings)

    errors = [f for f in findings if f.severity == ERROR]
    if errors:
        print("\nReplay invariants FAILED.")
        return 1
    print("\nReplay invariants passed.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
