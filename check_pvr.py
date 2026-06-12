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
TARGET_DATE = "2026-07-19"
TARGET_FILM_KEYWORD = "ODYSSEY"  # case-insensitive match on movie.filmName
TARGET_THEATRE_ID = "388"  # PVR Palazzo, The Nexus Vijaya Mall (API returns string)
TARGET_CINEMA = "Palazzo"  # fallback case-insensitive match on cinema.name
STATE_FILE = Path("call_attempts.json")
MAX_CALLS = 4

TWILIO_SID = os.environ["TWILIO_SID"]
TWILIO_TOKEN = os.environ["TWILIO_TOKEN"]
TWILIO_FROM = os.environ["TWILIO_FROM"]
MY_PHONE = os.environ["MY_PHONE"]

PVR_API = "https://api3.pvrcinemas.com/api/v1/booking/content/mshowtimes"

HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-US,en;q=0.9",
    "appversion": "1.0",
    "chain": "PVR",
    "city": "Chennai",
    "content-type": "application/json",
    "country": "INDIA",
    "origin": "https://www.pvrcinemas.com",
    "platform": "WEBSITE",
    "priority": "u=1, i",
    "sec-ch-ua": '"Google Chrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
}

PAYLOAD = {
    "city": "Chennai",
    "lat": "12.883208",
    "lng": "80.3613280",
    "dated": TARGET_DATE,
    "experience": "imax",
}


def load_attempts() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_attempts(attempts: dict):
    STATE_FILE.write_text(json.dumps(attempts, sort_keys=True))


def show_key(cinema: str, film: str) -> str:
    return hashlib.md5(f"{cinema}|{film}".encode()).hexdigest()


def make_call(cinema: str, film_name: str) -> bool:
    message = (
        f"Alert! Odyssey IMAX bookings are now open at {cinema} on 20th July. "
        f"Open PVR Cinemas or BookMyShow immediately to grab your seat. "
        f"Repeating. "
        f"Odyssey IMAX is now open for booking at {cinema}. Book now!"
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
        return True
    except Exception as e:
        print(f"[Twilio] Call failed: {e}")
        # Fallback ntfy push if call fails
        try:
            requests.post(
                "https://ntfy.sh/pvr-odyssey-imax-fallback",
                data=f"BOOK NOW — Odyssey IMAX @ {cinema}".encode(),
                headers={"Title": "PVR IMAX LIVE!", "Priority": "urgent"},
                timeout=10,
            )
        except Exception:
            pass
        return False


def poll():
    print(
        f"[{datetime.now(timezone.utc).isoformat()}] Polling PVR API for {TARGET_DATE}..."
    )

    try:
        resp = requests.post(PVR_API, headers=HEADERS, json=PAYLOAD, timeout=15)

        print("Status:", resp.status_code)
        print("Headers:", resp.headers)
        print("Body:", resp.text[:1000])

        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[ERROR] PVR API request failed: {e}")
        return

    output = data.get("output", {})
    show_time_sessions = output.get("showTimeSessions", [])

    if not show_time_sessions:
        print("No showtimes found yet for July 20.")
        return

    attempts = load_attempts()
    to_call = []

    for session_entry in show_time_sessions:
        movie = session_entry.get("movie") or {}
        film_name = movie.get("filmName", "") or ""

        # Only care about The Odyssey
        if TARGET_FILM_KEYWORD.lower() not in film_name.lower():
            continue

        for cinema_session in session_entry.get("movieCinemaSessions", []) or []:
            cinema = cinema_session.get("cinema") or {}
            theatre_id = str(cinema.get("theatreId", ""))
            cinema_name = cinema.get("name", "") or ""

            # Only care about Palazzo (by theatreId or name)
            is_palazzo = theatre_id == TARGET_THEATRE_ID or (
                TARGET_CINEMA.lower() in cinema_name.lower()
            )
            if not is_palazzo:
                continue

            key = show_key(cinema_name, film_name)
            count = attempts.get(key, 0)
            if count >= MAX_CALLS:
                print(
                    f"[SKIP] {cinema_name} | {film_name} — {count}/{MAX_CALLS} calls already made"
                )
                continue
            to_call.append({"key": key, "cinema": cinema_name, "film": film_name})

    if to_call:
        for s in to_call:
            count = attempts.get(s["key"], 0)
            print(f"[CALL {count + 1}/{MAX_CALLS}] {s['cinema']} | {s['film']}")
            if make_call(s["cinema"], s["film"]):
                attempts[s["key"]] = count + 1
        save_attempts(attempts)
    else:
        print(
            "No Palazzo shows to call (none found, or all snoozed after max attempts)."
        )


if __name__ == "__main__":
    poll()
