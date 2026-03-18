"""
Anomaly Detection Module
Uses IQR and z-score methods to flag outliers in any numeric dataset.

CSV format: date, metric_name, value, unit
"""

import csv
import math
from pathlib import Path
from collections import defaultdict
from . import alerts

def load_data(filepath):
    records = []
    with open(Path(filepath), newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                records.append({
                    "date":   row.get("date","").strip(),
                    "metric": row.get("metric_name","").strip(),
                    "value":  float(row.get("value",0)),
                    "unit":   row.get("unit","").strip(),
                })
            except (ValueError, TypeError):
                continue
    return records

def stats(values):
    n = len(values)
    if n == 0:
        return 0, 0, 0, 0, 0
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    std = math.sqrt(variance)
    sorted_v = sorted(values)
    q1 = sorted_v[n // 4]
    q3 = sorted_v[(3 * n) // 4]
    iqr = q3 - q1
    return mean, std, q1, q3, iqr

def detect(records, z_threshold=2.5, iqr_multiplier=1.5):
    by_metric = defaultdict(list)
    for r in records:
        by_metric[r["metric"]].append(r)

    anomalies = []
    for metric, entries in by_metric.items():
        values = [e["value"] for e in entries]
        if len(values) < 4:
            continue

        mean, std, q1, q3, iqr = stats(values)
        lower_iqr = q1 - iqr_multiplier * iqr
        upper_iqr = q3 + iqr_multiplier * iqr

        for e in entries:
            v = e["value"]
            z = abs((v - mean) / std) if std > 0 else 0
            iqr_flag = v < lower_iqr or v > upper_iqr

            if z >= z_threshold or iqr_flag:
                direction = "HIGH" if v > mean else "LOW"
                anomalies.append({
                    "date":      e["date"],
                    "metric":    metric,
                    "value":     v,
                    "unit":      e["unit"],
                    "z_score":   round(z, 2),
                    "mean":      round(mean, 2),
                    "std":       round(std, 2),
                    "direction": direction,
                    "severity":  "CRITICAL" if z >= 3.5 else "HIGH" if z >= 2.5 else "MEDIUM",
                    "detail":    f"{v} {e['unit']} ({direction}, z={z:.2f}, mean={mean:.2f}±{std:.2f})"
                })

    return sorted(anomalies, key=lambda x: x["z_score"], reverse=True)

def run(filepath, alert=True):
    print(f"\n[ANOMALY] Scanning {filepath}...")
    try:
        records = load_data(filepath)
    except FileNotFoundError:
        print(f"  ⚠️  File not found: {filepath}")
        return []

    if not records:
        return []

    anomalies = detect(records)
    if not anomalies:
        print("  ✅ No anomalies detected")
        return []

    print(f"  ⚠️  {len(anomalies)} anomaly(s) detected:")
    for a in anomalies[:10]:
        icon = "🔴" if a["severity"] == "CRITICAL" else "🟠" if a["severity"] == "HIGH" else "🟡"
        print(f"    {icon} [{a['severity']}] {a['metric']} on {a['date']}: {a['detail']}")

    if alert:
        lines = "\n".join([
            f"• {a['metric']} ({a['date']}): {a['value']} {a['unit']} [{a['direction']}, z={a['z_score']}]"
            for a in anomalies[:5]
        ])
        alerts.send(
            f"🚨 *OpsCore Anomaly Alert*\n\n"
            f"{len(anomalies)} anomaly(s) detected:\n{lines}\n\n"
            f"_Run OpsCore for full report._",
            silent=True
        )

    return anomalies
