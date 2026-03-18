#!/usr/bin/env python3
"""
OpsCore — Operations Intelligence Platform
Author: Nnaemeka Duru

Usage:
  python3 main.py                                     # full dashboard with sample data
  python3 main.py --shipments data/shipments.csv      # custom shipment data
  python3 main.py --kpis data/kpis.csv                # custom KPI data
  python3 main.py --anomalies data/metrics.csv        # anomaly scan only
  python3 main.py --sop "Describe your process here"  # generate SOP
  python3 main.py --sop template.json                 # generate SOP from JSON
  python3 main.py --no-alerts                         # suppress Telegram alerts
"""

import argparse
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from opscore import tracker, kpi, anomaly, sop, report

SAMPLE_SHIPMENTS = "sample_data/shipments.csv"
SAMPLE_KPIS      = "sample_data/kpis.csv"

def main():
    parser = argparse.ArgumentParser(description="OpsCore — Operations Intelligence Platform")
    parser.add_argument("--shipments",  default=SAMPLE_SHIPMENTS, help="Shipment CSV file")
    parser.add_argument("--kpis",       default=SAMPLE_KPIS,      help="KPI data CSV file")
    parser.add_argument("--anomalies",  default=None,              help="Metrics CSV for anomaly scan (default: same as --kpis)")
    parser.add_argument("--sop",        default=None,              help="Generate SOP: path to JSON template or plain text description")
    parser.add_argument("--output",     default="opscore_dashboard.html", help="Output HTML file")
    parser.add_argument("--no-alerts",  action="store_true",       help="Disable Telegram alerts")
    parser.add_argument("--sop-only",   action="store_true",       help="Only generate SOP, skip dashboard")
    args = parser.parse_args()

    print("=" * 60)
    print("  OpsCore — Operations Intelligence Platform")
    print("  by Nnaemeka Duru")
    print("=" * 60)

    # ── SOP Generation ──────────────────────────────────────────────────────────
    if args.sop:
        sop_path = sop.run(args.sop, output_dir="sops")
        print(f"\n✅ SOP generated: {sop_path}")
        if args.sop_only:
            return

    # ── Shipment Tracking ───────────────────────────────────────────────────────
    tracker_stats, shipments = {}, []
    if os.path.exists(args.shipments):
        tracker_stats, shipments = tracker.run(args.shipments, alert=not args.no_alerts)
    else:
        print(f"\n[TRACKER] ⚠️  No shipment file found at {args.shipments}")
        print("          Use --shipments <file.csv> or add sample_data/shipments.csv")

    # ── KPI Tracking ────────────────────────────────────────────────────────────
    kpi_summary = {}
    kpi_file = args.kpis
    if os.path.exists(kpi_file):
        kpi_summary = kpi.run(kpi_file)
    else:
        print(f"\n[KPI] ⚠️  No KPI file found at {kpi_file}")
        print("      Use --kpis <file.csv> or add sample_data/kpis.csv")

    # ── Anomaly Detection ───────────────────────────────────────────────────────
    anomaly_file = args.anomalies or kpi_file
    anomalies = []
    if os.path.exists(anomaly_file):
        anomalies = anomaly.run(anomaly_file, alert=not args.no_alerts)

    # ── Dashboard Report ────────────────────────────────────────────────────────
    report.generate(tracker_stats, shipments, kpi_summary, anomalies, output=args.output)

    print("\n" + "=" * 60)
    print(f"  ✅ OpsCore complete — open {args.output} to view dashboard")
    print("=" * 60)

if __name__ == "__main__":
    main()
