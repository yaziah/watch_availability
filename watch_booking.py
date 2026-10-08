#!/usr/bin/env python3
"""
Watches a YouCanBook.me page that shows "No Availability" until new slots are
released, then sends a phone push notification (ntfy.sh) when slots appear or
change.

Usage:
  python watch_booking.py --debug   # print what it sees, save debug.png, no alert
  python watch_booking.py           # normal run (used by the scheduler)
"""
import argparse
import json
import os
import re
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

URL = "https://utest-lon-journey-ar-gulf.youcanbook.me/"
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "CHANGE-ME")
STATE_FILE = Path(__file__).with_name("booking_state.json")

NO_AVAIL_RE = re.compile(r"no availability", re.I)
# Lines of page text that look like a time or a date:
TIME_RE = re.compile(r"\b\d{1,2}[:.]\d{2}\s*(am|pm)?\b", re.I)
DATE_RE = re.compile(
    r"\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*\b|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b",
    re.I,
)
# Lines to ignore (timezone pickers, footers, clocks) so they don't cause false alerts:
EXCLUDE_RE = re.compile(r"time\s*zone|timezone|gmt|utc|europe/|powered by|cookie|privacy", re.I)


def read_page():
    """Returns (status, slots). status: 'none' | 'available' | 'unknown'."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(URL, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(3000)
        text = page.inner_text("body")
        page.screenshot(path="debug.png", full_page=True)
        browser.close()

    if NO_AVAIL_RE.search(text):
        return "none", set(), text

    lines = [l.strip() for l in text.splitlines() if l.strip()]
    slots = {
        l for l in lines
        if (TIME_RE.search(l) or DATE_RE.search(l)) and not EXCLUDE_RE.search(l)
    }
    return ("available" if slots else "unknown"), slots, text


def notify(message):
    requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=message.encode("utf-8"),
        headers={"Title": "New booking availability!", "Priority": "urgent",
                 "Click": URL, "Tags": "calendar,rotating_light"},
        timeout=15,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    status, slots, text = read_page()

    if args.debug:
        print("STATUS:", status)
        print("SLOT LINES DETECTED:")
        for s in sorted(slots):
            print("  ", s)
        print("\n--- RAW PAGE TEXT ---\n", text)
        return

    if status == "unknown":
        # Page didn't load properly or layout changed; keep old state, don't alert.
        print("Could not read page; state unchanged.")
        return

    old = set(json.loads(STATE_FILE.read_text())) if STATE_FILE.exists() else None
    STATE_FILE.write_text(json.dumps(sorted(slots)))

    if old is None:
        print("Baseline saved:", status)
        return

    added = slots - old
    if added:
        preview = " | ".join(sorted(added)[:6])
        notify(f"New availability: {preview}\n{URL}")
        print("Notified:", preview)
    else:
        print("No new availability (" + status + ").")


if __name__ == "__main__":
    main()
