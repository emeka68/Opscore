#!/usr/bin/env python3
"""
OpsCore Flask Web Application
Author: Nnaemeka Duru
"""

import os
import json
import shutil
from pathlib import Path
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from werkzeug.utils import secure_filename

import sys
sys.path.insert(0, os.path.dirname(__file__))
from opscore import tracker, kpi, anomaly, sop

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "opscore-dev-key-change-in-prod")

UPLOAD_DIR   = Path("uploads")
SAMPLE_DIR   = Path("sample_data")
ALLOWED_EXT  = {"csv", "json"}
UPLOAD_DIR.mkdir(exist_ok=True)

def allowed(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT

def get_data_path(name, default_name):
    upload = UPLOAD_DIR / name
    if upload.exists():
        return str(upload)
    sample = SAMPLE_DIR / default_name
    if sample.exists():
        return str(sample)
    return None

def load_dashboard_data():
    ship_file = get_data_path("shipments.csv", "shipments.csv")
    kpi_file  = get_data_path("kpis.csv",      "kpis.csv")

    t_stats, shipments, kpi_data, anomalies = {}, [], {}, []

    if ship_file:
        t_stats, shipments = tracker.run(ship_file, alert=False)
    if kpi_file:
        kpi_data  = kpi.run(kpi_file)
        anomalies = anomaly.run(kpi_file, alert=False)

    return t_stats, shipments, kpi_data, anomalies

# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    t_stats, shipments, kpi_data, anomalies = load_dashboard_data()

    # Carrier stats for template
    carrier_data = []
    for carrier, cs in t_stats.get("carrier_stats", {}).items():
        ot = round(cs["on_time"] / cs["delivered"] * 100, 1) if cs["delivered"] else 0
        carrier_data.append({**cs, "carrier": carrier, "on_time_rate": ot})
    carrier_data.sort(key=lambda x: x["total"], reverse=True)

    # KPI data serializable
    kpi_list = []
    for metric, s in kpi_data.items():
        history_values = [r["value"] for r in s.get("history", [])]
        history_dates  = [r["date"]  for r in s.get("history", [])]
        kpi_list.append({**s, "metric": metric,
                          "history_values": json.dumps(history_values),
                          "history_dates":  json.dumps(history_dates)})

    return render_template("index.html",
        stats      = t_stats,
        shipments  = shipments[:50],
        kpi_list   = kpi_list,
        anomalies  = anomalies[:20],
        carriers   = carrier_data,
        flagged    = t_stats.get("flagged", [])[:8],
    )

@app.route("/upload", methods=["POST"])
def upload():
    kind = request.form.get("kind", "")  # "shipments" or "kpis"
    if "file" not in request.files:
        flash("No file selected", "error")
        return redirect(url_for("index"))

    f = request.files["file"]
    if f.filename == "" or not allowed(f.filename):
        flash("Invalid file — only CSV and JSON allowed", "error")
        return redirect(url_for("index"))

    name = "shipments.csv" if kind == "shipments" else "kpis.csv"
    dest = UPLOAD_DIR / name
    f.save(str(dest))
    flash(f"✅ {kind.capitalize()} data uploaded successfully", "success")
    return redirect(url_for("index"))

@app.route("/reset/<kind>")
def reset(kind):
    target = UPLOAD_DIR / ("shipments.csv" if kind == "shipments" else "kpis.csv")
    if target.exists():
        target.unlink()
    flash(f"Reset to sample {kind} data", "info")
    return redirect(url_for("index"))

@app.route("/sop", methods=["GET", "POST"])
def sop_page():
    result = None
    if request.method == "POST":
        description = request.form.get("description", "").strip()
        title       = request.form.get("title", "Standard Operating Procedure").strip()
        author      = request.form.get("author", "Operations Team").strip()
        dept        = request.form.get("department", "Operations").strip()

        if description:
            content = sop.generate_from_description(title, description, author=author, dept=dept)
            result = content
        else:
            flash("Please enter a process description", "error")

    return render_template("sop.html", result=result)

@app.route("/api/stats")
def api_stats():
    t_stats, shipments, kpi_data, anomalies = load_dashboard_data()
    return jsonify({
        "shipments": t_stats,
        "kpis": {k: {x: v[x] for x in ["latest","unit","target","avg","trend_pct","status"]}
                 for k, v in kpi_data.items()},
        "anomalies": len(anomalies),
        "flagged_shipments": len(t_stats.get("flagged", [])),
    })

@app.route("/api/shipments")
def api_shipments():
    ship_file = get_data_path("shipments.csv", "shipments.csv")
    if not ship_file:
        return jsonify([])
    _, shipments = tracker.run(ship_file, alert=False)
    return jsonify(shipments)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV", "production") == "development"
    print(f"OpsCore running on http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
