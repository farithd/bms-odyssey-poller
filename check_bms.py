"""
BookMyShow IMAX showtime poller → Twilio phone call notifier
Polls for The Odyssey at PVR Palazzo Chennai on 20 July 2026.
"""

import os
import json
import hashlib
import requests
from datetime import datetime
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
EVENT_CODE  = os.environ["BMS_EVENT_CODE"]   # ET00452034
VENUE_CODE  = "CHNP"                          # PVR Palazzo Chennai
CITY_CODE   = "CHEN"
TARGET_DATE = "20260719"
STATE_FILE  = Path("seen_shows.json")

TWILIO_SID   = os.environ["TWILIO_SID"]
TWILIO_TOKEN = os.environ["TWILIO_TOKEN"]
TWILIO_FROM  = os.environ["TWILIO_FROM"]     # your Twilio number
MY_PHONE     = os.environ["MY_PHONE"]        # your number e.g. +919876543210

BMS_API = (
    "https://in.bookmyshow.com/api/movies-data/showtimes-by-event"
    "?appCode=MOBAND2&appVersion=14304&language=en"
    f"&eventCode={EVENT_CODE}&format=json"
    f"&regionCode={CITY_CODE}&subRegion={CITY_CODE}"
    f"&ccode={VENUE_CODE}&date={TARGET_DATE}"
    "&priceCat=0"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://in.bookmyshow.com/",
    "Origin": "https://in.bookmyshow.com",
    "x-region-code": CITY_CODE,
    "x-region-slug": "chennai",
    "x-bms-id": "1.3.0.1",
    "Connection": "keep-alive",
}


def load_seen() -> set:
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text()))
    return set()


def save_seen(seen: set):
    STATE_FILE.write_text(json.dumps(sorted(seen)))


def show_key(venue: str, time: str, screen: str) -> str:
    return hashlib.md5(f"{venue}|{time}|{screen}".encode()).hexdigest()


def make_call(show: dict):
    message = (
        f"Alert! Odyssey IMAX bookings are now open at {show['venue']}. "
        f"Screen: {show['screen']}. "
        f"Show time: {show['time']}. "
        f"Open BookMyShow immediately to grab your seat. "
        f"Repeating. "
        f"Alert! Odyssey IMAX bookings are now open. "
        f"Show time: {show['time']}. Book now!"
    )

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="alice" language="en-IN" loop="3">{message}</Say>
</Response>"""

    try:
        resp = requests.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Calls.json",
            auth=(TWILIO_SID, TWILIO_TOKEN),
            data={"To": MY_PHONE, "From": TWILIO_FROM, "Twiml": twiml},
            timeout=15,
        )
        resp.raise_for_status()
        print(f"[Twilio] Call initiated: {resp.json().get('sid')}")
    except Exception as e:
        print(f"[Twilio] Call failed: {e}")
        # Fallback: silent ntfy push so you still get something
        try:
            requests.post(
                "https://ntfy.sh/bms-fallback-odyssey-palazzo",
                data=f"BOOK NOW — Odyssey IMAX @ {show['venue']} {show['time']}".encode(),
                headers={"Title": "BMS IMAX LIVE!", "Priority": "urgent"},
                timeout=10,
            )
        except Exception:
            pass


def poll():
    print(f"[{datetime.utcnow().isoformat()}] Polling BMS...")

    try:
        resp = requests.get(BMS_API, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[ERROR] BMS request failed: {e}")
        return

    venues = data.get("BookingDetails", {}).get("Venues", [])

    if not venues:
        print("No showtimes found yet.")
        return

    seen = load_seen()
    new_found = []

    for venue in venues:
        vname = venue.get("VenueName", "")
        for show in venue.get("ShowDetails", []):
            for t in show.get("ShowTimings", []):
                screen   = show.get("ScreenName", "")
                showtime = t.get("ShowTime", "")
                booking  = t.get("BookingUrl", "")

                key = show_key(vname, showtime, screen)
                if key not in seen:
                    seen.add(key)
                    new_found.append({
                        "venue":  vname,
                        "screen": screen,
                        "time":   showtime,
                        "url":    booking or "https://in.bookmyshow.com",
                    })

    save_seen(seen)

    if new_found:
        for s in new_found:
            print(f"[NEW] {s['venue']} | {s['screen']} | {s['time']}")
            make_call(s)
    else:
        print("No new showtimes since last check.")


if __name__ == "__main__":
    poll()
