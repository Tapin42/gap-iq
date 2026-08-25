"""Process-local runtime state.

Deliberately in-memory. One upstream sweep returns *every* checkpoint at once, so the
trend baseline is a different checkpoint rather than a different point in time -- there is
no history to persist. That also removes a subtle correctness trap: because the current
and baseline checkpoints come from the same sweep, an athlete who is retroactively erased
upstream (which happens the moment a DNF is recorded) disappears from both consistently
and cannot manufacture a phantom change of neighbour.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SweepResult:
    """Everything one full sweep of the race produced."""

    started_at: float
    finished_at: float
    # division id -> checkpoint id -> provider standings object
    standings: dict[str, dict[str, Any]] = field(default_factory=dict)
    divisions: dict[str, Any] = field(default_factory=dict)
    checkpoints: dict[str, list[Any]] = field(default_factory=dict)
    roster_progress: dict[str, Any] = field(default_factory=dict)
    request_count: int = 0
    anomalies: list[str] = field(default_factory=list)
    #: Hash of the payload, used to distinguish "we fetched" from "the data changed".
    content_hash: str = ""
    degraded: bool = False
    degraded_reason: str = ""


@dataclass
class PollerHealth:
    """What /health reports. Three separate facts, never collapsed into one number.

    Collapsing them is how a dashboard ends up claiming freshness it does not have: a
    dropped client connection, a dead poller and a frozen upstream are three different
    problems that would otherwise all render as "updated 12s ago".
    """

    started_at: float = field(default_factory=time.time)
    #: Last time we successfully reached upstream, regardless of whether data changed.
    last_contact_at: float | None = None
    #: Last time the payload actually changed.
    last_change_at: float | None = None
    last_error: str | None = None
    last_error_at: float | None = None
    consecutive_failures: int = 0
    sweeps_completed: int = 0
    total_requests: int = 0
    circuit_open: bool = False
    circuit_opened_at: float | None = None
    polling_reason: str = "not started"
    running: bool = False
    restarts: int = 0


class AppState:
    """Thread-safe holder. The poller writes from a worker thread; the API reads from the
    event loop, so every access is guarded."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._latest: SweepResult | None = None
        self.health = PollerHealth()

    @property
    def latest(self) -> SweepResult | None:
        with self._lock:
            return self._latest

    def publish(self, sweep: SweepResult) -> bool:
        """Store a sweep. Returns True when the content changed."""
        with self._lock:
            changed = self._latest is None or self._latest.content_hash != sweep.content_hash
            self._latest = sweep
            self.health.last_contact_at = sweep.finished_at
            if changed:
                self.health.last_change_at = sweep.finished_at
            self.health.sweeps_completed += 1
            self.health.total_requests += sweep.request_count
            self.health.consecutive_failures = 0
            self.health.last_error = None
            return changed

    def record_failure(self, error: str) -> int:
        with self._lock:
            self.health.consecutive_failures += 1
            self.health.last_error = error
            self.health.last_error_at = time.time()
            return self.health.consecutive_failures

    def snapshot_health(self) -> PollerHealth:
        with self._lock:
            # Shallow copy is enough: all fields are scalars.
            return PollerHealth(**vars(self.health))


STATE = AppState()
