"""
Shipment Tracker Module
Ingests shipment CSV data, calculates delivery performance,
flags delayed/at-risk shipments, and generates alerts.

CSV format:
  tracking_id, carrier, origin, destination, ship_date, expected_date,
  actual_delivery_date (blank if not delivered), status, notes
"""

import csv
import json
from datetime import datetime, date
from pathlib import Path
from . import alerts

STATUSES = {
    "delivered":   ("✅", "DELIVERED"),
    "in_transit":  ("🚚", "IN TRANSIT"),
    "delayed":     ("⚠️", "DELAYED"),
    "exception":   ("🔴", "EXCEPTION"),
    "pending":     ("⏳", "PENDING"),
    "returned":    ("↩️", "RETURNED"),
}

def parse_date(s):
    if not s or str(s).strip() in ("", "N/A", "None"):
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None

def load_shipments(filepath):
    shipments = []
    path = Path(filepath)
    if not path.exists():
        print(f"  ⚠️  File not found: {filepath}")
        return []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ship_date     = parse_date(row.get("ship_date", ""))
            expected_date = parse_date(row.get("expected_date", ""))
            delivery_date = parse_date(row.get("actual_delivery_date", ""))
            today         = date.today()

            # Compute days late
            days_late = None
            if delivery_date and expected_date:
                days_late = (delivery_date - expected_date).days
            elif not delivery_date and expected_date and today > expected_date:
                days_late = (today - expected_date).days

            status = (row.get("status") or "").lower().strip()
            if status not in STATUSES:
                # Auto-classify
                if delivery_date:
                    status = "delivered"
                elif days_late and days_late > 0:
                    status = "delayed"
                elif not delivery_date and expected_date and today <= expected_date:
                    status = "in_transit"
                else:
                    status = "pending"

            shipments.append({
                "tracking_id":    row.get("tracking_id", ""),
                "carrier":        row.get("carrier", "").upper(),
                "origin":         row.get("origin", ""),
                "destination":    row.get("destination", ""),
                "ship_date":      str(ship_date) if ship_date else "",
                "expected_date":  str(expected_date) if expected_date else "",
                "delivery_date":  str(delivery_date) if delivery_date else "",
                "status":         status,
                "days_late":      days_late or 0,
                "notes":          row.get("notes", ""),
            })
    return shipments

def analyze(shipments):
    total       = len(shipments)
    delivered   = [s for s in shipments if s["status"] == "delivered"]
    delayed     = [s for s in shipments if s["days_late"] > 0]
    exceptions  = [s for s in shipments if s["status"] == "exception"]
    in_transit  = [s for s in shipments if s["status"] == "in_transit"]
    on_time     = [s for s in delivered if s["days_late"] <= 0]

    avg_days_late = (
        sum(s["days_late"] for s in delayed) / len(delayed) if delayed else 0
    )
    on_time_rate = (len(on_time) / len(delivered) * 100) if delivered else 0

    # Carrier performance
    carrier_stats = {}
    for s in shipments:
        c = s["carrier"] or "UNKNOWN"
        if c not in carrier_stats:
            carrier_stats[c] = {"total": 0, "delivered": 0, "delayed": 0, "on_time": 0}
        carrier_stats[c]["total"] += 1
        if s["status"] == "delivered":
            carrier_stats[c]["delivered"] += 1
            if s["days_late"] <= 0:
                carrier_stats[c]["on_time"] += 1
        if s["days_late"] > 0:
            carrier_stats[c]["delayed"] += 1

    return {
        "total":         total,
        "delivered":     len(delivered),
        "in_transit":    len(in_transit),
        "delayed":       len(delayed),
        "exceptions":    len(exceptions),
        "on_time_rate":  round(on_time_rate, 1),
        "avg_days_late": round(avg_days_late, 1),
        "carrier_stats": carrier_stats,
        "flagged":       sorted(delayed + exceptions, key=lambda x: x["days_late"], reverse=True)[:10],
    }

def run(filepath, alert=True):
    print(f"\n[TRACKER] Loading shipments from {filepath}...")
    shipments = load_shipments(filepath)
    if not shipments:
        return {}, []

    print(f"  Loaded {len(shipments)} shipments")
    stats = analyze(shipments)

    print(f"  On-time rate:  {stats['on_time_rate']}%")
    print(f"  Delayed:       {stats['delayed']}")
    print(f"  Exceptions:    {stats['exceptions']}")
    print(f"  In transit:    {stats['in_transit']}")
    print(f"  Avg days late: {stats['avg_days_late']}")

    if stats["flagged"] and alert:
        flagged_lines = "\n".join([
            f"  • {s['tracking_id']} ({s['carrier']}) — {s['days_late']}d late → {s['destination']}"
            for s in stats["flagged"][:5]
        ])
        alerts.send(
            f"🚚 *Shipment Alert — {stats['delayed']} Delayed*\n\n"
            f"On-time rate: `{stats['on_time_rate']}%`\n"
            f"Avg delay: `{stats['avg_days_late']} days`\n\n"
            f"*Top flagged:*\n{flagged_lines}",
            silent=True
        )

    return stats, shipments
