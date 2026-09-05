# Capture report — powerman-world-championships-zofingen-2026

- Frames: **3711**
- Window: 2026-08-25T18:36:00.954617+00:00 → 2026-09-05T15:19:45.987157+00:00
- Stages observed: live, reg
- `refreshwait` values (ms): [3000, 15000, 120000]

## The three questions a finished race could not answer

### 1. Do athletes appear ranked at a checkpoint and later show as withdrawn?

_Not observed._ Either nobody withdrew mid-capture, or withdrawal is applied
immediately everywhere. Do not treat this as proof of the latter.

### 2. Does `order=split-<id>` recompute during the race?

Answer: **yes** (1588 checkpoints observed)

- `zofingen-5000-jugend-weiblich` / `split-1135`: ranked counts [0, 0, 0, 1]
- `zofingen-5000-jugend-weiblich` / `split-1137`: ranked counts [0, 0, 0, 1]
- `zofingen-5000-jugend-weiblich` / `split-1138`: ranked counts [0, 0, 0, 1]
- `zofingen-5000-jugend-weiblich-u16-908894` / `split-1135`: ranked counts [0, 0, 0, 1]
- `zofingen-5000-jugend-weiblich-u16-908894` / `split-1137`: ranked counts [0, 0, 0, 1]
- `zofingen-5000-jugend-weiblich-u16-908894` / `split-1138`: ranked counts [0, 0, 0, 1]
- `zofingen-5000-women` / `split-1144`: ranked counts [0, 0, 0, 0, 27]
- `zofingen-5000-women` / `split-1151`: ranked counts [0, 0, 0, 0, 27]
- `zofingen-5000-women` / `split-1153`: ranked counts [0, 0, 0, 0, 27]
- `zofingen-5000-women` / `split-1155`: ranked counts [0, 0, 0, 0, 27]

### 3. What is the in-race `stage` value?

Answer: **live**

## Anomalies

### Revised times

A time changed for an athlete at a checkpoint after first being published. Any cached or derived value has to tolerate this.

```json
[
 {
  "athlete": "fajardo-manuel",
  "list": "zofingen-5000-men",
  "checkpoint": "",
  "was": "26:53,9",
  "now": "34:17,0",
  "at": "2026-09-05T15:19:41.748185+00:00"
 },
 {
  "athlete": "fajardo-manuel",
  "list": "zofingen-5000-maenner-m40-908906",
  "checkpoint": "",
  "was": "26:53,9",
  "now": "34:17,0",
  "at": "2026-09-05T15:19:45.122387+00:00"
 }
]
```

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

