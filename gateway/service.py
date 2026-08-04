"""Briefing Station gateway service.

Run this in a terminal and leave it running:
    python service.py

It refreshes cards every `refresh_minutes` (config.json), immediately on a
device knock / update key / dashboard refresh, writes state/cards.json and
state/events.log for the Streamlit app, and forwards events + telemetry to
Azure when a connection string is configured.
"""
import json
import pathlib
import sys
import threading
import time

import brain
import cloud
import mqtt_link

BASE = pathlib.Path(__file__).resolve().parent
STATE = BASE / "state"


def load_json(name, required=False):
    p = BASE / name
    if not p.exists():
        if required:
            sys.exit(f"Missing {p}. Copy secrets.example.json to secrets.json and edit it.")
        return {}
    return json.loads(p.read_text())


def main():
    cfg = load_json("config.json")
    sec = load_json("secrets.json", required=True)

    STATE.mkdir(exist_ok=True)
    refresh_now = threading.Event()
    azure = cloud.AzureLink(sec.get("azure_connection_string", ""))

    def log_event(topic, obj):
        entry = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "topic": topic, **obj}
        with open(STATE / "events.log", "a") as f:
            f.write(json.dumps(entry) + "\n")

    def on_event(topic, obj):
        print(f"[event] {topic}: {obj}")
        log_event(topic, obj)
        azure.send({"topic": topic, **obj})
        t = obj.get("type")
        if t == "knock" or (t == "key" and obj.get("id") == "update"):
            refresh_now.set()

    def on_control(obj):
        print(f"[control] {obj}")
        if obj.get("type") == "refresh":
            refresh_now.set()

    link = mqtt_link.Link(sec["mqtt_host"], sec.get("mqtt_port", 1883),
                          sec["mqtt_user"], sec["mqtt_pass"],
                          on_event=on_event, on_control=on_control)
    link.start()

    next_due = 0.0
    while True:
        if time.time() >= next_due or refresh_now.is_set():
            refresh_now.clear()
            cfg = load_json("config.json")  # pick up dashboard edits live
            cards = brain.build_cards(cfg, sec)
            link.publish_cards(cards)
            (STATE / "cards.json").write_text(json.dumps(
                {"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "cards": cards},
                indent=2))
            print(f"[service] published {len(cards)} cards")
            next_due = time.time() + max(2, int(cfg.get("refresh_minutes", 15))) * 60
        time.sleep(1)


if __name__ == "__main__":
    main()
