"""
OpsCore Pre-Alert Email Parser
Ingests shipment pre-alert emails, extracts tracking info, and feeds Live Tracker.

Pre-alerts are advance shipment notifications sent by vendors/suppliers before
a shipment arrives. Common in cruise, aviation, logistics industries.

Supports:
  - IMAP connection (Gmail, Outlook, corporate mail)
  - Manual upload of .eml files or pasted email text
  - Auto-extraction: tracking numbers, carrier, ETA, company, PO#, description
  - Sorting by date, company, status

Env vars:
  PREALERT_EMAIL        — inbox email address
  PREALERT_PASSWORD     — IMAP app password
  PREALERT_IMAP_HOST    — IMAP server (default: imap.gmail.com)
  PREALERT_IMAP_PORT    — IMAP port (default: 993)
  PREALERT_FOLDER       — folder to monitor (default: INBOX)
  PREALERT_SUBJECT_FILTER — only fetch emails containing this in subject (optional)
"""

import os
import re
import json
import imaplib
import email
import uuid
from email.header import decode_header
from datetime import datetime, timezone
from pathlib import Path

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

# ── Config ─────────────────────────────────────────────────────────────────────
IMAP_HOST      = os.environ.get("PREALERT_IMAP_HOST", "imap.gmail.com")
IMAP_PORT      = int(os.environ.get("PREALERT_IMAP_PORT", "993"))
EMAIL_ADDR     = os.environ.get("PREALERT_EMAIL", "")
EMAIL_PASS     = os.environ.get("PREALERT_PASSWORD", "")
IMAP_FOLDER    = os.environ.get("PREALERT_FOLDER", "INBOX")
SUBJECT_FILTER = os.environ.get("PREALERT_SUBJECT_FILTER", "")

STORE_FILE = Path(__file__).parent.parent / "uploads" / "prealerts.json"

# ── Tracking number patterns ────────────────────────────────────────────────────
CARRIER_PATTERNS = [
    # UPS
    ("ups",   r"\b(1Z[A-Z0-9]{16})\b"),
    # FedEx Express (12/15 digits)
    ("fedex", r"\b([0-9]{4}\s?[0-9]{4}\s?[0-9]{4}|[0-9]{12}|[0-9]{15}|[0-9]{20,22})\b"),
    # USPS
    ("usps",  r"\b(9[2345][0-9]{18,20}|94[0-9]{20}|420[0-9]{25})\b"),
    # DHL Express
    ("dhl",   r"\b(JD[0-9]{18}|[0-9]{10,11})\b"),
    # Amazon
    ("amazon",r"\bTBA[0-9]{12}\b"),
    # Generic "tracking number" near digits
    ("auto",  r"(?:tracking\s*(?:number|#|no\.?)?[\s:]+)([A-Z0-9\-]{8,30})"),
]

DATE_PATTERNS = [
    r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b",
    r"\b(\d{4}[/-]\d{2}[/-]\d{2})\b",
    r"\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})\b",
    r"\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4})\b",
]

PO_PATTERNS = [
    r"(?:P\.?O\.?\s*(?:Number|No\.?|#)[\s:#]+)([A-Z0-9][A-Z0-9\-\/]{3,24})",
    r"(?:Purchase\s+Order[\s:#]+)([A-Z0-9][A-Z0-9\-\/]{3,24})",
    r"\bPO[#\-]([A-Z0-9][A-Z0-9\-]{3,19})\b",
]

CARRIER_KEYWORDS = {
    "ups":    ["ups", "united parcel", "u.p.s"],
    "fedex":  ["fedex", "federal express", "fed ex"],
    "usps":   ["usps", "postal service", "post office", "priority mail"],
    "dhl":    ["dhl", "deutsche post"],
    "maersk": ["maersk", "mærsk"],
    "msc":    ["msc ", "mediterranean shipping"],
    "cma":    ["cma cgm"],
    "evergreen": ["evergreen"],
    "hapag":  ["hapag-lloyd", "hapag lloyd"],
    "amazon": ["amazon logistics", "amazon.com"],
}

ETA_KEYWORDS = ["eta", "estimated arrival", "expected delivery", "estimated delivery",
                "arrive", "arrival date", "delivery date", "due date", "expected date"]
COMPANY_FIELDS = ["from", "sender", "company", "vendor", "supplier", "shipper"]

# ── Storage ────────────────────────────────────────────────────────────────────

def _load() -> list:
    STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if STORE_FILE.exists():
        try:
            return json.loads(STORE_FILE.read_text())
        except Exception:
            pass
    return []

def _save(data: list):
    STORE_FILE.write_text(json.dumps(data, indent=2, default=str))

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

# ── Email text extraction ──────────────────────────────────────────────────────

