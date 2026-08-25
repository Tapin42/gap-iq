"""Record raw upstream responses during a live race.

Runs headless on a schedule. One invocation takes a single pass over the event and writes
only what changed, so a whole race day collapses into a manageable corpus instead of tens
of thousands of near-identical payloads.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from racedata.providers.datasport.client import (
    DatasportBlockedError,
    DatasportClient,
    DatasportError,
)
from racedata.providers.datasport.parse import (
    applied_checkpoint_label,
    checkpoint_catalog,
    contest_lists,
)

log = logging.getLogger("capture")

MANIFEST_NAME = "manifest.jsonl"
FRAMES_DIR = "frames"


@dataclass
class FrameRecord:
    """One stored response."""

    captured_at: float
    captured_at_iso: str
    task: str
    list_slug: str
    order: str
    url: str
    path: str
    body_sha256: str
    stage: str | None
    refresh_wait_ms: int | None
    row_count: int
    ranked_count: int
    withdrawn_count: int
    applied_label: str | None = None
    note: str = ""


@dataclass
class PassSummary:
    started_at: float
    finished_at: float = 0.0
    requests: int = 0
    frames_written: int = 0
    frames_unchanged: int = 0
    errors: list[str] = field(default_factory=list)
    stages: list[str] = field(default_factory=list)


#: Keys that change on every request without the content changing. Left in the stored
#: frame -- they are part of what the server actually sent -- but excluded from the hash,
#: otherwise every pass looks like new data and the corpus grows without carrying any
#: additional information.
VOLATILE_KEYS = frozenset({"refresh", "beacon", "gtag"})


def _canonical(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _canonical(item)
            for key, item in sorted(value.items())
            if key not in VOLATILE_KEYS
        }
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    return value


def _sha(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(_canonical(payload), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _counts(payload: dict) -> tuple[int, int, int]:
    """(rows, ranked, withdrawn) without importing the full parse layer semantics."""
    table = payload.get("table")
    rows = table.get("rows") if isinstance(table, dict) else None
    if not isinstance(rows, list):
        return 0, 0, 0
    ranked = 0
    withdrawn = 0
    for row in rows:
        if not isinstance(row, dict) or row.get("separator"):
            continue
        if row.get("rank.main") is not None and row.get("time.main"):
            ranked += 1
        elif row.get("name"):
            withdrawn += 1
    return len(rows), ranked, withdrawn


class CaptureSession:
    """A single pass over one event, writing changed frames to disk."""

    def __init__(
        self,
        edition: str,
        *,
        output_dir: Path,
        client: DatasportClient | None = None,
        athlete_slugs: tuple[str, ...] = (),
        max_lists: int | None = None,
    ) -> None:
        self.edition = edition
        self.output_dir = output_dir
        self.frames_dir = output_dir / FRAMES_DIR
        self.manifest_path = output_dir / MANIFEST_NAME
        self.client = client or DatasportClient()
        self.athlete_slugs = athlete_slugs
        self.max_lists = max_lists
        self._seen: set[str] = self._load_seen()

    def _load_seen(self) -> set[str]:
        """Hashes already on disk, so reruns and restarts do not duplicate frames."""
        if not self.manifest_path.exists():
            return set()
        seen = set()
        for line in self.manifest_path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                seen.add(json.loads(line)["body_sha256"])
            except (ValueError, KeyError):
                continue
        return seen

    # -- Writing -----------------------------------------------------------------------
    def _store(
        self,
        *,
        task: str,
        payload: dict,
        url: str,
        list_slug: str = "",
        order: str = "",
        note: str = "",
    ) -> bool:
        digest = _sha(payload)
        if digest in self._seen:
            return False
        self._seen.add(digest)

        now = time.time()
        rows, ranked, withdrawn = _counts(payload)
        stem = f"{int(now)}-{task}-{list_slug or 'event'}-{order or 'default'}-{digest[:8]}.json.gz"
        # Nested by task keeps a race-day directory listing navigable.
        relative = Path(task) / stem
        target = self.frames_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(target, "wt", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"))

        record = FrameRecord(
            captured_at=now,
            captured_at_iso=datetime.fromtimestamp(now, timezone.utc).isoformat(),
            task=task,
            list_slug=list_slug,
            order=order,
            url=url,
            path=str(Path(FRAMES_DIR) / relative),
            body_sha256=digest,
            stage=payload.get("stage") if isinstance(payload.get("stage"), str) else None,
            refresh_wait_ms=payload.get("refreshwait") if isinstance(payload.get("refreshwait"), int) else None,
            row_count=rows,
            ranked_count=ranked,
            withdrawn_count=withdrawn,
            applied_label=applied_checkpoint_label(payload),
            note=note,
        )
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with self.manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(record)) + "\n")
        return True

    # -- One pass ----------------------------------------------------------------------
    def run_pass(self) -> PassSummary:
        summary = PassSummary(started_at=time.time())
        before = self.client.request_count

        try:
            lists = self._capture_event_tree(summary)
            for ref in lists[: self.max_lists] if self.max_lists else lists:
                self._capture_list(ref.slug, summary)
            for slug in self.athlete_slugs:
                self._capture_participant(slug, summary)
        except DatasportBlockedError as exc:
            # Terminal and worth surfacing loudly: retrying will not fix a rejected agent.
            summary.errors.append(f"BLOCKED: {exc}")
        except DatasportError as exc:
            summary.errors.append(f"{type(exc).__name__}: {exc}")

        summary.requests = self.client.request_count - before
        summary.finished_at = time.time()
        return summary

    def _capture_event_tree(self, summary: PassSummary):
        refs = []
        for task in ("ranking", "startlist"):
            try:
                response = self.client.call(task, edition=self.edition)
            except DatasportBlockedError:
                # Terminal for the whole pass: every subsequent request will be refused
                # too, so abort rather than log the same rejection once per list.
                raise
            except DatasportError as exc:
                summary.errors.append(f"{task}: {exc}")
                continue
            if self._store(task=task, payload=response.payload, url=response.url):
                summary.frames_written += 1
            else:
                summary.frames_unchanged += 1
            if response.stage:
                summary.stages.append(response.stage)
            found = contest_lists(response.payload)
            if found and not refs:
                refs = found
        return refs

    def _capture_list(self, slug: str, summary: PassSummary) -> None:
        """Capture a list's default view plus every checkpoint ordering it offers."""
        try:
            base = self.client.call("ranking", edition=self.edition, slug=slug, count=200, page=1)
        except DatasportBlockedError:
            raise
        except DatasportError as exc:
            summary.errors.append(f"ranking {slug}: {exc}")
            return

        if self._store(task="ranking", payload=base.payload, url=base.url, list_slug=slug):
            summary.frames_written += 1
        else:
            summary.frames_unchanged += 1
        if base.stage:
            summary.stages.append(base.stage)

        for order, label in checkpoint_catalog(base.payload):
            try:
                response = self.client.call(
                    "ranking", edition=self.edition, slug=slug, order=order, count=200, page=1
                )
            except DatasportBlockedError:
                raise
            except DatasportError as exc:
                summary.errors.append(f"ranking {slug} {order}: {exc}")
                continue
            if self._store(
                task="ranking",
                payload=response.payload,
                url=response.url,
                list_slug=slug,
                order=order,
                note=f"expected label={label}",
            ):
                summary.frames_written += 1
            else:
                summary.frames_unchanged += 1

    def _capture_participant(self, slug: str, summary: PassSummary) -> None:
        try:
            response = self.client.call("participant", edition=self.edition, slug=slug)
        except DatasportBlockedError:
            raise
        except DatasportError as exc:
            summary.errors.append(f"participant {slug}: {exc}")
            return
        if self._store(task="participant", payload=response.payload, url=response.url, list_slug=slug):
            summary.frames_written += 1
        else:
            summary.frames_unchanged += 1
        if response.stage:
            summary.stages.append(response.stage)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture live datasport responses.")
    parser.add_argument("--edition", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--athlete", action="append", default=[], dest="athletes")
    parser.add_argument("--max-lists", type=int, default=None)
    parser.add_argument(
        "--passes", type=int, default=1, help="passes to make before exiting"
    )
    parser.add_argument("--interval", type=float, default=30.0)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    session = CaptureSession(
        args.edition,
        output_dir=args.output,
        athlete_slugs=tuple(args.athletes),
        max_lists=args.max_lists,
    )

    worst = 0
    for index in range(args.passes):
        summary = session.run_pass()
        log.info(
            "pass %s/%s: %s requests, %s new frames, %s unchanged, stages=%s, errors=%s",
            index + 1,
            args.passes,
            summary.requests,
            summary.frames_written,
            summary.frames_unchanged,
            sorted(set(summary.stages)) or "-",
            len(summary.errors),
        )
        for message in summary.errors:
            log.warning("  %s", message)
        # A pass that only hit errors is a failure; one that captured nothing new is not.
        if summary.errors and summary.frames_written == 0:
            worst = 1
        if index + 1 < args.passes:
            time.sleep(args.interval)
    return worst


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
