# OpsCore 🏭

An operations intelligence platform that unifies shipment tracking, KPI monitoring, anomaly detection, and SOP generation into a single tool — with a live HTML dashboard and Telegram alerts.

Built by someone who's actually worked in operations. No bloat, just what ops teams actually need.

## Features

| Module | What It Does |
|--------|-------------|
| 📦 **Shipment Tracker** | Ingests carrier data, calculates on-time rates, flags delays & exceptions |
| 📊 **KPI Dashboard** | Tracks ops metrics over time, shows trends vs targets |
| 🚨 **Anomaly Detector** | Flags statistical outliers using IQR + z-score analysis |
| 📄 **SOP Generator** | Generates formatted Standard Operating Procedures from plain text or JSON |
| 📬 **Telegram Alerts** | Real-time notifications for delays, anomalies, and exceptions |

## Quick Start

```bash
git clone https://github.com/emeka68/opscore.git
cd opscore
pip install -r requirements.txt

# Run with sample data
python3 main.py

# Open dashboard
open opscore_dashboard.html
```

## Usage

```bash
# Full dashboard with your own data
python3 main.py --shipments data/shipments.csv --kpis data/kpis.csv

# Enable Telegram alerts
export TELEGRAM_BOT_TOKEN="your_token"
export TELEGRAM_CHAT_ID="your_chat_id"
python3 main.py --shipments data/shipments.csv

# Generate SOP from plain text description
python3 main.py --sop "Step 1: Receive inbound shipment. Step 2: Scan barcode..."

# Generate SOP from JSON template
python3 main.py --sop templates/receiving_sop.json --sop-only

# Anomaly scan only
python3 main.py --anomalies data/metrics.csv
```

## Data Formats

**Shipments CSV:**
```
tracking_id, carrier, origin, destination, ship_date, expected_date, actual_delivery_date, status, notes
```

**KPIs CSV:**
```
date, metric_name, value, unit, target, notes
```

See `sample_data/` for examples.

## Sample Output

```
[TRACKER] Loaded 15 shipments
  On-time rate:  71.4%
  Delayed:       10
  Exceptions:    1

[ANOMALY] 4 anomalies detected:
  🟡 avg_handling_time on 2026-03-08: 22.4 min (HIGH, z=2.43)
  🟡 damage_rate on 2026-03-08: 4.7% (HIGH, z=2.42)
```

## Background

Built with real operations knowledge — from coordinating cruise ship cargo at Holland America/Carnival, managing distribution workflows at Shef, and overseeing warehouse operations at Yusen Logistics. OpsCore automates what used to be done manually in spreadsheets.

## Author

**Nnaemeka Duru** — Operations & Cloud Professional
- 5+ years in logistics, warehouse, and distribution operations
- AWS Cloud Practitioner | CompTIA A+
- [LinkedIn](https://linkedin.com/in/nduru) | [GitHub](https://github.com/emeka68)

## License

MIT
