"""The tracked-athlete roster, and the seam that will make it per-supporter later.

Today there is exactly one shared roster: several people are relaying the same Team USA
information, so they should all see the same list. The likely next use is the opposite --
one athlete, one supporter ("athlete A's brother tracks athlete A") -- so every roster read
and write goes through a *scope*, and today that scope is the constant ``shared``.

TODO(per-user-roster): making this per-browser means replacing `resolve_scope` with one
that derives a scope id from a cookie or client-supplied token, and seeding a new scope
from the committed defaults. Nothing else in the app needs to change; see
docs/per-user-roster.md.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path

from app.config import Settings, get_settings

log = logging.getLogger(__name__)

#: The single scope in use today. Deliberately a named constant rather than an inline
#: string so every site that will need to change is greppable.
SHARED_SCOPE = "shared"

SCOPE_AGEGROUP = "agegroup"
SCOPE_OVERALL = "overall"


def _derive_last_name(name: str) -> str:
    """datasport writes "Surname Forename", so the family name leads."""
    return name.split(" ")[0] if name else ""


@dataclass(frozen=True)
class TrackedAthlete:
    """One athlete on the roster."""

    athlete_slug: str
    name: str
    #: Family name for display. When absent in the roster JSON, derived at load time from
    #: the datasport "Surname Forename" name field. Populated from the WT start list
    #: pre-race so compound surnames display correctly on race day.
    last_name: str = ""
    bib: str = ""
    country: str = ""
    year_of_birth: int | None = None
    locality: str = ""
    favorite_id: str = ""
    contest: str = ""
    gender_list_slug: str = ""
    agegroup_list_slug: str = ""
    #: Per-athlete display scope. Age group by default, switchable to the wider field for
    #: anyone in contention overall.
    scope: str = SCOPE_AGEGROUP

    @property
    def has_agegroup(self) -> bool:
        """False for elite entrants, where age groups do not exist.

        Their two rank scopes resolve to the same list, so offering the toggle would be a
        no-op rather than a choice.
        """
        return bool(self.agegroup_list_slug)

    @property
    def effective_list_slug(self) -> str:
        """The division list whose standings this athlete's position comes from."""
        if self.scope == SCOPE_AGEGROUP and self.agegroup_list_slug:
            return self.agegroup_list_slug
        return self.gender_list_slug

    @property
    def effective_scope(self) -> str:
        return SCOPE_AGEGROUP if (self.scope == SCOPE_AGEGROUP and self.has_agegroup) else SCOPE_OVERALL


@dataclass
class RosterDocument:
    """Parsed roster configuration."""

    edition: str
    label: str
    provider: str
    season_year: int
    athletes: list[TrackedAthlete] = field(default_factory=list)
    excluded_checkpoint_labels: frozenset[str] = frozenset()
    default_scope: str = SCOPE_AGEGROUP


def load_roster_document(path: Path) -> RosterDocument:
    raw = json.loads(path.read_text())
    event = raw.get("event") or {}
    default_scope = raw.get("default_scope") or SCOPE_AGEGROUP
    athletes = [
        TrackedAthlete(
            athlete_slug=item["athlete_slug"],
            name=item.get("name", ""),
            last_name=item.get("last_name") or _derive_last_name(item.get("name", "")),
            bib=item.get("bib", ""),
            country=item.get("country", ""),
            year_of_birth=item.get("year_of_birth"),
            locality=item.get("locality", ""),
            favorite_id=item.get("favorite_id", ""),
            contest=item.get("contest", ""),
            gender_list_slug=item.get("gender_list_slug", ""),
            agegroup_list_slug=item.get("agegroup_list_slug", ""),
            scope=item.get("scope") or default_scope,
        )
        for item in raw.get("athletes", [])
    ]
    return RosterDocument(
        edition=event.get("edition", ""),
        label=event.get("label", ""),
        provider=event.get("provider", "datasport"),
        season_year=int(event.get("season_year") or 0),
        athletes=athletes,
        excluded_checkpoint_labels=frozenset(raw.get("excluded_checkpoint_labels") or ()),
        default_scope=default_scope,
    )


