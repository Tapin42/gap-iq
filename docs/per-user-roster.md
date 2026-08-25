# Moving from one shared roster to per-supporter rosters

Today Gap IQ has exactly one roster, shared by everyone with the URL. That is the right
shape for Zofingen: several people are relaying the same Team USA information, so they
should all see the same list, and there is nothing to log into.

The likely next use is the opposite. At an Ironman or a USA Triathlon national championship
the pattern is one athlete, one supporter — athlete A's brother tracks athlete A, athlete
B's wife tracks athlete B — and a shared roster becomes a list of strangers.

## The seam

Every roster read and write already goes through a **scope**, and today that scope is the
constant `"shared"`. Grep for `TODO(per-user-roster)` to find each site.

```python
# app/roster.py
SHARED_SCOPE = "shared"

def resolve_scope(request_scope: str | None = None) -> str:
    return SHARED_SCOPE
```

`RosterStore` is already keyed by scope, and a scope it has not seen is seeded from the
committed defaults rather than starting empty:

```python
self._by_scope: dict[str, dict[str, TrackedAthlete]] = {...}
```

## What actually has to change

1. **Give `resolve_scope` a real identity.** A first-party cookie holding a random id is
   enough — no accounts, no email, no password. Set it on first request if absent. The
   function signature already accepts a caller-supplied value, so the API handlers do not
   change.

2. **Persist edits.** Runtime roster changes currently live in memory, which is fine when
   the canonical list is committed to git and every supporter shares it. Per-user rosters
   are not in git, so they need somewhere to live. Object storage keyed by scope id is the
   lightest option that keeps the app stateless and multi-machine safe; a database is
   overkill for a few rows per user.

3. **Decide what a new visitor sees.** Seeding from the committed defaults is right for a
   team event and wrong for Ironman, where a new supporter wants an empty list and a search
   box. Suggest making that a config flag (`GAPIQ_SEED_NEW_SCOPES`) rather than a code
   change, because it differs per event rather than per deployment.

## What deliberately does not change

**The poller stays global.** It sweeps the whole race regardless of who is watching, so
adding supporters costs no extra upstream requests. Per-user rosters must not become
per-user polling — that would turn a fixed request budget into one that grows with
popularity, on a service we do not own.

The consequence is that the poller needs the *union* of all tracked athletes, not one
scope's worth. `RosterStore.list_slugs_in_use` currently takes a scope; it will need a
variant that spans every scope.

## What this is not

Not authentication. A cookie-scoped roster keeps supporters out of each other's lists; it
does not protect anything. If the roster ever needs to be private, that is a separate piece
of work and should be treated as such.
