"""Runtime configuration for Gap IQ.

Everything race-specific is configuration rather than code, so pointing the app at a
different event -- or a different timing provider -- is an env/config change.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"


@dataclass(frozen=True)
class ActiveWindow:
    """A period during which the poller is allowed to touch upstream APIs.

    Outside every window the app makes no upstream requests at all. This is the primary
    cost control: an idle machine costs machine-time only, not a request budget, and a
    forgotten deployment cannot quietly poll for weeks.
    """

    label: str
    start: datetime
    end: datetime

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment <= self.end


def _parse_window(raw: dict) -> ActiveWindow:
    return ActiveWindow(
        label=str(raw["label"]),
        start=datetime.fromisoformat(raw["start"]),
        end=datetime.fromisoformat(raw["end"]),
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GAPIQ_", env_file=".env", extra="ignore")

    # --- Event targeting -------------------------------------------------------------
    provider: str = "datasport"
    edition: str = "powerman-world-championships-zofingen-2026"
    event_label: str = "Powerman Zofingen 2026"
    roster_file: str = "roster.zofingen-2026.json"

    # --- Polling ---------------------------------------------------------------------
    sweep_interval_seconds: float = 30.0
    sweep_concurrency: int = 8
    # The poller stops rather than hammering a wall. See app/poller.py.
    circuit_breaker_failures: int = 10
    polling_enabled: bool = True
    """Kill switch. Set GAPIQ_POLLING_ENABLED=false to stop upstream traffic without a
    redeploy -- the lever a supporter can pull from a phone."""

    ignore_active_windows: bool = False
    """Escape hatch for local development and replay, where wall-clock windows are
    meaningless."""

    # --- Upstream ---------------------------------------------------------------------
    user_agent: str = "gap-iq/0.1 (+https://github.com/Tapin42/gap-iq)"
    """Mandatory: datasport's Cloudflare rejects default library user agents outright."""

    request_timeout_seconds: float = 20.0

    # --- Ops --------------------------------------------------------------------------
    healthcheck_ping_url: str = ""
    """External dead-man's-switch endpoint, pinged on every successful sweep. An alerter
    living inside this process cannot fire when this process is what died, so liveness is
    asserted outward and the absence of a ping is what raises the alarm."""

    alert_email: str = "navratil@gmail.com"
    """Documented in the runbook as a race-morning checklist item to reassign to a
    supporter who is not competing."""

    # --- Gap engine -------------------------------------------------------------------
    trend_policy: str = "slot"
    """"slot" colours the gap to whoever occupies the neighbouring position; "occupant"
    reproduces the original spec of blanking the trend when the neighbour changes
    identity. See docs/RUNBOOK.md."""

    min_baseline_separation_seconds: int = 300

    active_windows_raw: str = Field(default="", alias="GAPIQ_ACTIVE_WINDOWS")

    # ---------------------------------------------------------------------------------
    @property
    def active_windows(self) -> list[ActiveWindow]:
        if self.active_windows_raw.strip():
            return [_parse_window(item) for item in json.loads(self.active_windows_raw)]
        path = CONFIG_DIR / "windows.json"
        if not path.exists():
            return []
        return [_parse_window(item) for item in json.loads(path.read_text())]

    def window_for(self, moment: datetime | None = None) -> ActiveWindow | None:
        moment = moment or datetime.now(timezone.utc)
        for window in self.active_windows:
            if window.contains(moment):
                return window
        return None

    def polling_allowed(self, moment: datetime | None = None) -> tuple[bool, str]:
        """Return (allowed, human-readable reason). The reason is surfaced on /health so
        "quiet because idle" is never mistaken for "quiet because broken"."""
        if not self.polling_enabled:
            return False, "polling disabled by kill switch (GAPIQ_POLLING_ENABLED=false)"
        if self.ignore_active_windows:
            return True, "active windows bypassed"
        windows = self.active_windows
        if not windows:
            return True, "no active windows configured; polling unrestricted"
        window = self.window_for(moment)
        if window is None:
            return False, "outside every configured active window"
        return True, f"inside active window {window.label!r}"

    @property
    def roster_path(self) -> Path:
        return CONFIG_DIR / self.roster_file


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings_cache() -> None:
    """Test seam."""
    global _settings
    _settings = None
