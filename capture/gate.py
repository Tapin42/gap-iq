"""Decide whether an event is worth polling right now.

The cron is deliberately coarse -- it covers whole days -- because a race that starts late
should still be captured. This narrows it at runtime using the event's own ``stage`` field,
so an idle day costs one request instead of a day of polling.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from racedata.providers.datasport.client import DatasportClient, DatasportError

log = logging.getLogger("capture.gate")

#: Stages worth capturing. ``reg`` is pre-race registration and ``done`` is a finished
#: event whose results no longer change; anything else is either live or unrecognised, and
#: an unrecognised stage is itself a finding worth recording.
SKIP_STAGES = {"done"}

#: Captured even at `reg`, because the pre-race shape is what race morning looks like and
#: we want a baseline to diff the live shape against.
CAPTURE_STAGES = {"reg", "idle", "live", "running"}


def is_active(edition: str, *, client: DatasportClient | None = None) -> tuple[bool, str]:
    client = client or DatasportClient()
    try:
        response = client.call("ranking", edition=edition)
    except DatasportError as exc:
        # Fail open: if we cannot tell, capture. A wasted pass is cheaper than a missed
        # race, and the error itself belongs in the corpus.
        return True, f"could not determine stage ({exc}); capturing anyway"

    stage = response.stage or "unknown"
    if stage in SKIP_STAGES:
        return False, f"stage={stage}; results are final"
    return True, f"stage={stage}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gate a capture run.")
    parser.add_argument("--edition", required=True)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    active, reason = is_active(args.edition)
    log.info("%s: %s -> %s", args.edition, reason, "capture" if active else "skip")

    # Written to GITHUB_OUTPUT by the workflow.
    print(f"active={'true' if active else 'false'}")
    print(f"reason={reason}")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
            handle.write(f"- `{args.edition}`: {reason}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
