"""
Live Carrier Tracker Module
Tracks real shipments by tracking number across 900+ carriers via AfterShip.
Saves state locally, detects status changes, and fires Telegram alerts.

Setup:
  1. Free AfterShip account → https://www.aftership.com (100 trackings/month free)
  2. Get API key from dashboard
  3. Set env var: AFTERSHIP_API_KEY=your_key

Usage:
  python3 -m opscore.live_tracker add UPS 1Z999AA10123456784 "My Package"
  python3 -m opscore.live_tracker check       # check all + alert on changes
  python3 -m opscore.live_tracker list        # show all tracked shipments
  python3 -m opscore.live_tracker remove TRK001
"""

import os
import json
import requests
from datetime import datetime, timezone
from pathlib import Path
from . import alerts

API_KEY    = os.environ.get("AFTERSHIP_API_KEY", "")
API_BASE   = "https://api.aftership.com/v4"
STATE_FILE = Path(__file__).parent.parent / "uploads" / "live_tracking_state.json"

# Status groups for human-friendly display
STATUS_LABELS = {
    "Pending":       ("⏳", "Pending"),
    "InfoReceived":  ("📋", "Info Received"),
    "InTransit":     ("🚚", "In Transit"),
    "OutForDelivery":("📦", "Out for Delivery"),
    "AttemptFail":   ("⚠️",  "Delivery Attempted"),
    "Delivered":     ("✅", "Delivered"),
    "AvailableForPickup": ("🏪", "Ready for Pickup"),
    "Exception":     ("🔴", "Exception"),
    "Expired":       ("💀", "Expired"),
}

ALERT_ON_STATUSES = {
    "OutForDelivery", "Delivered", "AttemptFail", "Exception", "AvailableForPickup"
}

def _headers():
    return {
        "as-api-key": API_KEY,
        "Content-Type": "application/json",
    }

def _load_state() -> dict:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}

def _save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))

def demo_track(tracking_number: str, carrier: str) -> dict:
    """Simulate tracking for demo/testing without an API key."""
    import hashlib
    h = int(hashlib.md5(tracking_number.encode()).hexdigest(), 16)
    statuses = ["InfoReceived", "InTransit", "InTransit", "OutForDelivery", "Delivered"]
    idx = h % len(statuses)
    return {
        "tracking_number": tracking_number,
        "carrier":         carrier,
        "status":          statuses[idx],
        "location":        "Distribution Center, Chicago IL",
        "last_update":     datetime.now(timezone.utc).isoformat(),
        "estimated_delivery": "2026-03-20",
        "events": [
            {"datetime": "2026-03-18T08:00:00Z", "status": "Label created", "location": "Origin"},
            {"datetime": "2026-03-18T14:00:00Z", "status": "Package picked up", "location": "Origin"},
            {"datetime": "2026-03-19T06:00:00Z", "status": "Arrived at facility", "location": "Chicago IL"},
        ],
        "demo": True,
    }

def add_tracking(tracking_number: str, carrier: str = None, label: str = None) -> dict:
    """Register a shipment for tracking."""
    state = _load_state()

    if not API_KEY:
        print(f"  [DEMO MODE] No AfterShip API key — simulating tracking for {tracking_number}")
        result = demo_track(tracking_number, carrier or "auto")
        state[tracking_number] = {
            "label":      label or tracking_number,
            "carrier":    carrier or "auto",
            "last_status": result["status"],
            "last_location": result["location"],
            "last_checked": datetime.now(timezone.utc).isoformat(),
            "added_at":   datetime.now(timezone.utc).isoformat(),
            "demo":       True,
        }
        _save_state(state)
        print(f"  ✅ Added (demo): {tracking_number} — {result['status']}")
        return result

    payload = {"tracking": {"tracking_number": tracking_number}}
    if carrier:
        payload["tracking"]["slug"] = carrier.lower()

    r = requests.post(f"{API_BASE}/trackings", headers=_headers(), json=payload, timeout=10)
    data = r.json()

    if r.status_code in (201, 200):
        t = data.get("data", {}).get("tracking", {})
        status = t.get("tag", "Pending")
        state[tracking_number] = {
            "label":       label or t.get("title", tracking_number),
            "carrier":     t.get("slug", carrier or "auto"),
            "aftership_id": t.get("id", ""),
            "last_status": status,
            "last_location": "",
            "last_checked": datetime.now(timezone.utc).isoformat(),
            "added_at":    datetime.now(timezone.utc).isoformat(),
        }
        _save_state(state)
        print(f"  ✅ Added: {tracking_number} ({state[tracking_number]['carrier']}) — {status}")
        return t
    elif r.status_code == 4003:
        print(f"  ℹ️  Already tracking {tracking_number}")
        return {}
    else:
        print(f"  ❌ Failed to add {tracking_number}: {data}")
        return {}

