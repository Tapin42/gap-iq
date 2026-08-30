"""Enrich a committed roster with authoritative last names from World Triathlon start lists.

DataSport supplies a single combined name ("Surname Forename") and racedata derives
``last_name`` as the first token, which breaks on compound surnames such as "Brooks Jr".
The WT Program Entries API exposes ``athlete_last`` explicitly and joins cleanly on bib.

This is a pre-race, one-time pass over the roster JSON. Live timing still keys athletes
by ``athlete_slug`` (the datasport profile id), so enriching display names here does not
affect race-day parsing.

    python -m scripts.enrich_roster_names --roster roster.zofingen-2026.json

Requires ``TRIATHLON_API_KEY`` or falls back to the public read key bundled in WT's
OpenAPI examples (fine for start lists, but register your own for anything heavier).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from app.config import CONFIG_DIR

DEFAULT_API_KEY = "2649776ef9ece4c391003b521cbfce7a"
EVENT_ID = 195080


def _api_get(path: str, *, api_key: str) -> dict:
    url = f"https://api.triathlon.org/v1{path}"
    request = urllib.request.Request(
        url,
        headers={"apikey": api_key, "User-Agent": "gap-iq-enrich-roster-names"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise SystemExit(f"WT API {exc.code} for {url}: {body}") from exc
    if payload.get("status") != "success":
        raise SystemExit(f"WT API error for {url}: {payload}")
    return payload["data"]


def _slug_tokens(slug: str) -> frozenset[str]:
    return frozenset(slug.lower().split("-"))


def _match_entry(athlete: dict, by_bib: dict[str, dict], by_slug: dict[frozenset[str], dict]) -> dict | None:
    bib = str(athlete.get("bib") or "").strip()
    if bib and bib in by_bib:
        return by_bib[bib]
    tokens = _slug_tokens(athlete.get("athlete_slug", ""))
    if tokens and tokens in by_slug:
        return by_slug[tokens]
    return None


def fetch_wt_last_names(*, api_key: str, country: str) -> tuple[dict[str, dict], dict[frozenset[str], dict]]:
    """Return (by_bib, by_slug_token_set) indexes for WT entries in *country*."""
    programs = _api_get(f"/events/{EVENT_ID}/programs", api_key=api_key)
    by_bib: dict[str, dict] = {}
    by_slug: dict[frozenset[str], dict] = {}

    for program in programs:
        if not program.get("is_race"):
            continue
        prog_id = program["prog_id"]
        data = _api_get(f"/events/{EVENT_ID}/programs/{prog_id}/entries", api_key=api_key)
        for entry in data.get("entries") or []:
            if entry.get("athlete_noc") != country:
                continue
            bib = entry.get("start_num")
            if bib is not None:
                by_bib[str(bib)] = entry
            slug = str(entry.get("athlete_slug") or "").strip()
            if slug:
                by_slug[_slug_tokens(slug)] = entry
        time.sleep(0.05)

    return by_bib, by_slug


def enrich_roster(path: Path, *, api_key: str, country: str, dry_run: bool) -> int:
    raw = json.loads(path.read_text())
    athletes = raw.get("athletes") or []
    by_bib, by_slug = fetch_wt_last_names(api_key=api_key, country=country)

    updated = 0
    missing: list[str] = []
    for athlete in athletes:
        if athlete.get("country") != country:
            continue
        entry = _match_entry(athlete, by_bib, by_slug)
        if entry is None:
            missing.append(athlete.get("athlete_slug") or athlete.get("name") or "?")
            continue
        last_name = str(entry.get("athlete_last") or "").strip()
        if not last_name:
            missing.append(athlete.get("athlete_slug") or "?")
            continue
        if athlete.get("last_name") != last_name:
            athlete["last_name"] = last_name
            updated += 1

    if missing:
        print("No WT start-list match for:", ", ".join(missing), file=sys.stderr)

    if updated and not dry_run:
        path.write_text(json.dumps(raw, indent=1, ensure_ascii=False) + "\n")

    print(
        f"{'would update' if dry_run else 'updated'} {updated} "
        f"{country} athlete(s) in {path.name}"
    )
    return 1 if missing else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--roster",
        default="roster.zofingen-2026.json",
        help="Roster file under config/ (default: roster.zofingen-2026.json)",
    )
    parser.add_argument("--country", default="USA", help="NOC to enrich (default: USA)")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing")
    args = parser.parse_args(argv)

    api_key = os.environ.get("TRIATHLON_API_KEY", DEFAULT_API_KEY)
    path = CONFIG_DIR / args.roster
    if not path.exists():
        raise SystemExit(f"roster not found: {path}")

    return enrich_roster(path, api_key=api_key, country=args.country, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
