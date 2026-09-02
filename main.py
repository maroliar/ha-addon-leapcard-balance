import json
import os
import re
import sys
import time
from datetime import datetime

from paho.mqtt.publish import multiple as mqtt_publish_multiple

from leapcard_client import LeapCardClient, LeapCardLoginError

OPTIONS_PATH = "/data/options.json"
OUTPUT_PATH = "/data/leap_data.json"

DISCOVERY_TOPIC = "homeassistant/sensor/leapcard_balance/config"
STATE_TOPIC = "leapcard/state"
ATTRIBUTES_TOPIC = "leapcard/attributes"

DEVICE_INFO = {
    "identifiers": ["leapcard_balance_addon"],
    "name": "LeapCard Balance",
    "manufacturer": "maroliar",
}


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%d/%m/%Y - %H:%M:%S')}] {msg}", flush=True)


def load_options() -> dict:
    with open(OPTIONS_PATH, encoding="utf-8") as f:
        return json.load(f)


def parse_balance(raw: str) -> str:
    """Normalize the scraped balance (e.g. "€12.34", "12,34 €") to a plain
    numeric string, so the MQTT state stays numeric for HA statistics/graphs."""
    cleaned = re.sub(r"[^\d,.-]", "", raw.strip())
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    return cleaned


def publish_to_mqtt(mqtt_config: dict, data: dict) -> None:
    # TODO: username_pw_set() is always called, even with empty strings, when
    # mqtt.user/mqtt.pass are left blank. Some brokers with allow_anonymous
    # reject that; auth should be omitted entirely in that case.
    auth = {"username": mqtt_config["user"], "password": mqtt_config["pass"]}

    discovery_payload = {
        "name": "Leap Card",
        "unique_id": "leapcard_balance",
        "default_entity_id": "sensor.leapcard",
        "state_topic": STATE_TOPIC,
        "json_attributes_topic": ATTRIBUTES_TOPIC,
        "unit_of_measurement": "EUR",
        "device_class": "monetary",
        "icon": "mdi:credit-card-outline",
        "device": DEVICE_INFO,
    }

    attributes = {
        "name": data["name"],
        "generated_at": data["generated_at"],
        "card_number": data["card_number"],
        "history": data["history"],
    }

    messages = [
        {"topic": DISCOVERY_TOPIC, "payload": json.dumps(discovery_payload),
         "qos": 1, "retain": True},
        {"topic": STATE_TOPIC, "payload": data["balance"], "qos": 1, "retain": True},
        {"topic": ATTRIBUTES_TOPIC, "payload": json.dumps(attributes),
         "qos": 1, "retain": True},
    ]

    mqtt_publish_multiple(
        messages,
        hostname=mqtt_config["host"],
        port=mqtt_config["port"],
        auth=auth,
        client_id="leapcard_balance",
    )
    log("Published to MQTT (retained).")


def fetch_data(username: str, password: str) -> dict:
    client = LeapCardClient(username, password)
    log("Logging in...")
    client.login()

    name = client.get_name()
    balance_raw, _ = client.get_balance()
    balance = parse_balance(balance_raw)
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

    return data


def main() -> None:
    options = load_options()
    username = options["leapcard_username"]
    password = options["leapcard_password"]
    interval_minutes = options.get("update_interval_minutes", 1440)
    mqtt_config = options.get("mqtt", {})

    if not username or not password:
        log("ERROR: leapcard_username / leapcard_password not configured. "
            "Fill them in on the addon's Configuration tab.")
        sys.exit(1)

    if not mqtt_config.get("host"):
        log("ERROR: mqtt.host not configured. Fill in the MQTT section on "
            "the addon's Configuration tab (host, port, user, pass).")
        sys.exit(1)

    log(f"Addon started. Interval between queries: {interval_minutes} min.")

    while True:
        try:
            data = fetch_data(username, password)
            publish_to_mqtt(mqtt_config, data)
        except LeapCardLoginError as e:
            log(f"LOGIN ERROR: {e}")
        except Exception as e:  # noqa: BLE001
            log(f"UNEXPECTED ERROR: {e}")

        log(f"Waiting {interval_minutes} minutes until the next query...")
        time.sleep(interval_minutes * 60)


if __name__ == "__main__":
    main()