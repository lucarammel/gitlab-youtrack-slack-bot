"""Connectivity watchdog: alert once when polling keeps failing (VPN down...), and on recovery."""

from __future__ import annotations

from datetime import datetime

from .config import Config
from .formatting import esc
from .models import Notification
from .state import State, now_iso

KEY = "health"


def _h(state: State) -> dict:
    return state.data.setdefault(KEY, {"failures": 0, "alerted": False, "failing_since": None})


def on_failure(state: State, cfg: Config, error: Exception, quiet: bool) -> Notification | None:
    h = _h(state)
    h["failures"] += 1
    h["failing_since"] = h["failing_since"] or now_iso()
    h["last_error"] = str(error)[:300]
    threshold = cfg.alert_after_failures
    if threshold and h["failures"] >= threshold and not h["alerted"] and not quiet:
        h["alerted"] = True
        since = datetime.fromisoformat(h["failing_since"]).astimezone().strftime("%H:%M")
        return Notification(
            "connectivity",
            f"*:rotating_light: Notifier can't poll* since {since} ({h['failures']} attempts) — VPN down?\n"
            f"> {esc(h['last_error'])}",
        )
    return None


def on_success(state: State) -> Notification | None:
    h = _h(state)
    was_alerted = h["alerted"]
    state.data[KEY] = {"failures": 0, "alerted": False, "failing_since": None}
    if was_alerted:
        return Notification("connectivity", "*:electric_plug: Notifier is back online*, catching up.")
    return None
