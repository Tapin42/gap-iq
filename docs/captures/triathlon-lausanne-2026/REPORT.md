# Capture report — triathlon-lausanne-2026

- Frames: **1690**
- Window: 2026-08-29T10:47:45.150118+00:00 → 2026-08-30T09:48:02.608086+00:00
- Stages observed: idle, live
- `refreshwait` values (ms): [3000, 15000]

## The three questions a finished race could not answer

### 1. Do athletes appear ranked at a checkpoint and later show as withdrawn?

_Not observed._ Either nobody withdrew mid-capture, or withdrawal is applied
immediately everywhere. Do not treat this as proof of the latter.

### 2. Does `order=split-<id>` recompute during the race?

Answer: **yes** (478 checkpoints observed)

- `femmes-cla` / `split-281`: ranked counts [0, 0, 151, 151, 151, 151]
- `femmes-cla` / `split-282`: ranked counts [0, 0, 150, 150, 150, 150]
- `femmes-cla` / `split-283`: ranked counts [0, 0, 150, 150, 150, 150]
- `femmes-cla` / `split-284`: ranked counts [0, 0, 150, 150, 150, 150]
- `femmes-cla` / `split-285`: ranked counts [0, 0, 150, 150, 150, 150]
- `femmes-cla` / `split-286`: ranked counts [0, 0, 149, 149, 149, 149]
- `femmes-cla` / `split-287`: ranked counts [0, 0, 150, 150, 150, 150]
- `femmes-cla` / `split-288`: ranked counts [0, 0, 147, 148, 148, 148]
- `femmes-cla` / `split-289`: ranked counts [0, 0, 146, 146, 146, 146]
- `femmes-cla` / `split-290`: ranked counts [0, 0, 133, 134, 135, 137]

### 3. What is the in-race `stage` value?

Answer: **idle, live**

## Anomalies

### Revised times

A time changed for an athlete at a checkpoint after first being published. Any cached or derived value has to tolerate this.

```json
[
 {
  "athlete": "mias-philippine",
  "list": "femmes-cla",
  "checkpoint": "",
  "was": "3:12:58,3",
  "now": "3:14:05,0",
  "at": "2026-08-30T09:45:25.767364+00:00"
 },
 {
  "athlete": "bruegger-annick",
  "list": "femmes-cla",
  "checkpoint": "",
  "was": "3:19:10,4",
  "now": "3:20:17,0",
  "at": "2026-08-30T09:45:25.767364+00:00"
 },
 {
  "athlete": "simond-anne",
  "list": "femmes-cla",
  "checkpoint": "",
  "was": "3:19:42,0",
  "now": "3:20:53,6",
  "at": "2026-08-30T09:45:25.767364+00:00"
 },
 {
  "athlete": "zuber-sophie",
  "list": "femmes-cla",
  "checkpoint": "",
  "was": "2:53:03,5",
  "now": "3:12:48,8",
  "at": "2026-08-30T09:45:25.767364+00:00"
 },
 {
  "athlete": "bovino-luana",
  "list": "femmes-cla",
  "checkpoint": "",
  "was": "3:03:12,5",
  "now": "3:23:07,0",
  "at": "2026-08-30T09:45:25.767364+00:00"
 },
 {
  "athlete": "lu-diane",
  "list": "femmes-cla",
  "checkpoint": "",
  "was": "3:01:57,6",
  "now": "3:24:42,3",
  "at": "2026-08-30T09:45:25.767364+00:00"
 },
 {
  "athlete": "favrat-camille",
  "list": "femmes-cla",
  "checkpoint": "",
  "was": "3:18:41,3",
  "now": "3:21:28,8",
  "at": "2026-08-30T09:45:25.767364+00:00"
 },
 {
  "athlete": "mias-philippine",
  "list": "femmes-cla-18-34",
  "checkpoint": "",
  "was": "3:12:58,3",
  "now": "3:14:05,0",
  "at": "2026-08-30T09:45:30.222956+00:00"
 },
 {
  "athlete": "bruegger-annick",
  "list": "femmes-cla-18-34",
  "checkpoint": "",
  "was": "3:19:10,4",
  "now": "3:20:17,0",
  "at": "2026-08-30T09:45:30.222956+00:00"
 },
 {
  "athlete": "favrat-camille",
  "list": "femmes-cla-18-34",
  "checkpoint": "",
  "was": "3:18:41,3",
  "now": "3:21:28,8",
  "at": "2026-08-30T09:45:30.222956+00:00"
 }
]
```

### Row-count reversals along the course

A later checkpoint reported more finishers than an earlier one, which breaks any attempt to infer an athlete's progress from row counts.

```json
[
 {
  "list": "femmes-cla",
  "from": "split-286",
  "to": "split-287",
  "from_count": 149,
  "to_count": 150
 },
 {
  "list": "hommes-cla-35-44",
  "from": "split-281",
  "to": "split-282",
  "from_count": 131,
  "to_count": 132
 },
 {
  "list": "hommes-cla-35-44",
  "from": "split-286",
  "to": "split-287",
  "from_count": 129,
  "to_count": 130
 },
 {
  "list": "hommes-cla-35-44",
  "from": "split-288",
  "to": "split-289",
  "from_count": 129,
  "to_count": 130
 },
 {
  "list": "femmes-cla-18-34",
  "from": "split-286",
  "to": "split-287",
  "from_count": 107,
  "to_count": 108
 },
 {
  "list": "hommes-cla-55-64",
  "from": "split-286",
  "to": "split-287",
  "from_count": 36,
  "to_count": 37
 }
]
```

### Checkpoint id drift

_None observed._

### Order label mismatches

_None observed._

## What to do with this

1. Read the answers above against `docs/RUNBOOK.md` → *Resuming after capture*.
2. Any question still reading _not observed_ stays an open risk for race day.
3. The frames under `frames/` are the replay corpus. Prefer them over the
   completed-race replay, which contains no withdrawals and no revisions.

