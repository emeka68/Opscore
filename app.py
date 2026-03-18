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
from opscore import tracker, kpi, anomaly, sop, mes_connector, live_tracker, exceptions_mgr, scheduler, prealert

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "opscore-dev-key-change-in-prod")

# Start background scheduler on app load
scheduler.start()

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

# ── MES Routes ─────────────────────────────────────────────────────────────────

@app.route("/mes")
def mes_page():
    return render_template("mes.html")

@app.route("/mes/import", methods=["POST"])
def mes_import():
    kind     = request.form.get("kind", "shipments")
    fmt_map  = request.form.get("field_map", "")
    if "file" not in request.files:
        flash("No file selected", "error")
        return redirect(url_for("mes_page"))

    f = request.files["file"]
    if not f.filename:
        flash("No file selected", "error")
        return redirect(url_for("mes_page"))

    dest = UPLOAD_DIR / f"mes_import_{secure_filename(f.filename)}"
    f.save(str(dest))

    try:
        field_map = None
        if fmt_map and fmt_map in mes_connector.FIELD_MAPS:
            field_map = mes_connector.FIELD_MAPS[fmt_map]

        records = mes_connector.auto_import(str(dest), field_map=field_map)

        # Save as standard OpsCore CSV
        target_name = "shipments.csv" if kind == "shipments" else "kpis.csv"
        out_path = UPLOAD_DIR / target_name
        mes_connector.export_csv(records, str(out_path))

        flash(f"✅ Imported {len(records)} records from MES file as {kind} data", "success")
    except Exception as e:
        flash(f"Import error: {e}", "error")
    finally:
        dest.unlink(missing_ok=True)

    return redirect(url_for("index"))

@app.route("/mes/export/<kind>")
def mes_export(kind):
    import io
    from flask import send_file

    fmt = request.args.get("fmt", "csv")
    t_stats, shipments, kpi_data, _ = load_dashboard_data()

    if kind == "shipments":
        data = shipments
        filename = f"opscore_shipments.{fmt}"
    elif kind == "kpis":
        data = []
        for metric, s in kpi_data.items():
            for h in s.get("history", []):
                data.append({**h, "metric_name": metric})
        filename = f"opscore_kpis.{fmt}"
    else:
        flash("Unknown export kind", "error")
        return redirect(url_for("mes_page"))

    out_path = str(UPLOAD_DIR / filename)
    try:
        mes_connector.auto_export(data, out_path)
        return send_file(out_path, as_attachment=True, download_name=filename)
    except Exception as e:
        flash(f"Export error: {e}", "error")
        return redirect(url_for("mes_page"))

# ── Live Tracker Routes ─────────────────────────────────────────────────────────

@app.route("/tracking")
def tracking_page():
    tracked = live_tracker.list_tracked()
    return render_template("tracking.html", tracked=tracked)

@app.route("/tracking/add", methods=["POST"])
def tracking_add():
    tn      = request.form.get("tracking_number", "").strip()
    carrier = request.form.get("carrier", "").strip() or None
    label   = request.form.get("label", "").strip() or None
    if not tn:
        flash("Tracking number required", "error")
        return redirect(url_for("tracking_page"))
    live_tracker.add_tracking(tn, carrier, label)
    flash(f"✅ Now tracking {label or tn}", "success")
    return redirect(url_for("tracking_page"))

@app.route("/tracking/check")
def tracking_check():
    updates = live_tracker.check_all(alert=True)
    changed = sum(1 for u in updates if u.get("changed"))
    flash(f"Checked {len(updates)} shipment(s) — {changed} status change(s)", "success" if changed else "info")
    return redirect(url_for("tracking_page"))

@app.route("/tracking/remove/<tracking_number>")
def tracking_remove(tracking_number):
    live_tracker.remove_tracking(tracking_number)
    flash(f"Removed {tracking_number}", "info")
    return redirect(url_for("tracking_page"))

