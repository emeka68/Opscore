"""
OpsCore Exception Management
Tracks shipment exceptions, stores notes, and manages resolution workflow.

Exception lifecycle:
  open → investigating → resolved / escalated
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

EXCEPTIONS_FILE = Path(__file__).parent.parent / "uploads" / "exceptions.json"

STATUSES   = ["open", "investigating", "escalated", "resolved"]
SEVERITIES = ["low", "medium", "high", "critical"]

EXCEPTION_STATUS_TRIGGERS = {
    "Exception":     ("high",   "Carrier reported a shipment exception"),
    "AttemptFail":  ("medium", "Delivery attempt failed"),
    "Expired":      ("high",   "Shipment tracking has expired"),
}


def _load() -> list:
    EXCEPTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if EXCEPTIONS_FILE.exists():
        try:
            return json.loads(EXCEPTIONS_FILE.read_text())
        except Exception:
            pass
    return []


def _save(data: list):
    EXCEPTIONS_FILE.write_text(json.dumps(data, indent=2, default=str))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── CRUD ───────────────────────────────────────────────────────────────────────

def get_all(include_resolved=False) -> list:
    data = _load()
    if not include_resolved:
        data = [e for e in data if e.get("status") != "resolved"]
    return sorted(data, key=lambda x: x.get("detected_at", ""), reverse=True)


def get_by_id(exc_id: str) -> dict | None:
    for e in _load():
        if e["id"] == exc_id:
            return e
    return None


def create(tracking_number: str, carrier: str, label: str,
           carrier_status: str, detail: str = "", severity: str = "medium") -> dict:
    """Create a new exception record. Returns the new exception."""
    data = _load()

    # Don't duplicate open exceptions for the same tracking number
    for e in data:
        if e["tracking_number"] == tracking_number and e["status"] != "resolved":
            print(f"[EXCEPTIONS] Already open exception for {tracking_number}")
            return e

    exc = {
        "id":              str(uuid.uuid4())[:8],
        "tracking_number": tracking_number,
        "carrier":         carrier,
        "label":           label,
        "carrier_status":  carrier_status,
        "detail":          detail,
        "severity":        severity,
        "status":          "open",
        "detected_at":     _now(),
        "updated_at":      _now(),
        "resolved_at":     None,
        "notes":           [],
        "assignee":        None,
    }
    data.append(exc)
    _save(data)
    print(f"[EXCEPTIONS] Created #{exc['id']} — {label} ({tracking_number}) [{severity.upper()}]")
    return exc


def auto_create_from_tracking_update(update: dict) -> dict | None:
    """
    Called by live_tracker after each check.
    Auto-creates exception if carrier status warrants it.
    """
    status = update.get("new_status", "")
    if status not in EXCEPTION_STATUS_TRIGGERS:
        return None

    severity, detail = EXCEPTION_STATUS_TRIGGERS[status]
    return create(
        tracking_number = update.get("tracking_number", ""),
        carrier         = update.get("carrier", ""),
        label           = update.get("label", update.get("tracking_number", "")),
        carrier_status  = status,
        detail          = detail + (f" — {update.get('location','')}" if update.get("location") else ""),
        severity        = severity,
    )


def add_note(exc_id: str, note: str, author: str = "Ops Team") -> bool:
    data = _load()
    for e in data:
        if e["id"] == exc_id:
            e["notes"].append({
                "text":   note.strip(),
                "author": author,
                "at":     _now(),
            })
            e["updated_at"] = _now()
            if e["status"] == "open":
                e["status"] = "investigating"
            _save(data)
            return True
    return False


def update_status(exc_id: str, new_status: str, note: str = "") -> bool:
    if new_status not in STATUSES:
        return False
    data = _load()
    for e in data:
        if e["id"] == exc_id:
            old = e["status"]
            e["status"]     = new_status
            e["updated_at"] = _now()
            if new_status == "resolved":
                e["resolved_at"] = _now()
            if note:
                e["notes"].append({
                    "text":   f"[Status: {old} → {new_status}] {note}".strip(),
                    "author": "System",
                    "at":     _now(),
                })
            _save(data)
            return True
    return False


def assign(exc_id: str, assignee: str) -> bool:
    data = _load()
    for e in data:
        if e["id"] == exc_id:
            e["assignee"]   = assignee
            e["updated_at"] = _now()
            _save(data)
            return True
    return False


def get_stats() -> dict:
    data = _load()
    open_exc  = [e for e in data if e["status"] != "resolved"]
    resolved  = [e for e in data if e["status"] == "resolved"]
    by_severity = {}
    for e in open_exc:
        s = e.get("severity", "medium")
        by_severity[s] = by_severity.get(s, 0) + 1
    return {
        "total":       len(data),
        "open":        len(open_exc),
        "resolved":    len(resolved),
        "by_severity": by_severity,
        "critical":    by_severity.get("critical", 0),
        "high":        by_severity.get("high", 0),
    }
