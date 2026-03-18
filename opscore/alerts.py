"""Telegram alert module."""
import os, requests

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")

def send(message: str, silent=False):
    if not BOT_TOKEN or not CHAT_ID:
        if not silent:
            print(f"\n[ALERT] {message}\n")
        return False
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"},
            timeout=10
        )
        return True
    except Exception as e:
        print(f"Alert failed: {e}")
        return False
