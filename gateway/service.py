"""Briefly gateway service.

Run it and leave it running:
    python service.py

Responsibilities:
  * refresh cards on a timer, on a device knock, on an update key, or on a
    dashboard request
  * publish the card set (retained, so a rebooting device gets it instantly)
  * log every device event to state/events.log for the analytics tab
  * forward events + telemetry to Azure IoT Hub when configured
  * hold a temporary "answer" card at the front of the deck for a few minutes
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


def load_json(name, required=False, default=None):
    p = BASE / name
    if not p.exists():
        if required:
            sys.exit(f"Missing {p}. Copy secrets.example.json to secrets.json and edit it.")
        return default if default is not None else {}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError as e:
        print(f"[service] {name} is not valid JSON ({e}); using defaults")
        return default if default is not None else {}


def main():
    sec = load_json("secrets.json", required=True)
    STATE.mkdir(exist_ok=True)

    refresh_now = threading.Event()
    azure = cloud.AzureLink(sec.get("azure_connection_string", ""))
    temp = {"card": None, "until": 0.0}

    def log_event(topic, obj):
        entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "topic": topic, **obj}
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
        kind = obj.get("type")
        print(f"[control] {obj}")
        if kind == "refresh":
            refresh_now.set()
        elif kind == "temp_card" and obj.get("card"):
            minutes = float(obj.get("minutes", 10))
            temp["card"] = obj["card"]
            temp["until"] = time.time() + minutes * 60
            refresh_now.set()
        elif kind == "clear_temp":
            temp["card"], temp["until"] = None, 0.0
            refresh_now.set()

    link = mqtt_link.Link(sec["mqtt_host"], sec.get("mqtt_port", 1883),
                          sec["mqtt_user"], sec["mqtt_pass"],
                          on_event=on_event, on_control=on_control)
    link.start()
    print("[service] running - Ctrl-C to stop")

    next_due = 0.0
    while True:
        if temp["card"] and time.time() > temp["until"]:
            temp["card"], temp["until"] = None, 0.0
            refresh_now.set()

        if time.time() >= next_due or refresh_now.is_set():
            refresh_now.clear()
            cfg = load_json("config.json")          # hot-reload dashboard edits
            try:
                cards = brain.build_cards(cfg, sec)
            except Exception as e:                   # never let one bad feed kill the loop
                print("[service] build_cards failed:", e)
                cards = []
            if temp["card"]:
                cards = [temp["card"]] + cards
            cards = cards[:8]

            link.publish_cards(cards)
            (STATE / "cards.json").write_text(json.dumps(
                {"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "cards": cards}, indent=2))
            print(f"[service] published {len(cards)} cards")
            next_due = time.time() + max(2, int(cfg.get("refresh_minutes", 15))) * 60
        time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[service] stopped")
