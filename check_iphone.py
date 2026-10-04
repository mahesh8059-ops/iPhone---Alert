#!/usr/bin/env python3
"""Check Apple Canada store pickup availability and send a Gmail alert.

Config (environment variables):
  PART_NUMBER    Apple part number, e.g. MJX74VC/A            (required)
  POSTAL_CODES   comma-separated postal codes to search from  (required)
  GMAIL_ADDRESS  your Gmail address (alerts are sent to yourself) (required)
  GMAIL_APP_PASSWORD  16-character Google app password         (required)
  STORE_FILTER   optional comma-separated words; only stores whose name
                 contains one of them trigger alerts (e.g. "Guildford,Coquitlam")
  STATE_FILE     where to remember what was already alerted   (default state.json)
"""
import json
import os
import smtplib
import sys
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage

PART = os.environ["PART_NUMBER"].strip()
POSTALS = [p.strip() for p in os.environ["POSTAL_CODES"].split(",") if p.strip()]
GMAIL = os.environ["GMAIL_ADDRESS"].strip()
GMAIL_PW = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "").strip()
FILTERS = [f.strip().lower() for f in os.environ.get("STORE_FILTER", "").split(",") if f.strip()]
STATE_FILE = os.environ.get("STATE_FILE", "state.json")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def fetch_stores(postal):
    qs = urllib.parse.urlencode({
        "fae": "true", "pl": "true", "mts.0": "regular", "mts.1": "compact",
        "parts.0": PART, "location": postal,
    })
    url = f"https://www.apple.com/ca/shop/fulfillment-messages?{qs}"
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-CA,en;q=0.9",
        "Referer": "https://www.apple.com/ca/shop/buy-iphone/iphone-18-pro",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        print("HTTP", e.code, "body:", e.read()[:300].decode("utf-8", "replace"), file=sys.stderr)
        raise
    try:
        data = json.loads(raw)
    except ValueError:
        print("Not JSON, first 300 chars:", raw[:300], file=sys.stderr)
        raise
    return data["body"]["content"]["pickupMessage"]["stores"]


def available_stores():
    found = {}
    for postal in POSTALS:
        for s in fetch_stores(postal):
            name = s.get("storeName", "")
            info = s.get("partsAvailability", {}).get(PART, {})
            ok = info.get("pickupDisplay") == "available" or info.get("storePickEligible") is True \
                 and info.get("pickupDisplay") not in ("unavailable", None)
            if not ok:
                continue
            if FILTERS and not any(f in name.lower() for f in FILTERS):
                continue
            found[name] = info.get("pickupSearchQuote") or "Available for pickup"
    return found


def notify(stores):
    lines = [f"- {n}: {q}" for n, q in stores.items()]
    msg = EmailMessage()
    msg["Subject"] = "iPhone 18 Pro Max pickup available: " + ", ".join(stores)
    msg["From"] = GMAIL
    msg["To"] = GMAIL
    msg["X-Priority"] = "1"
    msg.set_content(
        "Pickup is showing as available for the 256GB Burgundy iPhone 18 Pro Max:\n\n"
        + "\n".join(lines)
        + "\n\nReserve it now:\n"
        "https://www.apple.com/ca/shop/buy-iphone/iphone-18-pro/6.9-inch-display-256gb-burgundy\n")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(GMAIL, GMAIL_PW)
        smtp.send_message(msg)


def main():
    try:
        now = available_stores()
    except Exception as e:  # Apple changed/blocked the endpoint: tell us once, don't fail silently
        print("ERROR:", repr(e), file=sys.stderr)
        sys.exit(1)

    try:
        prev = set(json.load(open(STATE_FILE)))
    except Exception:
        prev = set()

    new = {n: q for n, q in now.items() if n not in prev}
    print("available:", list(now) or "none", "| new:", list(new) or "none")
    if new:
        notify(new)
    json.dump(sorted(now), open(STATE_FILE, "w"))


if __name__ == "__main__":
    main()