@app.route("/tracking/bulk", methods=["POST"])
def tracking_bulk():
    """Upload a CSV with columns: tracking_number, carrier (opt), label (opt)"""
    if "file" not in request.files:
        flash("No file selected", "error")
        return redirect(url_for("tracking_page"))
    f = request.files["file"]
    if not f.filename:
        flash("No file selected", "error")
        return redirect(url_for("tracking_page"))

    import csv, io
    content = f.read().decode("utf-8-sig")
    reader  = csv.DictReader(io.StringIO(content))

    added, skipped = 0, 0
    for row in reader:
        tn = (row.get("tracking_number") or row.get("TrackingNumber") or
              row.get("tracking") or row.get("Tracking") or "").strip()
        if not tn:
            skipped += 1
            continue
        carrier = (row.get("carrier") or row.get("Carrier") or "").strip() or None
        label   = (row.get("label")   or row.get("Label")   or
                   row.get("description") or "").strip() or None
        live_tracker.add_tracking(tn, carrier, label)
        added += 1

    flash(f"✅ Bulk import: {added} shipment(s) added{f', {skipped} skipped' if skipped else ''}", "success")
    return redirect(url_for("tracking_page"))

@app.route("/api/tracking")
def api_tracking():
    return jsonify(live_tracker.list_tracked())

# ── Exception Management Routes ─────────────────────────────────────────────────

@app.route("/exceptions")
def exceptions_page():
    show_resolved = request.args.get("resolved", "false") == "true"
    excs  = exceptions_mgr.get_all(include_resolved=show_resolved)
    stats = exceptions_mgr.get_stats()
    return render_template("exceptions.html", exceptions=excs, stats=stats,
                           show_resolved=show_resolved)

@app.route("/exceptions/<exc_id>")
def exception_detail(exc_id):
    exc = exceptions_mgr.get_by_id(exc_id)
    if not exc:
        flash("Exception not found", "error")
        return redirect(url_for("exceptions_page"))
    return render_template("exception_detail.html", exc=exc)

@app.route("/exceptions/<exc_id>/note", methods=["POST"])
def exception_note(exc_id):
    note   = request.form.get("note", "").strip()
    author = request.form.get("author", "Ops Team").strip()
    if note:
        exceptions_mgr.add_note(exc_id, note, author)
        flash("Note added", "success")
    return redirect(url_for("exception_detail", exc_id=exc_id))

@app.route("/exceptions/<exc_id>/status", methods=["POST"])
def exception_status(exc_id):
    new_status = request.form.get("status", "")
    note       = request.form.get("note", "")
    if exceptions_mgr.update_status(exc_id, new_status, note):
        flash(f"Status updated to {new_status}", "success")
    return redirect(url_for("exception_detail", exc_id=exc_id))

@app.route("/exceptions/<exc_id>/assign", methods=["POST"])
def exception_assign(exc_id):
    assignee = request.form.get("assignee", "").strip()
    if assignee:
        exceptions_mgr.assign(exc_id, assignee)
        flash(f"Assigned to {assignee}", "success")
    return redirect(url_for("exception_detail", exc_id=exc_id))

@app.route("/api/exceptions")
def api_exceptions():
    return jsonify(exceptions_mgr.get_all(include_resolved=True))

@app.route("/api/scheduler/status")
def api_scheduler_status():
    return jsonify(scheduler.get_status())

# ── Pre-Alert Routes ────────────────────────────────────────────────────────────

@app.route("/prealerts")
def prealerts_page():
    sort_by      = request.args.get("sort", "date")
    status_filter = request.args.get("status", None)
    alerts_list  = prealert.get_all(status_filter=status_filter, sort_by=sort_by)
    stats        = prealert.get_stats()
    imap_configured = bool(prealert.EMAIL_ADDR and prealert.EMAIL_PASS)
    return render_template("prealerts.html", alerts=alerts_list, stats=stats,
                           sort_by=sort_by, status_filter=status_filter,
                           imap_configured=imap_configured)

