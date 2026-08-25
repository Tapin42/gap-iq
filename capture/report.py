"""Turn a captured frame corpus into findings a human (or an agent) can act on.

The corpus alone is archaeology. This answers the specific questions that could not be
settled from a finished race, and states plainly which remain unanswered -- because
"we did not observe it" and "it does not happen" are very different conclusions.
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from capture.harness import FRAMES_DIR, MANIFEST_NAME

log = logging.getLogger("capture.report")

UNKNOWN = "not observed"


@dataclass
class Findings:
    edition: str = ""
    frames: int = 0
    first_capture_iso: str = ""
    last_capture_iso: str = ""
    stages_seen: list[str] = field(default_factory=list)
    refresh_wait_values_ms: list[int] = field(default_factory=list)

    # The three questions a finished race could not answer.
    ranked_then_withdrawn: list[dict[str, Any]] = field(default_factory=list)
    checkpoint_recomputes_live: dict[str, Any] = field(default_factory=dict)
    in_race_stage: str = UNKNOWN

    # Anomalies worth knowing about before race day.
    revised_times: list[dict[str, Any]] = field(default_factory=list)
    row_count_reversals: list[dict[str, Any]] = field(default_factory=list)
    checkpoint_id_drift: list[dict[str, Any]] = field(default_factory=list)
    order_label_mismatches: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _read_manifest(root: Path) -> list[dict[str, Any]]:
    path = root / MANIFEST_NAME
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def _load_frame(root: Path, record: dict[str, Any]) -> dict[str, Any] | None:
    path = root / record["path"]
    if not path.exists():
        # Try the bare frames dir in case the corpus was moved.
        path = root / FRAMES_DIR / Path(record["path"]).name
        if not path.exists():
            return None
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def _rows(payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    table = payload.get("table")
    rows = table.get("rows") if isinstance(table, dict) else None
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and not row.get("separator"):
                yield row


def _athlete_id(row: dict[str, Any]) -> str:
    target = row.get("target")
    if isinstance(target, dict) and target.get("slug"):
        return str(target["slug"])
    name = row.get("name")
    if isinstance(name, dict):
        return str(name.get("text") or "")
    return str(name or "")


def _time_text(row: dict[str, Any]) -> str:
    value = row.get("time.main")
    if isinstance(value, dict):
        return str(value.get("text") or "")
    return str(value or "")


def _is_ranked(row: dict[str, Any]) -> bool:
    return row.get("rank.main") is not None and bool(_time_text(row))


def analyse(root: Path, *, edition: str = "") -> Findings:
    records = _read_manifest(root)
    findings = Findings(edition=edition, frames=len(records))
    if not records:
        findings.errors.append("no frames found; the capture produced nothing")
        return findings

    records.sort(key=lambda item: item.get("captured_at", 0))
    findings.first_capture_iso = records[0].get("captured_at_iso", "")
    findings.last_capture_iso = records[-1].get("captured_at_iso", "")
    findings.stages_seen = sorted({r["stage"] for r in records if r.get("stage")})
    findings.refresh_wait_values_ms = sorted(
        {r["refresh_wait_ms"] for r in records if r.get("refresh_wait_ms")}
    )

    # A stage other than the pre-registration and completed states is the in-race value.
    in_race = [s for s in findings.stages_seen if s not in {"reg", "done"}]
    if in_race:
        findings.in_race_stage = ", ".join(in_race)

    # Track per (list, checkpoint) how the field evolved.
    ranked_seen: dict[tuple[str, str], dict[str, str]] = defaultdict(dict)
    withdrawn_seen: dict[str, str] = {}
    counts: dict[tuple[str, str], list[tuple[float, int]]] = defaultdict(list)
    labels: dict[str, set[str]] = defaultdict(set)

    for record in records:
        if record.get("task") != "ranking":
            continue
        payload = _load_frame(root, record)
        if payload is None:
            findings.errors.append(f"missing frame file: {record.get('path')}")
            continue

        key = (record.get("list_slug", ""), record.get("order", ""))
        counts[key].append((record.get("captured_at", 0.0), record.get("ranked_count", 0)))

        if record.get("order"):
            labels[record["order"]].add(record.get("applied_label") or "")
            expected = (record.get("note") or "").replace("expected label=", "").strip()
            applied = record.get("applied_label")
            if expected and applied and expected != applied:
                findings.order_label_mismatches.append(
                    {"order": record["order"], "expected": expected, "applied": applied}
                )

        for row in _rows(payload):
            athlete = _athlete_id(row)
            if not athlete:
                continue
            if _is_ranked(row):
                previous = ranked_seen[key].get(athlete)
                current = _time_text(row)
                if previous and previous != current:
                    findings.revised_times.append(
                        {
                            "athlete": athlete,
                            "list": key[0],
                            "checkpoint": key[1],
                            "was": previous,
                            "now": current,
                            "at": record.get("captured_at_iso"),
                        }
                    )
                ranked_seen[key][athlete] = current
            else:
                withdrawn_seen.setdefault(athlete, record.get("captured_at_iso", ""))

    # Question 1: was anyone ranked at a checkpoint and later shown as withdrawn?
    for (list_slug, order), athletes in ranked_seen.items():
        for athlete in athletes:
            if athlete in withdrawn_seen:
                findings.ranked_then_withdrawn.append(
                    {
                        "athlete": athlete,
                        "list": list_slug,
                        "checkpoint": order,
                        "withdrawn_first_seen": withdrawn_seen[athlete],
                    }
                )

    # Question 2: does a checkpoint ordering recompute as the race progresses?
    growing = [
        {"list": key[0], "checkpoint": key[1], "ranked": [c for _, c in series]}
        for key, series in counts.items()
        if key[1] and len({c for _, c in series}) > 1
    ]
    findings.checkpoint_recomputes_live = {
        "answer": "yes" if growing else UNKNOWN,
        "evidence": growing[:20],
        "checkpoints_observed": len([k for k in counts if k[1]]),
    }

    # Row counts should not fall as the course progresses within a single pass; where they
    # do, a count-based frontier heuristic would be wrong.
    for list_slug in {key[0] for key in counts}:
        series = [
            (key[1], max(c for _, c in values))
            for key, values in counts.items()
            if key[0] == list_slug and key[1]
        ]
        for (first_cp, first_count), (second_cp, second_count) in zip(series, series[1:]):
            if second_count > first_count:
                findings.row_count_reversals.append(
                    {
                        "list": list_slug,
                        "from": first_cp,
                        "to": second_cp,
                        "from_count": first_count,
                        "to_count": second_count,
                    }
                )

    for order, seen in labels.items():
        real = {value for value in seen if value}
        if len(real) > 1:
            findings.checkpoint_id_drift.append({"order": order, "labels": sorted(real)})

    return findings


def render_markdown(findings: Findings) -> str:
    def answered(value: str) -> str:
        return "**" + value + "**" if value != UNKNOWN else f"_{value}_"

    lines = [
        f"# Capture report — {findings.edition or 'unknown edition'}",
        "",
        f"- Frames: **{findings.frames}**",
        f"- Window: {findings.first_capture_iso or '?'} → {findings.last_capture_iso or '?'}",
        f"- Stages observed: {', '.join(findings.stages_seen) or '_none_'}",
        f"- `refreshwait` values (ms): {findings.refresh_wait_values_ms or '_none_'}",
        "",
        "## The three questions a finished race could not answer",
        "",
        "### 1. Do athletes appear ranked at a checkpoint and later show as withdrawn?",
        "",
    ]

    if findings.ranked_then_withdrawn:
        lines += [
            f"**Yes — {len(findings.ranked_then_withdrawn)} observed.** This is the case a completed",
            "race cannot show, because withdrawal is applied retroactively to every earlier",
            "checkpoint. These frames are the fixtures for that behaviour.",
            "",
            "| athlete | list | checkpoint | withdrawn first seen |",
            "| --- | --- | --- | --- |",
        ]
        for item in findings.ranked_then_withdrawn[:15]:
            lines.append(
                f"| {item['athlete']} | {item['list']} | {item['checkpoint']} | {item['withdrawn_first_seen']} |"
            )
    else:
        lines += [
            "_Not observed._ Either nobody withdrew mid-capture, or withdrawal is applied",
            "immediately everywhere. Do not treat this as proof of the latter.",
        ]

    lines += [
        "",
        "### 2. Does `order=split-<id>` recompute during the race?",
        "",
        f"Answer: {answered(findings.checkpoint_recomputes_live.get('answer', UNKNOWN))} "
        f"({findings.checkpoint_recomputes_live.get('checkpoints_observed', 0)} checkpoints observed)",
        "",
    ]
    for item in findings.checkpoint_recomputes_live.get("evidence", [])[:10]:
        lines.append(f"- `{item['list']}` / `{item['checkpoint']}`: ranked counts {item['ranked']}")

    lines += [
        "",
        "### 3. What is the in-race `stage` value?",
        "",
        f"Answer: {answered(findings.in_race_stage)}",
        "",
        "## Anomalies",
        "",
    ]

    sections = [
        (
            "Revised times",
            findings.revised_times,
            "A time changed for an athlete at a checkpoint after first being published. "
            "Any cached or derived value has to tolerate this.",
        ),
        (
            "Row-count reversals along the course",
            findings.row_count_reversals,
            "A later checkpoint reported more finishers than an earlier one, which breaks "
            "any attempt to infer an athlete's progress from row counts.",
        ),
        (
            "Checkpoint id drift",
            findings.checkpoint_id_drift,
            "The same `split-` id resolved to more than one label. This is the failure the "
            "label-verifying order guard exists to catch.",
        ),
        (
            "Order label mismatches",
            findings.order_label_mismatches,
            "The server applied a different checkpoint than the one requested.",
        ),
    ]
    for title, items, explanation in sections:
        lines += [f"### {title}", ""]
        if items:
            lines += [explanation, "", "```json", json.dumps(items[:10], indent=1), "```", ""]
        else:
            lines += ["_None observed._", ""]

    if findings.errors:
        lines += ["## Capture errors", ""]
        lines += [f"- {message}" for message in findings.errors[:20]]
        lines.append("")

    lines += [
        "## What to do with this",
        "",
        "1. Read the answers above against `docs/RUNBOOK.md` → *Resuming after capture*.",
        "2. Any question still reading _not observed_ stays an open risk for race day.",
        "3. The frames under `frames/` are the replay corpus. Prefer them over the",
        "   completed-race replay, which contains no withdrawals and no revisions.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarise a capture corpus.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--edition", default="")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)
    findings = analyse(args.input, edition=args.edition)

    (args.input / "findings.json").write_text(
        json.dumps(
            {
                key: value
                for key, value in vars(findings).items()
            },
            indent=1,
            default=str,
        )
        + "\n"
    )
    (args.input / "REPORT.md").write_text(render_markdown(findings) + "\n")
    log.info("wrote REPORT.md and findings.json to %s (%s frames)", args.input, findings.frames)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
