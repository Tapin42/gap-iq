# Capture report — triathlon-lausanne-2026

- Frames: **543**
- Window: 2026-08-29T10:47:45.150118+00:00 → 2026-08-29T10:49:33.753314+00:00
- Stages observed: idle
- `refreshwait` values (ms): [3000, 15000]

## The three questions a finished race could not answer

### 1. Do athletes appear ranked at a checkpoint and later show as withdrawn?

_Not observed._ Either nobody withdrew mid-capture, or withdrawal is applied
immediately everywhere. Do not treat this as proof of the latter.

### 2. Does `order=split-<id>` recompute during the race?

Answer: _not observed_ (478 checkpoints observed)


### 3. What is the in-race `stage` value?

Answer: **idle**

## Anomalies

### Revised times

_None observed._

### Row-count reversals along the course

_None observed._

### Checkpoint id drift

_None observed._

### Order label mismatches

_None observed._

## What to do with this

1. Read the answers above against `docs/RUNBOOK.md` → *Resuming after capture*.
2. Any question still reading _not observed_ stays an open risk for race day.
3. The frames under `frames/` are the replay corpus. Prefer them over the
   completed-race replay, which contains no withdrawals and no revisions.