@app.route("/prealerts/fetch", methods=["POST"])
def prealerts_fetch():
    """Fetch new pre-alerts from IMAP inbox."""
    unread_only = request.form.get("unread_only", "true") == "true"
    limit       = int(request.form.get("limit", "20"))
    fetched = prealert.fetch_from_imap(limit=limit, unread_only=unread_only)
    if fetched:
        added = prealert.ingest_many(fetched)
        flash(f"✅ Fetched {len(fetched)} email(s), {added} new pre-alert(s) added", "success")
    else:
        flash("No new emails found or IMAP not configured", "info")
    return redirect(url_for("prealerts_page"))

@app.route("/prealerts/upload", methods=["POST"])
def prealerts_upload():
    """Upload .eml file or paste raw email text."""
    text   = request.form.get("email_text", "").strip()
    sender = request.form.get("sender", "").strip()
    subj   = request.form.get("subject", "Manual Upload").strip()

    # File upload (.eml)
    if "file" in request.files and request.files["file"].filename:
        f = request.files["file"]
        raw = f.read()
        try:
            parsed = prealert.parse_raw_email(raw)
            prealert.ingest(parsed)
            flash(f"✅ Parsed .eml: found {len(parsed['tracking_entries'])} tracking number(s)", "success")
        except Exception as e:
            flash(f"Parse error: {e}", "error")
        return redirect(url_for("prealerts_page"))

    # Pasted text
    if text:
        parsed = prealert.parse_email_text(text, sender=sender, subject=subj)
        prealert.ingest(parsed)
        flash(f"✅ Parsed email text: found {len(parsed['tracking_entries'])} tracking number(s)", "success")
        return redirect(url_for("prealerts_detail", pa_id=parsed["id"]))

    flash("No file or text provided", "error")
    return redirect(url_for("prealerts_page"))

@app.route("/prealerts/<pa_id>")
def prealerts_detail(pa_id):
    pa = prealert.get_by_id(pa_id)
    if not pa:
        flash("Pre-alert not found", "error")
        return redirect(url_for("prealerts_page"))
    return render_template("prealert_detail.html", pa=pa)

@app.route("/prealerts/<pa_id>/track", methods=["POST"])
def prealerts_track(pa_id):
    """Push one tracking number to Live Tracker."""
    tn      = request.form.get("tracking_number", "").strip()
    carrier = request.form.get("carrier", "").strip() or None
    label   = request.form.get("label", "").strip() or None
    if tn:
        live_tracker.add_tracking(tn, carrier, label)
        prealert.mark_tracked(pa_id)
        flash(f"✅ Added {tn} to Live Tracker", "success")
    return redirect(url_for("prealerts_detail", pa_id=pa_id))

@app.route("/prealerts/<pa_id>/track-all", methods=["POST"])
def prealerts_track_all(pa_id):
    """Push all tracking numbers from this pre-alert to Live Tracker."""
    pa = prealert.get_by_id(pa_id)
    if not pa:
        flash("Pre-alert not found", "error")
        return redirect(url_for("prealerts_page"))

    company = pa.get("company", "")
    added = 0
    for entry in pa.get("tracking_entries", []):
        tn      = entry.get("tracking_number", "")
        carrier = entry.get("carrier", "") or None
        label   = f"{company} — {pa.get('subject','')[:40]}" if company else pa.get("subject","")[:50]
        if tn:
            live_tracker.add_tracking(tn, carrier, label)
            added += 1

    prealert.mark_tracked(pa_id)
    flash(f"✅ Sent {added} tracking number(s) to Live Tracker", "success")
    return redirect(url_for("prealerts_detail", pa_id=pa_id))

@app.route("/prealerts/<pa_id>/status", methods=["POST"])
def prealerts_status(pa_id):
    status = request.form.get("status", "reviewed")
    notes  = request.form.get("notes", "")
    prealert.update_status(pa_id, status, notes)
    flash(f"Status updated to {status}", "info")
    return redirect(url_for("prealerts_detail", pa_id=pa_id))

@app.route("/api/prealerts")
def api_prealerts():
    return jsonify(prealert.get_all())

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV", "production") == "development"
    print(f"OpsCore running on http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
