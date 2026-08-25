"""Record a completed race into a replay snapshot.

    python -m scripts.snapshot_race --edition <slug> --list <gender-list> --out snapshots/x.json

The output feeds app.replay, which serves it back through a virtual clock so the whole app
can be exercised offline and deterministically.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from racedata.core.models import Race
from racedata.core.standings import Division

from app.roster import load_roster_document
from app.config import CONFIG_DIR
from racedata.providers.datasport.service import DatasportProvider


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Snapshot a race for replay.")
    parser.add_argument("--edition", required=True)
    parser.add_argument("--list", dest="lists", action="append", required=True)
    parser.add_argument("--roster", default="roster.zofingen-2025.json")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    document = load_roster_document(CONFIG_DIR / args.roster)
    provider = DatasportProvider(excluded_checkpoint_labels=document.excluded_checkpoint_labels)
    race = Race(event_key=args.edition, display_name=args.edition, provider="datasport")

    agegroups = frozenset(a.agegroup_list_slug for a in document.athletes if a.agegroup_list_slug)
    athletes: dict[str, dict] = {}
    lists: dict[str, dict] = {}

    for slug in args.lists:
        division = Division(id=slug, label=slug)
        checkpoints = provider.list_checkpoints(race, division)
        lists.setdefault(slug, {"checkpoints": [], "times": {}, "withdrawn": []})
        for group in agegroups:
            lists.setdefault(group, {"checkpoints": [], "times": {}, "withdrawn": []})

        for checkpoint in checkpoints:
            entry = {
                "id": checkpoint.id,
                "label": checkpoint.label,
                "order": checkpoint.order,
                "elapsed_estimate_tenths": checkpoint.elapsed_estimate_tenths,
                "usable_for_gaps": checkpoint.usable_for_gaps,
                "exclusion_reason": checkpoint.exclusion_reason,
                "is_finish": checkpoint.is_finish,
            }
            lists[slug]["checkpoints"].append(entry)
            for group in agegroups:
                lists[group]["checkpoints"].append(entry)

            if not checkpoint.usable_for_gaps:
                continue

            overall, groups = provider.fetch_standings_bundle(
                race, division, checkpoint, agegroups
            )
            for standings, target in [(overall, slug), *[(g, s) for s, g in groups.items()]]:
                lists[target]["times"][checkpoint.id] = {
                    e.athlete.profile_id: e.clock_tenths for e in standings.entries
                }
                for athlete in standings.withdrawn:
                    if athlete.profile_id not in lists[target]["withdrawn"]:
                        lists[target]["withdrawn"].append(athlete.profile_id)
                for e in standings.entries:
                    athletes[e.athlete.profile_id] = {
                        "profile_id": e.athlete.profile_id,
                        "entry_id": e.athlete.entry_id,
                        "name": e.athlete.name,
                        "bib": e.athlete.bib,
                        "country": e.athlete.country,
                        "last_name": e.athlete.last_name,
                    }
                for athlete in standings.withdrawn:
                    athletes.setdefault(
                        athlete.profile_id,
                        {
                            "profile_id": athlete.profile_id,
                            "entry_id": athlete.entry_id,
                            "name": athlete.name,
                            "bib": athlete.bib,
                            "country": athlete.country,
                            "last_name": athlete.last_name,
                        },
                    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {"edition": args.edition, "athletes": list(athletes.values()), "lists": lists},
            indent=1,
        )
        + "\n"
    )
    total = sum(len(v["times"]) for v in lists.values())
    print(f"wrote {args.out}: {len(athletes)} athletes, {len(lists)} lists, {total} checkpoint snapshots")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
