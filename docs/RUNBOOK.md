# Gap IQ runbook

Written for whoever is holding the phone, not for whoever wrote the app. On race day the
author is competing and unreachable.

---

## Race-morning smoke check

Run this before the gun. Every check below has a verified failure mode that returns
**HTTP 200**, so "it didn't error" is not evidence that it worked.

```bash
# 1. The app is up and polling for the right event.
curl -s https://gap-iq.fly.dev/health | jq '{status, event, polling, freshness}'
```

Expect `status` of `ok` or `idle`. **`idle` is healthy outside a race window** — the reason
field says which. `circuit_open` means the poller has given up and needs attention.

```bash
# 2. The edition still resolves and divisions are discoverable.
python -m scripts.preflight --edition powerman-world-championships-zofingen-2026
```

That script asserts, in order:

| Check | Why it exists |
| --- | --- |
| Edition resolves | A renamed edition slug returns 200 with an empty tree, not a 404 |
| Divisions non-empty | `task=ranking` returns nothing until results exist; the start list is the pre-race source |
| Every roster `favorite_id` resolves | Unknown ids are dropped silently, so 23 requested can render as 22 |
| Checkpoint ids resolve to expected labels | An id can stay valid but be reassigned between editions |
| Course order is monotonic | Guards against upstream reordering mats |
| Excluded mats are still exactly the expected ones | The multi-crossing set is event-specific |

```bash
# 3. One athlete end to end.
curl -s https://gap-iq.fly.dev/api/athlete/navratil-joe | jq '{position, field_size, checkpoint, ahead, behind}'
```

Before the start this correctly returns `has_data: false`. That is the expected pre-race
state, not a fault.

---

## What the display is telling you

**Green always means good for the tracked athlete.** The polarity is deliberately inverted
between the two rows: closing on the racer ahead is good, the racer behind closing on you is
not. The arrow is about the *number* — down means the gap is shrinking — so colour and arrow
carry different information.

| On screen | Meaning |
| --- | --- |
| `NEW` badge | A different athlete now holds that position. The gap is still a real comparison |
| `LEVEL` | Identical times |
| "Gap is as of *earlier mat*" | One of the two has not been recorded at the current mat. Not current, and says so |
| "Moved up — #341 is no longer on course" | A place gained because someone withdrew, not because of a pass |
| "no trend yet" | Nothing far enough back to compare against |
| Earlier-checkpoint banner | You are in history. One tap on **Back to live** returns |

**Freshness leads with the checkpoint, not the fetch.** On the bike leg consecutive mats are
35–53 minutes apart, so a gap can legitimately be 40 minutes old while the app is perfectly
healthy. "Checked 12s ago" is about the network; the checkpoint line is about the race.

---

## Something looks wrong

### The app is showing old data

Check `/health`:

- `polling.allowed: false` — outside a race window. Set `GAPIQ_IGNORE_ACTIVE_WINDOWS=true`
  or fix `config/windows.json` if the race is genuinely running.
- `circuit_open: true` — the poller stopped after repeated failures, on purpose, so it is
  not spending money on a wall. Press **Refresh** in the app (which resets it) or restart.
- `consecutive_failures` climbing — upstream trouble. The app keeps serving its last known
  data, labelled stale.

### First two things to try

1. **Refresh** in the app header. It forces an immediate sweep and clears the breaker.
2. Restart the machine:

```bash
fly machine restart --app gap-iq
```

### Stop it spending money

```bash
fly secrets set GAPIQ_POLLING_ENABLED=false --app gap-iq   # stop polling, keep serving
fly scale count 0 --app gap-iq                             # stop everything
```

### Handing it to an AI agent

The alert payload and `/health` are written to be pasted directly into an agent session.
Include:

- the full `/health` JSON,
- `fly logs --app gap-iq | tail -200`,
- this file,
- the relevant capture report under `docs/captures/`.

Useful context to give the agent: the timing API reports several distinct failures with
HTTP 200, so a plausible-looking response is not proof of success. See
[DATASPORT.md](DATASPORT.md).

---

## Alerting

The dead-man's switch is **external**, because an alerter inside this process cannot fire
when this process is what died. The app pings a monitor on every successful sweep; the
monitor raises the alarm when pings stop.

```bash
fly secrets set GAPIQ_HEALTHCHECK_PING_URL="https://hc-ping.com/<uuid>" --app gap-iq
```

Routing lives in the monitor's dashboard, so **changing who gets paged needs no redeploy**.

> **Race-morning checklist item:** `GAPIQ_ALERT_EMAIL` currently points at
> `navratil@gmail.com`, who will be on course. Reassign it to a supporter who can act.

---

## Resuming after a capture

The capture jobs commit their own findings, so a fresh session can pick this up cold.

1. Read `docs/captures/<edition>/REPORT.md`. It answers the three questions a finished race
   could not, and says explicitly when something was **not observed** — which is not the
   same as "does not happen".
2. Check these, which were contingent on live observation:
   - **In-race `stage` value.** `capture/gate.py` treats anything outside `reg`/`done` as
     live. If the real value is something unexpected, confirm the gate still fires.
   - **`refreshwait` mid-race.** Pre-race it is 120000 ms. We poll on our own 30-second
     schedule and treat it as advisory; if it turns out to be much shorter, revisit.
   - **Whether withdrawn athletes appear ranked mid-race.** The gap engine assumes they can,
     and handles their later disappearance. If the report shows a withdrawal *event*, add
     those frames as fixtures.
   - **Multi-crossing mats.** `config/roster.*.json` lists them explicitly. Re-verify with
     `DatasportProvider.detect_multi_crossing_labels` once 2026 has a finisher.
3. `frames/` is the replay corpus, and is better than the completed-race replay: finished
   results contain no withdrawals, no revisions and no outages.

---

## After the race

**Tear down, or this quietly bills forever.** Two `shared-cpu-1x` machines are on the order
of a dollar for the whole race weekend; the real cost risk is leaving them running for
months.

```bash
fly scale count 0 --app gap-iq
# or, when the season is done:
fly apps destroy gap-iq
```

Also disable the capture workflow schedule in `.github/workflows/capture.yml`, or it keeps
waking every five minutes on the configured dates next year.