def _decode_header_str(h: str) -> str:
    parts = decode_header(h or "")
    out = []
    for part, enc in parts:
        if isinstance(part, bytes):
            out.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(str(part))
    return " ".join(out)

def _extract_text_from_message(msg) -> str:
    """Extract plain text from email.Message object."""
    text_parts = []
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition") or "")
            if "attachment" in cd:
                continue
            if ct == "text/plain":
                try:
                    text_parts.append(part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="replace"))
                except Exception:
                    pass
            elif ct == "text/html" and HAS_BS4:
                try:
                    html = part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="replace")
                    text_parts.append(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))
                except Exception:
                    pass
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                text = payload.decode(charset, errors="replace")
                if msg.get_content_type() == "text/html" and HAS_BS4:
                    text = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
                text_parts.append(text)
        except Exception:
            pass
    return "\n".join(text_parts)

# ── Info extraction ────────────────────────────────────────────────────────────

def _extract_tracking_numbers(text: str) -> list:
    """Extract all tracking numbers with their detected carrier."""
    found = []
    seen  = set()
    for carrier, pattern in CARRIER_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            tn = re.sub(r"\s+", "", match.group(1) if match.lastindex else match.group())
            if tn not in seen and len(tn) >= 8:
                seen.add(tn)
                found.append({"tracking_number": tn, "carrier": carrier if carrier != "auto" else ""})
    return found

def _detect_carrier_from_text(text: str) -> str:
    """Detect carrier from keywords in email body."""
    lower = text.lower()
    for carrier, keywords in CARRIER_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return carrier
    return ""

def _extract_dates(text: str) -> list:
    dates = []
    for pattern in DATE_PATTERNS:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            dates.append(m.group(1).strip())
    return list(dict.fromkeys(dates))  # dedupe preserving order

def _extract_eta(text: str) -> str:
    """Find the most likely ETA/delivery date."""
    lines = text.split("\n")
    for line in lines:
        ll = line.lower()
        if any(kw in ll for kw in ETA_KEYWORDS):
            for pattern in DATE_PATTERNS:
                m = re.search(pattern, line, re.IGNORECASE)
                if m:
                    return m.group(1).strip()
    dates = _extract_dates(text)
    return dates[0] if dates else ""

def _extract_po_numbers(text: str) -> list:
    candidates = []
    for pattern in PO_PATTERNS:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            po = m.group(1).strip()
            if re.match(r'^\d{4}$', po):   # skip bare 4-digit years
                continue
            if len(po) < 4:
                continue
            candidates.append(po)

    # Deduplicate: drop any candidate that is a substring of a longer one
    pos = []
    for po in candidates:
        if not any(po != other and po in other for other in candidates):
            if po not in pos:
                pos.append(po)
    return pos

def _extract_company(sender: str, text: str) -> str:
    """Best-effort company/vendor name extraction."""
    # Try email display name first
    if sender:
        # "Company Name <email@domain.com>"
        m = re.match(r'^"?([^"<@]+?)"?\s*<', sender)
        if m:
            name = m.group(1).strip().rstrip(".")
            if name and "@" not in name:
                return name
        # domain as fallback
        m = re.search(r"@([^.>]+)", sender)
        if m:
            return m.group(1).title()

    # Scan body for company/vendor/shipper lines
    for line in text.split("\n")[:30]:
        ll = line.lower()
        for kw in ["company:", "vendor:", "supplier:", "shipper:", "from:", "sender:"]:
            if ll.startswith(kw):
                return line[len(kw):].strip()
    return ""

def _extract_description(text: str) -> str:
    """Try to find description of goods."""
    patterns = [
        r"(?:description|goods|commodity|cargo|item|content)[\s:]+([^\n]{5,80})",
        r"(?:shipment\s+of|containing|consists?\s+of)[\s:]+([^\n]{5,80})",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""

def _extract_weight(text: str) -> str:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:kg|lbs?|pounds?|kilograms?)", text, re.IGNORECASE)
    return m.group(0).strip() if m else ""

# ── Main parse function ────────────────────────────────────────────────────────

def parse_email_text(text: str, sender: str = "", subject: str = "",
                     email_date: str = "") -> dict:
    """Parse raw email text and return structured pre-alert data."""
    tracking_entries = _extract_tracking_numbers(text)
    carrier_from_text = _detect_carrier_from_text(text)

    # If carrier auto-detected from body, fill it in for 'auto' entries
    for entry in tracking_entries:
        if not entry["carrier"] and carrier_from_text:
            entry["carrier"] = carrier_from_text

    return {
        "id":               str(uuid.uuid4())[:8],
        "received_at":      email_date or _now(),
        "ingested_at":      _now(),
        "subject":          subject,
        "sender":           sender,
        "company":          _extract_company(sender, text),
        "tracking_entries": tracking_entries,
        "carrier_detected": carrier_from_text,
        "eta":              _extract_eta(text),
        "po_numbers":       _extract_po_numbers(text),
        "description":      _extract_description(text),
        "weight":           _extract_weight(text),
        "raw_dates":        _extract_dates(text)[:5],
        "status":           "new",          # new | reviewed | tracked | archived
        "tracked":          False,
        "notes":            "",
        "raw_text":         text[:3000],    # store first 3000 chars for reference
    }

