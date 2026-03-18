"""HTML Dashboard Report Generator"""

import json
from datetime import datetime
from pathlib import Path

def _color(status):
    return {"good":"#22c55e","ok":"#f59e0b","bad":"#ef4444","neutral":"#6b7280"}.get(status,"#6b7280")

def _sev_color(sev):
    return {"CRITICAL":"#ef4444","HIGH":"#f97316","MEDIUM":"#f59e0b","LOW":"#3b82f6"}.get(sev,"#6b7280")

def generate(tracker_stats, tracker_shipments, kpi_summary, anomalies, output="opscore_dashboard.html"):
    now = datetime.now().strftime("%Y-%m-%d %H:%M UTC")

    # ── Shipment table ──────────────────────────────────────────────────────────
    ship_rows = ""
    for s in (tracker_shipments or [])[:50]:
        status_colors = {"delivered":"#22c55e","delayed":"#f97316","exception":"#ef4444",
                         "in_transit":"#3b82f6","pending":"#9ca3af","returned":"#8b5cf6"}
        sc = status_colors.get(s["status"],"#9ca3af")
        late = f'+{s["days_late"]}d' if s["days_late"] > 0 else ("On time" if s["days_late"] == 0 and s["status"]=="delivered" else "—")
        late_color = "#ef4444" if s["days_late"] > 0 else "#22c55e"
        ship_rows += f"""<tr>
            <td>{s['tracking_id']}</td>
            <td>{s['carrier']}</td>
            <td>{s['destination']}</td>
            <td><span style="background:{sc};color:#fff;padding:2px 8px;border-radius:4px;font-size:11px">{s['status'].upper()}</span></td>
            <td style="color:{late_color}">{late}</td>
            <td>{s['expected_date']}</td>
        </tr>"""

    # ── KPI cards ───────────────────────────────────────────────────────────────
    kpi_cards = ""
    for metric, s in (kpi_summary or {}).items():
        c = _color(s["status"])
        trend_arrow = "↑" if s["trend"] > 0 else ("↓" if s["trend"] < 0 else "→")
        trend_color = "#22c55e" if s["trend"] >= 0 else "#ef4444"
        target_line = f'<div style="color:#6b7280;font-size:11px;margin-top:2px">Target: {s["target"]} {s["unit"]}</div>' if s["target"] else ""
        hit_line = f'<div style="color:#9ca3af;font-size:11px">Hit rate: {s["target_hit_rate"]}%</div>' if s.get("target_hit_rate") is not None else ""
        kpi_cards += f"""<div style="background:#1e293b;border-left:4px solid {c};border-radius:8px;padding:16px 20px">
            <div style="color:#9ca3af;font-size:12px;text-transform:uppercase;letter-spacing:.05em">{metric}</div>
            <div style="font-size:28px;font-weight:700;color:{c};margin:4px 0">{s['latest']} <span style="font-size:14px;color:#6b7280">{s['unit']}</span></div>
            <div style="color:{trend_color};font-size:13px">{trend_arrow} {abs(s['trend_pct'])}% vs baseline</div>
            {target_line}{hit_line}
        </div>"""

    # ── Anomaly rows ────────────────────────────────────────────────────────────
    anomaly_rows = ""
    for a in (anomalies or [])[:20]:
        sc = _sev_color(a["severity"])
        anomaly_rows += f"""<tr>
            <td>{a['date']}</td>
            <td>{a['metric']}</td>
            <td>{a['value']} {a['unit']}</td>
            <td><span style="background:{sc};color:#fff;padding:2px 8px;border-radius:4px;font-size:11px">{a['severity']}</span></td>
            <td style="color:#9ca3af;font-size:12px">{a['detail']}</td>
        </tr>"""

    # ── Carrier performance ─────────────────────────────────────────────────────
    carrier_rows = ""
    for carrier, cs in (tracker_stats.get("carrier_stats") or {}).items():
        ot = round(cs["on_time"]/cs["delivered"]*100,1) if cs["delivered"] else 0
        c = "#22c55e" if ot >= 90 else "#f59e0b" if ot >= 75 else "#ef4444"
        carrier_rows += f"""<tr>
            <td>{carrier}</td>
            <td>{cs['total']}</td>
            <td>{cs['delivered']}</td>
            <td>{cs['delayed']}</td>
            <td style="color:{c};font-weight:600">{ot}%</td>
        </tr>"""

    ts = tracker_stats or {}
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OpsCore Dashboard</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0f172a;color:#e5e7eb;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;padding:32px 20px}}
.container{{max-width:1200px;margin:0 auto}}
h1{{font-size:26px;font-weight:700;color:#f9fafb}}
h2{{font-size:16px;font-weight:600;color:#94a3b8;text-transform:uppercase;letter-spacing:.06em;margin:28px 0 12px}}
.meta{{color:#6b7280;font-size:13px;margin:4px 0 24px}}
.stat-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;margin-bottom:24px}}
.stat{{background:#1e293b;border-radius:8px;padding:16px;text-align:center}}
.stat .num{{font-size:30px;font-weight:700}}
.stat .label{{font-size:12px;color:#9ca3af;margin-top:3px}}
.kpi-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px;margin-bottom:24px}}
.table-wrap{{background:#1e293b;border-radius:10px;overflow-x:auto;margin-bottom:24px}}
table{{width:100%;border-collapse:collapse;min-width:500px}}
thead th{{background:#111827;padding:10px 14px;text-align:left;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;color:#6b7280}}
tbody td{{padding:10px 14px;border-bottom:1px solid #1f2937;font-size:13px;color:#d1d5db}}
tbody tr:last-child td{{border-bottom:none}}
.empty{{padding:30px;text-align:center;color:#4b5563}}
</style>
</head>
<body>
<div class="container">
  <h1>🏭 OpsCore Dashboard</h1>
  <div class="meta">Generated: {now} &nbsp;·&nbsp; Author: Nnaemeka Duru</div>

  <h2>📦 Shipment Overview</h2>
  <div class="stat-grid">
    <div class="stat"><div class="num" style="color:#e5e7eb">{ts.get('total',0)}</div><div class="label">Total</div></div>
    <div class="stat"><div class="num" style="color:#22c55e">{ts.get('delivered',0)}</div><div class="label">Delivered</div></div>
    <div class="stat"><div class="num" style="color:#3b82f6">{ts.get('in_transit',0)}</div><div class="label">In Transit</div></div>
    <div class="stat"><div class="num" style="color:#f97316">{ts.get('delayed',0)}</div><div class="label">Delayed</div></div>
    <div class="stat"><div class="num" style="color:#{'22c55e' if ts.get('on_time_rate',0)>=90 else 'f59e0b' if ts.get('on_time_rate',0)>=75 else 'ef4444'}">{ts.get('on_time_rate',0)}%</div><div class="label">On-Time Rate</div></div>
    <div class="stat"><div class="num" style="color:#ef4444">{ts.get('exceptions',0)}</div><div class="label">Exceptions</div></div>
  </div>

  <h2>🚛 Carrier Performance</h2>
  <div class="table-wrap"><table>
    <thead><tr><th>Carrier</th><th>Total</th><th>Delivered</th><th>Delayed</th><th>On-Time %</th></tr></thead>
    <tbody>{carrier_rows or '<tr><td colspan="5" class="empty">No carrier data</td></tr>'}</tbody>
  </table></div>

  <h2>📊 KPI Metrics</h2>
  <div class="kpi-grid">{kpi_cards or '<div style="color:#4b5563;padding:20px">No KPI data loaded</div>'}</div>

  <h2>🚨 Anomalies Detected</h2>
  <div class="table-wrap"><table>
    <thead><tr><th>Date</th><th>Metric</th><th>Value</th><th>Severity</th><th>Detail</th></tr></thead>
    <tbody>{anomaly_rows or '<tr><td colspan="5" class="empty">✅ No anomalies detected</td></tr>'}</tbody>
  </table></div>

  <h2>📦 Shipment Details</h2>
  <div class="table-wrap"><table>
    <thead><tr><th>Tracking ID</th><th>Carrier</th><th>Destination</th><th>Status</th><th>Delay</th><th>Expected</th></tr></thead>
    <tbody>{ship_rows or '<tr><td colspan="6" class="empty">No shipment data loaded</td></tr>'}</tbody>
  </table></div>
</div></body></html>"""

    Path(output).write_text(html)
    print(f"\n📊 Dashboard → {Path(output).resolve()}")
    return output
