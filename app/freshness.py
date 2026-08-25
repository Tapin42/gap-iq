"""The freshness contract.

The most dangerous thing this app could do is imply data is current when it is not. On the
Zofingen bike leg consecutive timing mats are 35-53 minutes apart, so no polling interval
can make a displayed gap younger than the last mat an athlete crossed. A single
"updated 12s ago" label next to a 40-minute-old gap is precisely the failure the whole
project exists to avoid.

Two rules follow, and both are structural rather than cosmetic:

**Send epochs, not prose.** A rendered "12s ago" freezes at whatever the server thought
when it serialised. A phone that locks its screen and wakes an hour later would display it
unchanged and be confidently wrong. The client is given absolute timestamps and computes
ages itself.

**Report three facts, never one.** A dropped client connection, a dead poller and a frozen
upstream are different problems that would otherwise all render identically. Keeping them
separate is what lets the UI say "the race hasn't updated" instead of "everything is fine".
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: How many multiples of the sweep interval may pass before contact counts as broken.
CONTACT_STALE_MULTIPLIER = 4.0

#: An athlete between distant mats is normal, not broken, so athlete freshness gets a
#: generous default. Zofingen's bike leg alone can leave a 53-minute silence.
DEFAULT_ATHLETE_QUIET_SECONDS = 45 * 60


@dataclass(frozen=True)
class Freshness:
    """Three independent facts about how current the displayed data is."""

    #: When the server last successfully reached upstream, whether or not anything changed.
    last_upstream_contact_at: float | None = None
    #: When the payload last actually changed. Upstream can be reachable and static.
    last_data_change_at: float | None = None
    #: When the displayed athlete was last recorded at a timing mat. This is the one that
    #: bounds how current a gap can possibly be.
    athlete_last_seen_at: float | None = None
    #: Elapsed race time at that mat, which is what a supporter reads on a stopwatch.
    athlete_last_seen_checkpoint: str = ""
    #: The next mat we expect, so a quiet period reads as "wait" not "broken".
    next_expected_checkpoint: str = ""

    server_time: float = 0.0
    sweep_interval_seconds: float = 30.0
    polling_allowed: bool = True
    polling_reason: str = ""
    degraded: bool = False
    degraded_reason: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def contact_is_stale(self) -> bool:
        """True when the server has not reached upstream for several sweeps.

        Only meaningful while polling is allowed: silence outside a race window is the
        intended behaviour, not a fault.
        """
        if not self.polling_allowed:
            return False
        if self.last_upstream_contact_at is None:
            return True
        age = self.server_time - self.last_upstream_contact_at
        return age > self.sweep_interval_seconds * CONTACT_STALE_MULTIPLIER

    def as_payload(self) -> dict:
        """Serialise for the client.

        Absolute epochs only -- no pre-rendered ages, so a suspended tab cannot display a
        frozen "12s ago" indefinitely.
        """
        return {
            "server_time": self.server_time,
            "sweep_interval_seconds": self.sweep_interval_seconds,
            "last_upstream_contact_at": self.last_upstream_contact_at,
            "last_data_change_at": self.last_data_change_at,
            "athlete_last_seen_at": self.athlete_last_seen_at,
            "athlete_last_seen_checkpoint": self.athlete_last_seen_checkpoint,
            "next_expected_checkpoint": self.next_expected_checkpoint,
            "contact_is_stale": self.contact_is_stale,
            "polling": {"allowed": self.polling_allowed, "reason": self.polling_reason},
            "degraded": self.degraded,
            "degraded_reason": self.degraded_reason,
            "notes": list(self.notes),
        }
