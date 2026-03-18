"""
OpsCore Background Scheduler
Runs carrier tracking checks automatically every N hours.

Env vars:
  CHECK_INTERVAL_HOURS  — how often to auto-check (default: 4)
  SCHEDULER_ENABLED     — set to "false" to disable (default: true)
"""

import os
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

INTERVAL_HOURS = float(os.environ.get("CHECK_INTERVAL_HOURS", "4"))
ENABLED        = os.environ.get("SCHEDULER_ENABLED", "true").lower() != "false"
STATE_FILE     = Path(__file__).parent.parent / "uploads" / "scheduler_state.json"

_thread = None
_stop_event = threading.Event()


def _load_state() -> dict:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"last_run": None, "run_count": 0, "next_run": None}


def _save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


def get_status() -> dict:
    return _load_state()


def _run_check():
    """Run one check cycle — import here to avoid circular import at module load."""
    from . import live_tracker
    print(f"\n[SCHEDULER] Auto-check triggered at {datetime.now(timezone.utc).isoformat()}")
    try:
        updates = live_tracker.check_all(alert=True)
        changed = sum(1 for u in updates if u.get("changed"))
        print(f"[SCHEDULER] Done — {len(updates)} shipment(s) checked, {changed} change(s)")
        return len(updates), changed
    except Exception as e:
        print(f"[SCHEDULER] Check failed: {e}")
        return 0, 0


def _scheduler_loop():
    interval_secs = INTERVAL_HOURS * 3600
    state = _load_state()

    while not _stop_event.is_set():
        now = datetime.now(timezone.utc).timestamp()

        # Determine if it's time to run
        last_run_ts = None
        if state.get("last_run"):
            try:
                from datetime import datetime as dt
                last_run_ts = dt.fromisoformat(state["last_run"].replace("Z", "+00:00")).timestamp()
            except Exception:
                pass

        should_run = (last_run_ts is None) or (now - last_run_ts >= interval_secs)

        if should_run:
            checked, changed = _run_check()
            now_iso = datetime.now(timezone.utc).isoformat()
            next_iso = datetime.fromtimestamp(
                datetime.now(timezone.utc).timestamp() + interval_secs, tz=timezone.utc
            ).isoformat()
            state = {
                "last_run":  now_iso,
                "next_run":  next_iso,
                "run_count": state.get("run_count", 0) + 1,
                "last_checked_count": checked,
                "last_changed_count": changed,
            }
            _save_state(state)

        # Sleep in 60s increments so we can respond to stop events
        for _ in range(60):
            if _stop_event.is_set():
                break
            time.sleep(60)


def start():
    global _thread
    if not ENABLED:
        print("[SCHEDULER] Disabled via SCHEDULER_ENABLED=false")
        return

    if _thread and _thread.is_alive():
        print("[SCHEDULER] Already running")
        return

    _stop_event.clear()
    _thread = threading.Thread(target=_scheduler_loop, daemon=True, name="opscore-scheduler")
    _thread.start()
    print(f"[SCHEDULER] Started — auto-checking every {INTERVAL_HOURS}h")


def stop():
    _stop_event.set()
    print("[SCHEDULER] Stopped")


def trigger_now():
    """Manually trigger a check outside the normal schedule."""
    t = threading.Thread(target=_run_check, daemon=True, name="opscore-manual-check")
    t.start()
    return t
