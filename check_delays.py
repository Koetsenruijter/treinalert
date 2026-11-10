"""Stuurt een pushbericht (via ntfy.sh) als een trein tussen Zwolle en
Hoogeveen (of andersom) 30 minuten of meer vertraging heeft."""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

NS_API_KEY = os.environ["NS_API_KEY"]
NTFY_TOPIC = os.environ["NTFY_TOPIC"]

URL = "https://gateway.apiportal.ns.nl/reisinformatie-api/api/v2/departures"
# (stationscode, naam, bestemming die op de route moet liggen)
ROUTES = [("ZL", "Zwolle", "Hoogeveen"), ("HGV", "Hoogeveen", "Zwolle")]
MIN_DELAY_MIN = 10
ALERT_ON_CANCEL = True  # ook een bericht bij uitval
STATE_FILE = Path(__file__).parent / "seen.json"
TIME_FMT = "%Y-%m-%dT%H:%M:%S%z"


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    state = {k: v for k, v in state.items() if v > cutoff}
    STATE_FILE.write_text(json.dumps(state, indent=1))


def departures(code):
    r = requests.get(
        URL,
        params={"station": code, "maxJourneys": 40},
        headers={"Ocp-Apim-Subscription-Key": NS_API_KEY},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["payload"]["departures"]


def notify(title, message):
    requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=message.encode("utf-8"),
        headers={"Title": title, "Priority": "high", "Tags": "train"},
        timeout=20,
    ).raise_for_status()


def main():
    state = load_state()
    now = datetime.now(timezone.utc).isoformat()

    for code, origin, dest in ROUTES:
        for dep in departures(code):
            route = [s.get("mediumName", "") for s in dep.get("routeStations", [])]
            if dest not in route:
                continue

            planned = datetime.strptime(dep["plannedDateTime"], TIME_FMT)
            actual = datetime.strptime(dep.get("actualDateTime", dep["plannedDateTime"]), TIME_FMT)
            delay = int((actual - planned).total_seconds() // 60)
            cancelled = dep.get("cancelled", False)

            is_late = delay >= MIN_DELAY_MIN
            if not (is_late or (cancelled and ALERT_ON_CANCEL)):
                continue

            number = dep.get("product", {}).get("number", "?")
            key = f"{planned.date()}-{number}-{code}"
            if key in state:
                continue

            kind = dep.get("product", {}).get("shortCategoryName", "Trein")
            if cancelled:
                title = f"Uitval {origin} - {dest}"
                msg = f"{kind} {number} van {planned:%H:%M} rijdt niet."
            else:
                title = f"{delay} min vertraging {origin} - {dest}"
                msg = (f"{kind} {number} van {planned:%H:%M} vertrekt pas om "
                       f"{actual:%H:%M} (+{delay} min).")
            notify(title, msg)
            state[key] = now
            print("Verstuurd:", title, msg)

    save_state(state)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("Fout:", e, file=sys.stderr)
        sys.exit(1)
