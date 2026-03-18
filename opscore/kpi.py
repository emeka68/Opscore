"""
KPI Tracker Module
Ingests operations data CSV and computes KPIs over time.

CSV format:
  date, metric_name, value, unit, target (optional), notes (optional)
"""

import csv
from datetime import datetime
from pathlib import Path
from collections import defaultdict

def parse_date(s):
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except Exception:
            continue
    return None

def load_kpis(filepath):
    records = []
    path = Path(filepath)
    if not path.exists():
        print(f"  ⚠️  File not found: {filepath}")
        return []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            d = parse_date(row.get("date", ""))
            if not d:
                continue
            try:
                value  = float(row.get("value", 0))
                target = float(row["target"]) if row.get("target") else None
            except (ValueError, TypeError):
                continue
            records.append({
                "date":   str(d),
                "metric": row.get("metric_name", "").strip(),
                "value":  value,
                "unit":   row.get("unit", "").strip(),
                "target": target,
                "notes":  row.get("notes", "").strip(),
            })
    return records

def analyze(records):
    # Group by metric
    by_metric = defaultdict(list)
    for r in records:
        by_metric[r["metric"]].append(r)

    summary = {}
    for metric, entries in by_metric.items():
        entries.sort(key=lambda x: x["date"])
        values  = [e["value"] for e in entries]
        targets = [e["target"] for e in entries if e["target"] is not None]
        latest  = entries[-1]
        avg     = sum(values) / len(values)
        trend   = values[-1] - values[0] if len(values) > 1 else 0

        # Target hit rate
        target_hit_rate = None
        if targets:
            t = targets[-1]
            # For most KPIs, higher = better. Detect inverted (e.g. "damage_rate")
            inverted = any(w in metric.lower() for w in ["delay","damage","error","cost","time","late","miss"])
            hits = [v for v in values if (v <= t if inverted else v >= t)]
            target_hit_rate = round(len(hits) / len(values) * 100, 1)

        summary[metric] = {
            "latest":          round(latest["value"], 2),
            "unit":            latest["unit"],
            "target":          targets[-1] if targets else None,
            "avg":             round(avg, 2),
            "trend":           round(trend, 2),
            "trend_pct":       round((trend / values[0] * 100), 1) if values[0] != 0 else 0,
            "target_hit_rate": target_hit_rate,
            "history":         entries,
            "status":          _status(latest["value"], targets[-1] if targets else None, metric),
        }
    return summary

def _status(value, target, metric):
    if target is None:
        return "neutral"
    inverted = any(w in metric.lower() for w in ["delay","damage","error","cost","time","late","miss"])
    if inverted:
        if value <= target * 0.9:  return "good"
        if value <= target:        return "ok"
        return "bad"
    else:
        if value >= target * 0.95: return "good"
        if value >= target * 0.8:  return "ok"
        return "bad"

def run(filepath):
    print(f"\n[KPI TRACKER] Loading data from {filepath}...")
    records = load_kpis(filepath)
    if not records:
        return {}
    print(f"  Loaded {len(records)} records across metrics")
    summary = analyze(records)
    for metric, s in summary.items():
        status_icon = {"good": "✅", "ok": "🟡", "bad": "🔴", "neutral": "➖"}.get(s["status"], "➖")
        print(f"  {status_icon} {metric}: {s['latest']} {s['unit']} (avg: {s['avg']}, trend: {s['trend_pct']:+.1f}%)")
    return summary
