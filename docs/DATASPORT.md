# The datasport results API, and the traps in it

Everything below was verified against the live service. The traps matter more than the happy
path, because **this API reports several distinct failures with HTTP 200 and a
plausible-looking body**. "The request succeeded" is not evidence the answer is right.

## Shape

One endpoint; a `task` parameter selects the operation.

```
https://results.datasport.com/api?task=<task>&edition=<slug>&slug=<list-or-athlete>&lang=en
```

| task | Returns |
| --- | --- |
| `ranking` | A contest tree, or one list's standings |
| `startlist` | Entrants, and the contest tree **before results exist** |
| `participant` | One athlete's split table, with a rank at every checkpoint |
| `favorites` | An arbitrary watch list in a single request |

No key, cookie or Referer. Add `order=split-<id>` to re-rank a list **at a checkpoint**,
with `gap` measured to that checkpoint's leader.

## Traps

### A custom User-Agent is mandatory

Default library agents get HTTP 403 with a ~17-byte **plain-text** body. A JSON-first client
raises a decode error and buries the real cause. Retrying does not help.

### Failures that return 200

| Symptom | What actually happened | How we detect it |
| --- | --- | --- |
| Standings look plausible but are in final order | An unknown `order` was **ignored** | The applied `Sorting` value gains `highlight: true` and loses its `apioptions.order`. Verify the label too, since an id can be reassigned |
| Empty-looking list | The list **slug rotated** for this edition | No `table` key at all, versus a present table with zero rows |
| 22 of 23 athletes render | `favorites` **silently dropped** unknown ids | Compare requested ids against returned ones |
| Zero divisions on race morning | `task=ranking` has no contest tree until results exist | Fall back to `task=startlist` |

> The earlier heuristic for the first row — "a correctly applied ordering returns zero
> `split.*` columns" — has a verified false negative. Any list whose default view has no
> split columns (a plain running race, or any checkpoint nobody has reached yet) passes it
> with a completely invalid order.

### Two mats are crossed more than once

Zofingen's second run laps through the transition area, so `Run2 - WZ OUT` is crossed four
times and `Run2 - WZ IN` twice — and a checkpoint query returns each athlete's **last**
crossing. Mid-race that ranks one athlete's second lap against another's fourth. The gaps
are meaningless and look entirely ordinary.

These are excluded from the gap ladder. Detect them from a participant split table
(`detect_multi_crossing_labels`), which is definitive; the field-disagreement heuristic in
`course.py` is only a mid-race backstop, because on finished data every athlete's last
crossing is from the same lap and the mat looks perfectly consistent.

### Course order is *almost* the array order

Across all 29 Zofingen checkpoints there are exactly **two** ordering violations against the
API's array order, and both are the multi-crossing mats above. Exclude those two and the
array order is exactly right. We still derive order from observed times, because that is
self-correcting and generalises to other events.

### Withdrawal is retroactive

Once a DNF is recorded, that athlete is erased from **every earlier checkpoint**. Three
consequences:

- A completed race contains no withdrawal *event* — only a permanent absence. That is why
  the replay simulator is a harness, not ground truth, and why live capture matters.
- An athlete who raced for hours can look identical to one who never started. The withdrawn
  block distinguishes them, but it is **not carried at every checkpoint** — the finish list
  holds only finishers — so the whole ladder must be searched.
- A checkpoint and its trend baseline must come from the **same sweep**. Mixing a fresh
  checkpoint with a stored older one can invent a change of neighbour that never happened.

DNF rows do carry `name`, `bib`, `pictures` and `gap`. What they lack is `rank.main` and
`time.main`, so classify on those.

### Ranks are not a usable index

Real data contains ties and holes: `…66, 67, 67, 69…`. Rank 68 does not exist, so looking
for "my rank minus one" finds nobody and a mid-pack athlete is reported as leading.
Neighbours are keyed on sorted position; provider rank is display only.

### `rank.AGEGROUP` is the final placing, not the placing here

On a split-ordered row its *value* is the athlete's finishing age-group rank, not their rank
at the queried checkpoint. Its `target.slug`, however, is a gift: filtering a gender-list
response by that slug produces correct age-group standings for **every** age group from a
single request. Filtered fields must then be renumbered, or an athlete leading their age
group appears eighth with nobody ahead of them.

### List names are not unique

The elite and paraduathlon contests each expose a `gender` list *and* an `agegroup` list
under byte-identical names, differing only by slug. Any lookup that returns one scope for a
name has to guess, and guesses wrong for every elite athlete. Resolve by slug.

### Times use a decimal comma, and the start mat has no colon

`"7:01:46,5"`, `"12:04,7"`, and the start mat is a bare `"5,6"`. A comma-to-period
substitution over a colon-splitting parser returns `None` for that last one.

Precision is not optional: truncating to whole seconds puts 29% of adjacent-athlete gaps off
by at least half a second across a full field, and flips real trend labels — including cases
where losing ground renders as closing. Times are carried in tenths.

### Paging

`count` caps at **200** server-side whatever you ask for, and ranks continue across pages.
Page-1-only fetching drops the neighbour of anyone at rank 200, 400, … Harmless for
Zofingen's largest list (148) and wrong for Lausanne (532) or Kaprun (2483).

### Other notes

- Athlete records carry **no country**. Nationality comes from the ISO 3166-1 *numeric* code
  in the flag filename (`flags/840.png` → USA). `alttext` is localised. Some athletes have no
  `pictures` key at all, so absent nationality must be displayable.
- Applying an `order` consumes that entry's ordering value, so a checkpoint catalogue built
  from an ordered response **omits the checkpoint it was sorted by**. Build catalogues from
  an unordered fetch.
- `refresh` + `refreshwait` give a conditional fetch: pass the token back and get ~100 bytes
  of `{"unchanged": true}`. `refreshwait` is advisory and drifts (120000 ms at Zofingen
  pre-race, 15000 at Lausanne).
- `cache-control: max-age=120` does **not** floor a server-side poller: `cf-cache-status` is
  `DYNAMIC`, there is no `ETag`, and requests seconds apart reach origin. A 30-second sweep
  is real.
- Mat misses are routine — about 7% of a real field has at least one hole, one athlete
  missing 12 consecutive checkpoints while still racing. Row counts along the course are
  therefore non-monotonic, which breaks any count-based progress heuristic.