def resolve_scope(request_scope: str | None = None) -> str:
    """Which roster the caller should see.

    TODO(per-user-roster): return a per-browser identity here. Everything downstream
    already keys on the result, so this function is the whole change.
    """
    return SHARED_SCOPE


class RosterStore:
    """In-memory roster, seeded from committed configuration.

    Not persisted deliberately. The seed is in version control, so losing a machine costs
    only runtime edits, and that in turn means no volume, no single-host pin, and a machine
    that can be replaced mid-race without ceremony.

    TODO(per-user-roster): `_by_scope` is already keyed by scope, so per-supporter rosters
    need a real identity from `resolve_scope` and a persistence backend for edits.
    """

    def __init__(self, document: RosterDocument) -> None:
        self._lock = threading.RLock()
        self.document = document
        self._by_scope: dict[str, dict[str, TrackedAthlete]] = {
            SHARED_SCOPE: {athlete.athlete_slug: athlete for athlete in document.athletes}
        }

    def _bucket(self, scope: str) -> dict[str, TrackedAthlete]:
        if scope not in self._by_scope:
            # A new scope starts from the committed defaults rather than empty.
            self._by_scope[scope] = {
                athlete.athlete_slug: athlete for athlete in self.document.athletes
            }
        return self._by_scope[scope]

    def list_athletes(self, scope: str = SHARED_SCOPE) -> list[TrackedAthlete]:
        with self._lock:
            return sorted(self._bucket(scope).values(), key=lambda a: (a.name or a.athlete_slug))

    def get(self, athlete_slug: str, scope: str = SHARED_SCOPE) -> TrackedAthlete | None:
        with self._lock:
            return self._bucket(scope).get(athlete_slug)

    def add(self, athlete: TrackedAthlete, scope: str = SHARED_SCOPE) -> TrackedAthlete:
        with self._lock:
            bucket = self._bucket(scope)
            existing = bucket.get(athlete.athlete_slug)
            if existing is not None:
                # Preserve a scope choice a supporter already made.
                athlete = replace(athlete, scope=existing.scope)
            bucket[athlete.athlete_slug] = athlete
            return athlete

    def remove(self, athlete_slug: str, scope: str = SHARED_SCOPE) -> bool:
        with self._lock:
            return self._bucket(scope).pop(athlete_slug, None) is not None

    def set_scope(self, athlete_slug: str, display_scope: str, scope: str = SHARED_SCOPE) -> TrackedAthlete | None:
        with self._lock:
            bucket = self._bucket(scope)
            athlete = bucket.get(athlete_slug)
            if athlete is None:
                return None
            if display_scope == SCOPE_AGEGROUP and not athlete.has_agegroup:
                # Elite entrants have no age group; refuse rather than store a setting that
                # silently does nothing.
                return athlete
            updated = replace(athlete, scope=display_scope)
            bucket[athlete_slug] = updated
            return updated

    def favorite_ids(self, scope: str = SHARED_SCOPE) -> list[str]:
        return [a.favorite_id for a in self.list_athletes(scope) if a.favorite_id]

    def list_slugs_in_use(self, scope: str = SHARED_SCOPE) -> set[str]:
        """Every division list the roster needs standings for."""
        slugs: set[str] = set()
        for athlete in self.list_athletes(scope):
            if athlete.gender_list_slug:
                slugs.add(athlete.gender_list_slug)
        return slugs


_store: RosterStore | None = None


def get_roster_store(settings: Settings | None = None) -> RosterStore:
    global _store
    if _store is None:
        settings = settings or get_settings()
        document = load_roster_document(settings.roster_path)
        log.info(
            "roster loaded: %s athletes for %s (excluding %s checkpoints)",
            len(document.athletes),
            document.edition,
            len(document.excluded_checkpoint_labels),
        )
        _store = RosterStore(document)
    return _store


def reset_roster_cache() -> None:
    """Test seam."""
    global _store
    _store = None
