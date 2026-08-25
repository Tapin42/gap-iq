"""Race-morning smoke check.

Every assertion here corresponds to a failure the upstream API reports with **HTTP 200**.
That is the whole reason this script exists: "the request succeeded" is not evidence that
the answer was right, so each check looks for positive confirmation instead.

    python -m scripts.preflight --edition powerman-world-championships-zofingen-2026

Exit code 0 means clear to race. 1 means something needs a human.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from racedata.core.models import Race
from racedata.core.standings import Division
from racedata.providers.datasport.course import monotonicity_violations
from racedata.providers.datasport.parse import OrderNotAppliedError, assert_order_applied
from racedata.providers.datasport.service import DatasportProvider

from app.config import CONFIG_DIR
from app.roster import load_roster_document

PASS = "PASS"
FAIL = "FAIL"
WARN = "WARN"


@dataclass
class Check:
    name: str
    status: str
    detail: str


def run(edition: str, roster_file: str, *, deep: bool) -> list[Check]:
    checks: list[Check] = []
    document = load_roster_document(CONFIG_DIR / roster_file)
    provider = DatasportProvider(
        excluded_checkpoint_labels=document.excluded_checkpoint_labels
    )
    race = Race(event_key=edition, display_name=document.label, provider="datasport")

    # 1. The edition resolves at all. A renamed slug answers 200 with an empty tree.
    divisions = provider.list_divisions(race)
    if divisions:
        checks.append(Check("edition resolves", PASS, f"{len(divisions)} result lists"))
    else:
        checks.append(
            Check(
                "edition resolves",
                FAIL,
                f"no divisions for {edition!r}. A renamed edition slug returns 200 with an "
                "empty tree, so check the slug against the event page.",
            )
        )
        return checks

    by_id = {division.id: division for division in divisions}

    # 2. Every list the roster depends on still exists under the same slug.
    missing_lists = sorted(
        {
            slug
            for athlete in document.athletes
            for slug in (athlete.gender_list_slug, athlete.agegroup_list_slug)
            if slug and slug not in by_id
        }
    )
    checks.append(
        Check("roster list slugs resolve", PASS, "all present")
        if not missing_lists
        else Check(
            "roster list slugs resolve",
            FAIL,
            f"{len(missing_lists)} slug(s) no longer exist: {missing_lists}. Slugs rotate "
            "between editions; re-run scripts/seed_roster.py.",
        )
    )

    # 3. Favourite ids still resolve. Unknown ids are dropped silently with a 200.
    favourite_ids = [a.favorite_id for a in document.athletes if a.favorite_id]
    if favourite_ids:
        _, dropped = provider.fetch_favorites(race, favourite_ids)
        checks.append(
            Check("favourite ids resolve", PASS, f"{len(favourite_ids)} athletes")
            if not dropped
            else Check(
                "favourite ids resolve",
                FAIL,
                f"{len(dropped)} id(s) were silently dropped: {dropped}. Those athletes "
                "would vanish from the roster with no error.",
            )
        )

    # 4. Checkpoints, ordering and the multi-crossing exclusions.
    gender_slugs = sorted({a.gender_list_slug for a in document.athletes if a.gender_list_slug})
    for slug in gender_slugs:
        division = by_id.get(slug) or Division(id=slug, label=slug)
        checkpoints = provider.list_checkpoints(race, division)
        if not checkpoints:
            checks.append(Check(f"checkpoints for {slug}", FAIL, "none offered"))
            continue

        usable = [cp for cp in checkpoints if cp.usable_for_gaps]
        excluded = sorted(cp.label for cp in checkpoints if not cp.usable_for_gaps)
        checks.append(
            Check(
                f"checkpoints for {slug}",
                PASS,
                f"{len(usable)} usable, {len(excluded)} excluded ({excluded or 'none'})",
            )
        )

        expected = sorted(document.excluded_checkpoint_labels)
        if expected and excluded != expected:
            checks.append(
                Check(
                    f"excluded mats for {slug}",
                    WARN,
                    f"expected {expected}, got {excluded}. Multi-crossing mats are "
                    "event-specific; re-verify with detect_multi_crossing_labels.",
                )
            )

        violations = monotonicity_violations(checkpoints)
        if violations:
            checks.append(
                Check(f"course order for {slug}", FAIL, f"runs backwards at {violations}")
            )

        # 5. An id can remain valid but point at a different checkpoint. Only a label check
        #    catches that, and only a real request can perform it.
        probes = [usable[0], usable[len(usable) // 2], usable[-1]] if deep else [usable[-1]]
        for checkpoint in probes:
            try:
                response = provider.client.call(
                    "ranking", edition=edition, slug=slug, order=checkpoint.id, count=1
                )
                assert_order_applied(
                    response.payload, checkpoint.id, expected_label=checkpoint.label
                )
                checks.append(
                    Check(f"order {checkpoint.id} -> {checkpoint.label}", PASS, "applied")
                )
            except OrderNotAppliedError as exc:
                checks.append(Check(f"order {checkpoint.id}", FAIL, str(exc)))

    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Race-morning smoke check.")
    parser.add_argument("--edition", required=True)
    parser.add_argument("--roster", default="roster.zofingen-2026.json")
    parser.add_argument(
        "--deep",
        action="store_true",
        help="probe several checkpoints per list rather than just the finish",
    )
    args = parser.parse_args(argv)

    checks = run(args.edition, args.roster, deep=args.deep)

    width = max((len(check.name) for check in checks), default=10)
    for check in checks:
        print(f"[{check.status}] {check.name.ljust(width)}  {check.detail}")

    failures = [check for check in checks if check.status == FAIL]
    warnings = [check for check in checks if check.status == WARN]
    print()
    print(
        f"{len(checks)} checks, {len(failures)} failing, {len(warnings)} warning"
        + ("" if len(warnings) == 1 else "s")
    )
    if failures:
        print("\nNOT clear to race. See docs/RUNBOOK.md.")
        return 1
    print("\nClear to race." + (" Review the warnings above." if warnings else ""))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
