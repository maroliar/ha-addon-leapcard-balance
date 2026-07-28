import json
import os
import time
import sys
from datetime import datetime

import requests

from leapcard_client import LeapCardClient, LeapCardLoginError

OPTIONS_PATH = "/data/options.json"
OUTPUT_PATH = "/data/leap_data.json"
ENTITY_ID = "sensor.leapcard"

# Injected by the Supervisor when homeassistant_api: true is set in config.yaml
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN")
CORE_API_URL = "http://supervisor/core/api"


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%d/%m/%Y - %H:%M:%S')}] {msg}", flush=True)


def load_options() -> dict:
    with open(OPTIONS_PATH, encoding="utf-8") as f:
        return json.load(f)


def push_to_ha(data: dict) -> None:
    if not SUPERVISOR_TOKEN:
        log("WARNING: SUPERVISOR_TOKEN not found - running outside the addon? "
            "Skipping publish to HA.")
        return

    auth_headers = {
        "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "state": data["balance"],
        "attributes": {
            "friendly_name": "Leap Card",
            "unit_of_measurement": "€",
            "name": data["name"],
            "generated_at": data["generated_at"],
            "card_number": data["card_number"],
            "history": data["history"],
        },
    }

    resp = requests.post(
        f"{CORE_API_URL}/states/{ENTITY_ID}",
        headers=auth_headers,
        json=payload,
        timeout=10,
    )

    if resp.status_code not in (200, 201):
        log(f"ERROR publishing to HA: {resp.status_code} - {resp.text[:200]}")
    else:
        log(f"Published to {ENTITY_ID} successfully.")


def run_once(username: str, password: str) -> None:
    client = LeapCardClient(username, password)
    log("Logging in...")
    client.login()

    name = client.get_name()
    balance, _ = client.get_balance()
    card_number = client.get_card_number()
    history = client.get_history()

    data = {
        "name": name,
        "generated_at": datetime.now().strftime("%d/%m/%Y - %H:%M:%S"),
        "balance": balance,
        "card_number": card_number,
        "history": history,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    log(f"OK - card {card_number} - balance: EUR{balance} - "
        f"{len(history)} transactions saved to {OUTPUT_PATH}")

    push_to_ha(data)


def main() -> None:
    options = load_options()
    username = options["leapcard_username"]
    password = options["leapcard_password"]
    interval_minutes = options.get("update_interval_minutes", 1440)

    if not username or not password:
        log("ERROR: leapcard_username / leapcard_password not configured. "
            "Fill them in on the addon's Configuration tab.")
        sys.exit(1)

    log(f"Addon started. Interval between queries: {interval_minutes} min.")

    while True:
        try:
            run_once(username, password)
        except LeapCardLoginError as e:
            log(f"LOGIN ERROR: {e}")
        except Exception as e:  # noqa: BLE001
            log(f"UNEXPECTED ERROR: {e}")

        log(f"Waiting {interval_minutes} minutes until the next query...")
        time.sleep(interval_minutes * 60)


if __name__ == "__main__":
    main()