def get_tracking_update(tracking_number: str, state_entry: dict) -> dict:
    """Fetch latest status from AfterShip."""
    if state_entry.get("demo"):
        return demo_track(tracking_number, state_entry.get("carrier",""))

    carrier = state_entry.get("carrier", "")
    r = requests.get(
        f"{API_BASE}/trackings/{carrier}/{tracking_number}",
        headers=_headers(), timeout=10
    )
    if r.status_code != 200:
        # Try without carrier slug
        r = requests.get(
            f"{API_BASE}/trackings/{tracking_number}",
            headers=_headers(), timeout=10
        )
    if r.status_code != 200:
        return {}

    t = r.json().get("data", {}).get("tracking", {})
    checkpoints = t.get("checkpoints", [])
    last_checkpoint = checkpoints[-1] if checkpoints else {}

    return {
        "tracking_number": tracking_number,
        "carrier":         t.get("slug", ""),
        "status":          t.get("tag", ""),
        "location":        last_checkpoint.get("city", "") + " " + last_checkpoint.get("country_name", ""),
        "last_update":     t.get("updated_at", ""),
        "estimated_delivery": t.get("expected_delivery", ""),
        "events":          [
            {
                "datetime": c.get("checkpoint_time", ""),
                "status":   c.get("message", ""),
                "location": c.get("city", "") + ", " + c.get("country_name", "")
            }
            for c in reversed(checkpoints[-5:])
        ],
    }

def check_all(alert=True) -> list:
    """Check all tracked shipments and alert on status changes."""
    state = _load_state()
    if not state:
        print("[LIVE TRACKER] No shipments being tracked. Use 'add' to start tracking.")
        return []

    updates = []
    print(f"\n[LIVE TRACKER] Checking {len(state)} shipment(s)...")

    for tracking_number, entry in state.items():
        update = get_tracking_update(tracking_number, entry)
        if not update:
            continue

        new_status  = update.get("status", "")
        prev_status = entry.get("last_status", "")
        changed     = new_status != prev_status
        icon, label = STATUS_LABELS.get(new_status, ("📦", new_status))
        location    = (update.get("location") or "").strip()

        print(f"  {icon} {entry.get('label', tracking_number)} ({entry.get('carrier','').upper()})")
        print(f"     Status: {label}" + (f" ← was {prev_status}" if changed else "") )
        if location:
            print(f"     Location: {location}")

        state[tracking_number]["last_status"]   = new_status
        state[tracking_number]["last_location"] = location
        state[tracking_number]["last_checked"]  = datetime.now(timezone.utc).isoformat()

        updates.append({
            **entry,
            "tracking_number": tracking_number,
            "new_status": new_status,
            "prev_status": prev_status,
            "changed": changed,
            "location": location,
            "events": update.get("events", []),
            "estimated_delivery": update.get("estimated_delivery", ""),
        })

        # Alert on significant status changes
        if changed and new_status in ALERT_ON_STATUSES and alert:
            icon, label = STATUS_LABELS.get(new_status, ("📦", new_status))
            msg = (
                f"{icon} *Shipment Update*\n\n"
                f"*{entry.get('label', tracking_number)}*\n"
                f"Carrier: `{entry.get('carrier','').upper()}`\n"
                f"Status: *{label}*\n"
                + (f"Location: `{location}`\n" if location else "")
                + (f"Est. Delivery: `{update.get('estimated_delivery','')}`\n" if update.get("estimated_delivery") else "")
                + f"\nTracking #: `{tracking_number}`"
            )
            alerts.send(msg)
            print(f"     📬 Alert sent!")

    _save_state(state)
    return updates

def remove_tracking(tracking_number: str):
    state = _load_state()
    if tracking_number in state:
        entry = state.pop(tracking_number)
        _save_state(state)
        print(f"  ✅ Removed: {entry.get('label', tracking_number)}")

        if API_KEY and not entry.get("demo"):
            carrier = entry.get("carrier", "")
            requests.delete(
                f"{API_BASE}/trackings/{carrier}/{tracking_number}",
                headers=_headers(), timeout=10
            )
    else:
        print(f"  ⚠️  {tracking_number} not found in tracked shipments")

def list_tracked() -> list:
    state = _load_state()
    if not state:
        print("  No shipments currently tracked")
        return []

    print(f"\n{'='*55}")
    print(f"  Live Tracked Shipments ({len(state)})")
    print(f"{'='*55}")
    items = []
    for tn, entry in state.items():
        icon, label = STATUS_LABELS.get(entry.get("last_status",""), ("📦", entry.get("last_status","")))
        print(f"  {icon} {entry.get('label', tn)}")
        print(f"     {tn} | {entry.get('carrier','').upper()} | {label}")
        print(f"     Last checked: {entry.get('last_checked','')[:19]}")
        items.append({**entry, "tracking_number": tn})
    return items

if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if not args or args[0] == "list":
        list_tracked()
    elif args[0] == "check":
        check_all()
    elif args[0] == "add" and len(args) >= 2:
        tracking = args[1]
        carrier  = args[2] if len(args) > 2 else None
        label    = args[3] if len(args) > 3 else None
        add_tracking(tracking, carrier, label)
    elif args[0] == "remove" and len(args) >= 2:
        remove_tracking(args[1])
    else:
        print("Usage:")
        print("  python3 -m opscore.live_tracker list")
        print("  python3 -m opscore.live_tracker check")
        print("  python3 -m opscore.live_tracker add <tracking_number> [carrier] [label]")
        print("  python3 -m opscore.live_tracker remove <tracking_number>")
