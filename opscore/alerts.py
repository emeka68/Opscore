"""
OpsCore Alert Module
Supports: Telegram, Email (SMTP)

Env vars:
  Telegram: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
  Email:    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, ALERT_EMAIL
            SMTP_FROM (optional, defaults to SMTP_USER)
"""

import os
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ── Telegram ───────────────────────────────────────────────────────────────────
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")

# ── Email ──────────────────────────────────────────────────────────────────────
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER)
ALERT_EMAIL = os.environ.get("ALERT_EMAIL", "")   # recipient(s), comma-separated


def send_telegram(message: str, silent=False) -> bool:
    if not BOT_TOKEN or not CHAT_ID:
        if not silent:
            print(f"\n[ALERT/TELEGRAM] {message}\n")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"},
            timeout=10,
        )
        return r.ok
    except Exception as e:
        print(f"[ALERT] Telegram failed: {e}")
        return False


def send_email(subject: str, body: str, html_body: str = None) -> bool:
    """Send alert via SMTP. Supports plain text and optional HTML."""
    if not all([SMTP_USER, SMTP_PASS, ALERT_EMAIL]):
        print(f"[ALERT/EMAIL] Not configured — skipping email. ({subject})")
        return False

    recipients = [r.strip() for r in ALERT_EMAIL.split(",") if r.strip()]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[OpsCore] {subject}"
    msg["From"]    = SMTP_FROM or SMTP_USER
    msg["To"]      = ", ".join(recipients)

    msg.attach(MIMEText(body, "plain"))
    if html_body:
        msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_FROM or SMTP_USER, recipients, msg.as_string())
        print(f"[ALERT/EMAIL] Sent: {subject} → {', '.join(recipients)}")
        return True
    except Exception as e:
        print(f"[ALERT] Email failed: {e}")
        return False


def send(message: str, subject: str = None, silent=False, email=True, telegram=True) -> dict:
    """
    Send alert via all configured channels.
    Returns dict of {channel: success_bool}.
    """
    results = {}

    if telegram:
        results["telegram"] = send_telegram(message, silent=silent)

    if email:
        # Convert Markdown message to plain text (strip asterisks/backticks)
        plain = message.replace("*", "").replace("`", "").replace("_", "")
        subj  = subject or plain.split("\n")[0][:80]
        html  = _markdown_to_html(message)
        results["email"] = send_email(subj, plain, html)

    return results


def _markdown_to_html(text: str) -> str:
    """Minimal Markdown → HTML for email bodies."""
    import re
    lines = []
    for line in text.split("\n"):
        line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
        line = re.sub(r"\*(.+?)\*",     r"<em>\1</em>",         line)
        line = re.sub(r"`(.+?)`",       r"<code>\1</code>",      line)
        lines.append(line)
    body = "<br>".join(lines)
    return f"""
    <html><body style="font-family:Arial,sans-serif;color:#1f2937;max-width:600px;margin:0 auto;padding:20px">
    <div style="background:#1e293b;color:#e5e7eb;border-radius:8px;padding:20px">
      <h2 style="color:#3b82f6;margin-top:0">OpsCore Alert</h2>
      <p style="line-height:1.7">{body}</p>
      <hr style="border-color:#334155;margin:16px 0">
      <p style="color:#64748b;font-size:12px">Sent by OpsCore · Unsubscribe by removing ALERT_EMAIL env var</p>
    </div></body></html>"""
