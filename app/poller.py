"""The upstream poller: one supervised loop that sweeps the whole race.

Three decisions worth stating, because each replaced something more complicated:

**It sweeps everything, every time.** No tiered cadence, no per-athlete frontier detection.
Measured against the real API, every checkpoint of a division fetches in about 1.6 seconds
at modest concurrency, and a whole event is roughly 90 requests in a few seconds. Knowing
where everyone is turns out to be cheaper than working out where to look -- and it deletes
the frontier-detection problem rather than solving it.

**It is supervised.** `racedata` is synchronous, so the sweep runs in a worker thread; and
an unhandled exception in a bare asyncio task is *swallowed*, leaving the API cheerfully
serving hours-old rows with no outward sign. The loop therefore catches, counts, reports and
restarts.

**It stops rather than hammering.** After enough consecutive failures the breaker opens: the
app serves its last known data clearly labelled as stale and stops spending requests and
money on a wall.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from racedata.core.models import Race
from racedata.core.standings import Checkpoint, CheckpointStandings, Division
from racedata.providers.datasport.client import DatasportBlockedError, DatasportError
from racedata.providers.datasport.service import DatasportProvider

from app.config import Settings, get_settings
from app.roster import RosterStore, get_roster_store
from app.state import STATE, AppState, SweepResult

log = logging.getLogger("gapiq.poller")


@dataclass
class Ladders:
    """Standings for every division we track, keyed by list slug then checkpoint id."""

    by_list: dict[str, list[CheckpointStandings]]
    checkpoints: dict[str, list[Checkpoint]]


def _hash_ladders(ladders: dict[str, list[CheckpointStandings]]) -> str:
    """Content hash used to tell "we fetched" apart from "the data changed"."""
    digest = hashlib.sha256()
    for slug in sorted(ladders):
        for standings in ladders[slug]:
            digest.update(slug.encode())
            digest.update(standings.checkpoint.id.encode())
            for entry in standings.entries:
                digest.update(entry.athlete.profile_id.encode())
                digest.update(str(entry.clock_tenths).encode())
    return digest.hexdigest()


class Sweeper:
    """Performs one synchronous pass over the event."""

    def __init__(
        self,
        settings: Settings,
        roster: RosterStore,
        provider: DatasportProvider | None = None,
    ) -> None:
        self.settings = settings
        self.roster = roster
        self.provider = provider or DatasportProvider(
            excluded_checkpoint_labels=roster.document.excluded_checkpoint_labels
        )
        self.race = Race(
            event_key=settings.edition,
            display_name=settings.event_label,
            provider=settings.provider,
        )
        self._divisions: list[Division] | None = None
        self._checkpoints: dict[str, list[Checkpoint]] = {}

    # -- Cached metadata ---------------------------------------------------------------
    def divisions(self) -> list[Division]:
        if self._divisions is None:
            self._divisions = self.provider.list_divisions(self.race)
        return self._divisions

    def checkpoints_for(self, slug: str) -> list[Checkpoint]:
        """Checkpoint ladder for a list.

        Cached for the process lifetime: a course does not change mid-race, and re-deriving
        it every 30 seconds would double the request budget for no benefit.
        """
        if slug not in self._checkpoints:
            division = Division(id=slug, label=slug)
            self._checkpoints[slug] = self.provider.list_checkpoints(self.race, division)
        return self._checkpoints[slug]

    # -- The sweep ---------------------------------------------------------------------
    def sweep(self) -> SweepResult:
        started = time.time()
        before = self.provider.client.request_count
        anomalies: list[str] = []

        gender_slugs = self.roster.list_slugs_in_use()
        agegroup_slugs = frozenset(
            athlete.agegroup_list_slug
            for athlete in self.roster.list_athletes()
            if athlete.agegroup_list_slug
        )

        ladders: dict[str, list[CheckpointStandings]] = {}
        checkpoints_out: dict[str, list[Checkpoint]] = {}

        for slug in sorted(gender_slugs):
            division = Division(id=slug, label=slug)
            try:
                checkpoints = self.checkpoints_for(slug)
            except DatasportError as exc:
                anomalies.append(f"checkpoints for {slug}: {exc}")
                continue
            checkpoints_out[slug] = checkpoints

            usable = [cp for cp in checkpoints if cp.usable_for_gaps]
            gender_ladder: list[CheckpointStandings] = []
            group_ladders: dict[str, list[CheckpointStandings]] = {
                group: [] for group in agegroup_slugs
            }

            for checkpoint in usable:
                try:
                    overall, groups = self.provider.fetch_standings_bundle(
                        self.race, division, checkpoint, agegroup_slugs
                    )
                except DatasportBlockedError:
                    raise
                except DatasportError as exc:
                    anomalies.append(f"{slug}/{checkpoint.id}: {exc}")
                    continue
                gender_ladder.append(overall)
                for group, standings in groups.items():
                    if standings.entries:
                        group_ladders[group].append(standings)

            ladders[slug] = gender_ladder
            for group, rungs in group_ladders.items():
                if rungs:
                    ladders[group] = rungs
                    checkpoints_out[group] = usable

        roster_progress: dict[str, object] = {}
        try:
            entries, missing = self.provider.fetch_favorites(
                self.race, self.roster.favorite_ids()
            )
            roster_progress = {entry.athlete.profile_id: entry for entry in entries}
            if missing:
                # Silently dropped ids would otherwise mean rendering 22 of 23 athletes
                # with no indication anything was lost.
                anomalies.append(
                    f"favorites did not return {len(missing)} requested athlete(s): {missing}"
                )
        except DatasportError as exc:
            anomalies.append(f"favorites: {exc}")

        finished = time.time()
        return SweepResult(
            started_at=started,
            finished_at=finished,
            standings={slug: {s.checkpoint.id: s for s in rungs} for slug, rungs in ladders.items()},
            divisions={d.id: d for d in (self._divisions or [])},
            checkpoints=checkpoints_out,
            roster_progress=roster_progress,
            request_count=self.provider.client.request_count - before,
            anomalies=anomalies,
            content_hash=_hash_ladders(ladders),
        )


class PollerSupervisor:
    """Owns the sweep loop, the circuit breaker and the liveness ping."""

    def __init__(
        self,
        settings: Settings | None = None,
        roster: RosterStore | None = None,
        state: AppState | None = None,
        sweeper: Sweeper | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.roster = roster or get_roster_store(self.settings)
        self.state = state or STATE
        self._sweeper = sweeper
        self._task: asyncio.Task | None = None
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="sweep")
        self._stop = asyncio.Event()

    @property
    def sweeper(self) -> Sweeper:
        if self._sweeper is None:
            self._sweeper = Sweeper(self.settings, self.roster)
        return self._sweeper

    def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._supervise(), name="poller-supervisor")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
        self._executor.shutdown(wait=False)

    async def _supervise(self) -> None:
        """Restart the loop if it dies.

        Without this an unhandled exception would terminate polling silently while the API
        kept answering with stale data -- the exact failure mode this app must not have.
        """
        while not self._stop.is_set():
            try:
                await self._loop()
                return
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                self.state.health.restarts += 1
                log.exception("poller loop crashed; restarting (restart #%s)", self.state.health.restarts)
                await asyncio.sleep(5.0)

    async def _loop(self) -> None:
        self.state.health.running = True
        try:
            while not self._stop.is_set():
                allowed, reason = self.settings.polling_allowed()
                self.state.health.polling_reason = reason

                if self.state.health.circuit_open:
                    log.warning("circuit breaker open; not polling. %s", self.state.health.last_error)
                    await self._sleep_with_jitter(self.settings.sweep_interval_seconds * 4)
                    continue

                if not allowed:
                    # Idle by design. Checked often enough to wake promptly when a window
                    # opens, but costs no upstream requests.
                    await self._sleep_with_jitter(min(60.0, self.settings.sweep_interval_seconds * 2))
                    continue

                await self._run_once()
                await self._sleep_with_jitter(self.settings.sweep_interval_seconds)
        finally:
            self.state.health.running = False

    async def _run_once(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            sweep = await loop.run_in_executor(self._executor, self.sweeper.sweep)
        except DatasportBlockedError as exc:
            # Not transient: every later request will be refused identically. Open the
            # breaker immediately rather than burning the retry budget.
            self.state.record_failure(f"blocked by upstream: {exc}")
            self._open_circuit("upstream refused our requests (Cloudflare)")
            return
        except Exception as exc:  # noqa: BLE001
            failures = self.state.record_failure(f"{type(exc).__name__}: {exc}")
            log.warning("sweep failed (%s consecutive): %s", failures, exc)
            if failures >= self.settings.circuit_breaker_failures:
                self._open_circuit(f"{failures} consecutive sweep failures")
            return

        changed = self.state.publish(sweep)
        for anomaly in sweep.anomalies:
            log.warning("sweep anomaly: %s", anomaly)
        log.info(
            "sweep ok in %.1fs: %s requests, %s divisions, changed=%s",
            sweep.finished_at - sweep.started_at,
            sweep.request_count,
            len(sweep.standings),
            changed,
        )
        await self._ping_healthcheck()

    def _open_circuit(self, reason: str) -> None:
        self.state.health.circuit_open = True
        self.state.health.circuit_opened_at = time.time()
        log.error(
            "circuit breaker opened: %s. Serving last known data, clearly marked stale, "
            "and no longer spending requests.",
            reason,
        )

    def reset_circuit(self) -> None:
        """Manual recovery, used by the force-refresh control."""
        self.state.health.circuit_open = False
        self.state.health.circuit_opened_at = None
        self.state.health.consecutive_failures = 0

    async def refresh_now(self) -> bool:
        """Run one sweep immediately, regardless of window or breaker state.

        This is the supporter-facing lever, so it deliberately ignores both: someone
        pressing refresh has more context than our schedule does.
        """
        self.reset_circuit()
        await self._run_once()
        return not self.state.health.circuit_open

    async def _ping_healthcheck(self) -> None:
        """Tell an external monitor we are alive.

        Outward, not inward: an alerter running inside this process cannot fire when this
        process is what failed, so liveness is asserted to something else and the *absence*
        of a ping is what raises the alarm.
        """
        url = self.settings.healthcheck_ping_url.strip()
        if not url:
            return
        try:
            import requests

            await asyncio.get_running_loop().run_in_executor(
                self._executor, lambda: requests.get(url, timeout=5)
            )
        except Exception as exc:  # noqa: BLE001
            # Never let monitoring failure affect the race data path.
            log.debug("healthcheck ping failed: %s", exc)

    async def _sleep_with_jitter(self, seconds: float) -> None:
        # Jitter keeps two machines from synchronising into a request spike.
        delay = seconds * (1.0 + random.uniform(-0.1, 0.1))
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=max(0.5, delay))
        except asyncio.TimeoutError:
            return


_supervisor: PollerSupervisor | None = None


def get_supervisor() -> PollerSupervisor:
    global _supervisor
    if _supervisor is None:
        _supervisor = PollerSupervisor()
    return _supervisor


def reset_supervisor() -> None:
    """Test seam."""
    global _supervisor
    _supervisor = None
