# Gap IQ

A mobile-first live race-tracking dashboard. For a tracked athlete it answers the only
three questions a supporter standing on a course actually has:

- **Where am I?** — position in the division, in the largest type on the screen.
- **Who is ahead, and am I catching them?**
- **Who is behind, and are they catching me?**

Built for the Powerman Zofingen long-distance duathlon world championships, but the data
layer is provider-agnostic: race timing comes from the
[`racedata`](https://github.com/Tapin42/racedata) library, so the same dashboard works
against datasport.com, RTRT.me (Ironman, 70.3, USA Triathlon) or any other backend with a
`StandingsProvider` implementation.

## The display

```
┌──────────────────────────────────────────┐
│  #372 USA  Cobb            ▲ 1:04  ← ahead, colour = is the gap closing?
├──────────────────────────────────────────┤
│                                          │
│            3. Navratil                   │  ← position + last name
│                                          │
├──────────────────────────────────────────┤
│  #375 USA  Weiss           ▼ 0:22  ← behind
└──────────────────────────────────────────┘
   Bike – Rothrist 3 · 12 min ago
```

Colour polarity is inverted between the two rows so that **green always means good for
your athlete**: for the racer ahead, a closing gap is green; for the racer behind, a
closing gap is red. Every trend also carries an arrow glyph, so the display survives
red-green colour blindness and direct sunlight.

## Two things this app refuses to do

**It will not lie about freshness.** On the Zofingen bike leg, consecutive timing mats are
35–53 minutes apart, so no polling interval can make a displayed gap younger than the last
mat an athlete crossed. An "updated 12s ago" label next to a 40-minute-old gap is the exact
failure this app exists to prevent. So the primary indicator is **checkpoint age**, not
fetch age, and the API reports three separate facts — last upstream contact, last data
change, and when the athlete was last seen at a mat.

**It will not present a gap it cannot stand behind.** Two of Zofingen's mats are crossed
multiple times per athlete (run 2 laps through the transition area), and the upstream API
returns each athlete's *last* crossing — so a standings list there silently compares one
athlete's lap 2 against another's lap 4. Those mats are detected and excluded rather than
displayed as if they were sound.

## Running locally

Requires Python 3.11+ and Node 22+.

```bash
# Backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Frontend
cd web && npm install && cd ..

# Terminal 1 -- API on an uncommon port
GAPIQ_IGNORE_ACTIVE_WINDOWS=true uvicorn app.main:app --reload --port 8477

# Terminal 2 -- SPA dev server, proxies /api to the backend
cd web && npm run dev
```

Then open the printed Vite URL. `GAPIQ_IGNORE_ACTIVE_WINDOWS=true` is needed because the
poller is otherwise idle outside the configured race windows.

### Without a network

The replay simulator serves a real completed race through a virtual clock, so the whole UI
works offline and deterministically:

```bash
GAPIQ_IGNORE_ACTIVE_WINDOWS=true GAPIQ_PROVIDER=replay \
  uvicorn app.main:app --reload --port 8477
```

## Tests

```bash
pytest                    # unit + fixture tests, no network
pytest -m live            # hits live upstream APIs; needs egress
cd web && npm test        # component tests
cd web && npx playwright test   # end-to-end against the replay simulator
```

## Deployment

One fly.io app, two stateless machines in `fra`, no volume. See
[docs/RUNBOOK.md](docs/RUNBOOK.md) for the race-morning smoke check, the alerting setup,
the cost kill switch, and the post-race teardown.

## Documentation

- [docs/RUNBOOK.md](docs/RUNBOOK.md) — operations, race morning, incident response
- [docs/DATASPORT.md](docs/DATASPORT.md) — the upstream API, and the verified traps in it
- [docs/per-user-roster.md](docs/per-user-roster.md) — how to move from one shared roster
  to per-supporter rosters
- `docs/captures/` — findings reports recorded from live races
