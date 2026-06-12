"""
PVR Cinemas IMAX showtime poller → Twilio phone call notifier
Polls for The Odyssey IMAX at PVR Palazzo Chennai on 20 July 2026.

GitHub Secrets needed:
  TWILIO_SID       – from twilio.com/console (ACxxxx...)
  TWILIO_TOKEN     – from twilio.com/console
  TWILIO_FROM      – your Twilio number e.g. +12015551234
  MY_PHONE         – your Indian mobile e.g. +919876543210
"""

import json
import os
import hashlib
import requests
from datetime import datetime, timezone
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
TARGET_DATE      = "2026-07-20"
TARGET_FILM_CODE = "35098"          # The Odyssey on PVR
TARGET_CINEMA    = "Palazzo"        # will match "PVR: Palazzo, The Nexus Vijaya Mall"
STATE_FILE       = Path("seen_shows.json")

TWILIO_SID   = os.environ["TWILIO_SID"]
TWILIO_TOKEN = os.environ["TWILIO_TOKEN"]
TWILIO_FROM  = os.environ["TWILIO_FROM"]
MY_PHONE     = os.environ["MY_PHONE"]

PVR_API = "https://api3.pvrcinemas.com/api/v1/booking/content/mshowtimes"

HEADERS = {
    "accept":              "application/json, text/plain, */*",
    "accept-language":     "en-US,en;q=0.9",
    "appversion":          "1.0",
    "chain":               "PVR",
    "city":                "Chennai",
    "content-type":        "application/json",
    "country":             "INDIA",
    "origin":              "https://www.pvrcinemas.com",
    "platform":            "WEBSITE",
    "priority":            "u=1, i",
    "sec-ch-ua":           '"Google Chrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
    "sec-ch-ua-mobile":    "?0",
    "sec-ch-ua-platform":  '"macOS"',
    "sec-fetch-dest":      "empty",
    "sec-fetch-mode":      "cors",
    "sec-fetch-site":      "same-site",
    "user-agent":          "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
}

PAYLOAD = {
    "city":       "Chennai",
    "lat":        "12.883208",
    "lng":        "80.3613280",
    "dated":      TARGET_DATE,
    "experience": "imax",
}


def load_seen() -> set:
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text()))
    return set()


def save_seen(seen: set):
    STATE_FILE.write_text(json.dumps(sorted(seen)))


def show_key(cinema: str, time: str, film: str) -> str:
    return hashlib.md5(f"{cinema}|{time}|{film}".encode()).hexdigest()


def make_call(cinema: str, showtime: str, film_name: str):
    message = (
        f"Alert! Odyssey IMAX bookings are now open at {cinema}. "
        f"Show time: {showtime} on 20th July. "
        f"Open PVR Cinemas or BookMyShow immediately to grab your seat. "
        f"Repeating. "
        f"Odyssey IMAX is now open for booking at {cinema}. "
        f"Show time: {showtime}. Book now!"
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
        # Fallback ntfy push if call fails
        try:
            requests.post(
                "https://ntfy.sh/pvr-odyssey-imax-fallback",
                data=f"BOOK NOW — Odyssey IMAX @ {cinema} {showtime}".encode(),
                headers={"Title": "PVR IMAX LIVE!", "Priority": "urgent"},
                timeout=10,
            )
        except Exception:
            pass


def poll():
    print(f"[{datetime.now(timezone.utc).isoformat()}] Polling PVR API for {TARGET_DATE}...")

    try:
        resp = requests.post(PVR_API, headers=HEADERS, data=json.dumps(PAYLOAD), timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[ERROR] PVR API request failed: {e}")
        return

    output = data.get("output", {})
    days   = output.get("days", [])

    if not days:
        print("No showtimes found yet for July 20.")
        return

    seen      = load_seen()
    new_found = []

    for day in days:
        for cinema_entry in day.get("cinemas", []):
            cinema_name = cinema_entry.get("cinemaName", "")

            # Only care about Palazzo
            if TARGET_CINEMA.lower() not in cinema_name.lower():
                continue

            for show in cinema_entry.get("shows", []):
                film_code = str(show.get("filmCommonCode", ""))
                film_name = show.get("filmName", "")

                # Only care about The Odyssey
                if film_code != TARGET_FILM_CODE:
                    continue

                for session in show.get("showTimes", []):
                    showtime = session.get("showTime", "")
                    key      = show_key(cinema_name, showtime, film_name)

                    if key not in seen:
                        seen.add(key)
                        new_found.append({
                            "cinema":   cinema_name,
                            "film":     film_name,
                            "showtime": showtime,
                        })

    save_seen(seen)

    if new_found:
        for s in new_found:
            print(f"[NEW] {s['cinema']} | {s['film']} | {s['showtime']}")
            make_call(s["cinema"], s["showtime"], s["film"])
    else:
        print(f"Odyssey IMAX found in response but no Palazzo shows yet.")


if __name__ == "__main__":
    poll()
