"""Milestone M2 helper: push a sample card set to the device without the
service running. From the repo root:

    python tools/publish_test_card.py

Reads broker credentials from gateway/secrets.json. If the OLED shows these
cards, your device <-> broker <-> laptop loop works end to end.
"""
import json
import pathlib
import sys

import paho.mqtt.client as mqtt

sec_path = pathlib.Path(__file__).resolve().parent.parent / "gateway" / "secrets.json"
if not sec_path.exists():
    sys.exit("Copy gateway/secrets.example.json to gateway/secrets.json first.")
SEC = json.loads(sec_path.read_text())

CARDS = {"v": 1, "cards": [
    {"id": "hello", "title": "Hello!", "line1": "MQTT loop works",
     "line2": "milestone M2 done"},
    {"id": "next", "title": "Next step", "line1": "run service.py",
     "line2": "for live cards"},
]}

c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
c.username_pw_set(SEC["mqtt_user"], SEC["mqtt_pass"])
c.connect(SEC["mqtt_host"], int(SEC.get("mqtt_port", 1883)), 30)
c.loop_start()
info = c.publish("station/cards", json.dumps(CARDS), qos=1, retain=True)
info.wait_for_publish(5)
c.loop_stop()
c.disconnect()
print("Test cards published (retained). Check the OLED / press button B to cycle.")