def parse_raw_email(raw: bytes) -> dict:
    """Parse a raw .eml bytes object."""
    msg     = email.message_from_bytes(raw)
    subject = _decode_header_str(msg.get("Subject", ""))
    sender  = _decode_header_str(msg.get("From", ""))
    date    = msg.get("Date", "")
    text    = _extract_text_from_message(msg)
    return parse_email_text(text, sender=sender, subject=subject, email_date=date)

# ── IMAP fetch ─────────────────────────────────────────────────────────────────

def fetch_from_imap(limit: int = 20, unread_only: bool = True) -> list:
    """Connect to IMAP and fetch pre-alert emails."""
    if not EMAIL_ADDR or not EMAIL_PASS:
        print("[PREALERT] IMAP not configured — set PREALERT_EMAIL and PREALERT_PASSWORD")
        return []

    print(f"[PREALERT] Connecting to {IMAP_HOST}:{IMAP_PORT} as {EMAIL_ADDR}...")
    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        mail.login(EMAIL_ADDR, EMAIL_PASS)
        mail.select(IMAP_FOLDER)

        search_criteria = "UNSEEN" if unread_only else "ALL"
        if SUBJECT_FILTER:
            search_criteria = f'({search_criteria} SUBJECT "{SUBJECT_FILTER}")'

        _, msg_ids = mail.search(None, search_criteria)
        ids = msg_ids[0].split()[-limit:]  # most recent N

        print(f"[PREALERT] Found {len(ids)} email(s) to process")
        results = []
        for msg_id in reversed(ids):
            _, data = mail.fetch(msg_id, "(RFC822)")
            for part in data:
                if isinstance(part, tuple):
                    parsed = parse_raw_email(part[1])
                    results.append(parsed)
                    print(f"  → {parsed['subject'][:60]} | {len(parsed['tracking_entries'])} tracking#(s)")

        mail.logout()
        return results
    except Exception as e:
        print(f"[PREALERT] IMAP error: {e}")
        return []

# ── Store operations ───────────────────────────────────────────────────────────

def ingest(prealert: dict) -> dict:
    """Save a parsed pre-alert. Deduplicates by subject+sender+date."""
    data = _load()
    # Deduplicate: same subject + sender within same day
    key = f"{prealert.get('subject','')}|{prealert.get('sender','')}|{prealert.get('received_at','')[:10]}"
    for existing in data:
        existing_key = f"{existing.get('subject','')}|{existing.get('sender','')}|{existing.get('received_at','')[:10]}"
        if existing_key == key:
            return existing  # already stored
    data.insert(0, prealert)
    _save(data)
    return prealert

def ingest_many(prealerts: list) -> int:
    count = sum(1 for p in prealerts if ingest(p).get("id") == p.get("id"))
    return count

def get_all(status_filter: str = None, sort_by: str = "date") -> list:
    data = _load()
    if status_filter:
        data = [p for p in data if p.get("status") == status_filter]

    if sort_by == "company":
        data.sort(key=lambda x: (x.get("company","").lower(), x.get("received_at","")), reverse=False)
    else:  # date
        data.sort(key=lambda x: x.get("received_at",""), reverse=True)
    return data

def get_by_id(pa_id: str) -> dict | None:
    for p in _load():
        if p["id"] == pa_id:
            return p
    return None

def update_status(pa_id: str, status: str, notes: str = ""):
    data = _load()
    for p in data:
        if p["id"] == pa_id:
            p["status"] = status
            if notes:
                p["notes"] = notes
            _save(data)
            return True
    return False

def mark_tracked(pa_id: str):
    data = _load()
    for p in data:
        if p["id"] == pa_id:
            p["tracked"] = True
            p["status"]  = "tracked"
            _save(data)
            return


def get_stats() -> dict:
    data = _load()
    by_company = {}
    for p in data:
        c = p.get("company", "Unknown") or "Unknown"
        by_company[c] = by_company.get(c, 0) + 1
    return {
        "total":      len(data),
        "new":        sum(1 for p in data if p.get("status") == "new"),
        "tracked":    sum(1 for p in data if p.get("status") == "tracked"),
        "reviewed":   sum(1 for p in data if p.get("status") == "reviewed"),
        "archived":   sum(1 for p in data if p.get("status") == "archived"),
        "by_company": dict(sorted(by_company.items(), key=lambda x: -x[1])[:10]),
        "total_tracking_numbers": sum(len(p.get("tracking_entries",[])) for p in data),
    }
