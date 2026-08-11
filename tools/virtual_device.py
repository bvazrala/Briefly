"""Virtual Briefly device - test the whole gateway with no hardware.

Your partner has the board? Run this instead. It speaks exactly the same MQTT
protocol as the firmware: subscribes to station/cards and station/command,
publishes station/event and station/telemetry, keeps alarms, and draws both
screens as ASCII so you can see what the real device would show.

    python tools/virtual_device.py

Then type commands at the prompt:
    knock      double-knock (snoozes a ringing alarm, else asks for a brief)
    update     the "request update" key
    next       cycle to the next card
    dismiss    dismiss a ringing alarm
    temp       send a fake telemetry reading now
    ring       force an alarm to ring (for testing the snooze path)
    quit
"""
import json
import pathlib
import sys
import threading
import time

import paho.mqtt.client as mqtt

SEC_PATH = pathlib.Path(__file__).resolve().parent.parent / "gateway" / "secrets.json"
if not SEC_PATH.exists():
    sys.exit("Copy gateway/secrets.example.json to gateway/secrets.json first.")
SEC = json.loads(SEC_PATH.read_text())

WIDTH = 21
state = {"cards": [], "cur": 0, "ringing": False, "alarms": [], "snooze_at": None}
lock = threading.Lock()


def draw():
    with lock:
        cards, cur, ringing = state["cards"], state["cur"], state["ringing"]
        alarms = list(state["alarms"])
    now = time.strftime("%H:%M")
    top = f" LCD  {now} " + ("  *** ALARM ***" if ringing else "")
    alarm_txt = ", ".join(a["time"] for a in alarms) or "no alarm"

    print("\n" + "=" * 34)
    print(top)
    print(f" wifi mqtt   {alarm_txt}")
    print("-" * 34)
    if ringing:
        print(" OLED |      ALARM!         |")
        print("      | knock 2x = snooze   |")
    elif not cards:
        print(" OLED | waiting for cards   |")
        print("      | knock = request     |")
    else:
        c = cards[cur % len(cards)]
        print(f" OLED |{c.get('title',''):^21}|")
        print(f"      |{c.get('line1',''):<21}|")
        print(f"      |{c.get('line2',''):<21}|")
        print(f"      | {cur % len(cards) + 1}/{len(cards)}")
    print("=" * 34)


def on_connect(client, userdata, flags, reason_code, properties):
    print(f"[device] connected ({reason_code})")
    client.subscribe([("station/cards", 0), ("station/command", 0)])
    client.publish("station/event", json.dumps(
        {"type": "boot", "oled": True, "touch": True, "imu": True, "dht20": True, "virtual": True}))


def on_message(client, userdata, msg):
    try:
        obj = json.loads(msg.payload.decode())
    except Exception:
        return
    if msg.topic == "station/cards":
        with lock:
            state["cards"] = obj.get("cards", [])
            state["cur"] = 0
        print(f"\n[device] received {len(state['cards'])} cards")
        draw()
    elif msg.topic == "station/command":
        t = obj.get("type")
        if t == "set_alarm":
            with lock:
                state["alarms"] = [a for a in state["alarms"] if a["time"] != obj.get("time")]
                state["alarms"].append({"time": obj.get("time", "07:00"),
                                        "days": obj.get("days", list(range(7)))})
            print(f"\n[device] alarm set for {obj.get('time')}")
            client.publish("station/event", json.dumps({"type": "alarm", "action": "set"}))
        elif t == "clear_alarms":
            with lock:
                state["alarms"], state["ringing"] = [], False
            print("\n[device] alarms cleared")
            client.publish("station/event", json.dumps({"type": "alarm", "action": "cleared"}))
        elif t == "beep":
            print("\n[device] *beep*")
        draw()


def alarm_thread(client):
    """Fire alarms at their minute, and honour the 5-minute snooze."""
    last_min = None
    while True:
        now = time.localtime()
        hhmm = time.strftime("%H:%M", now)
        with lock:
            snooze_at = state["snooze_at"]
            alarms = list(state["alarms"])
            ringing = state["ringing"]
        if hhmm != last_min:
            last_min = hhmm
            if not ringing and any(a["time"] == hhmm for a in alarms):
                with lock:
                    state["ringing"] = True
                print("\n[device] ALARM RINGING (type 'knock' to snooze)")
                client.publish("station/event", json.dumps({"type": "alarm", "action": "ringing"}))
                draw()
        if snooze_at and time.time() >= snooze_at:
            with lock:
                state["snooze_at"], state["ringing"] = None, True
            print("\n[device] snooze expired - ALARM RINGING again")
            client.publish("station/event", json.dumps({"type": "alarm", "action": "ringing"}))
            draw()
        time.sleep(2)


def telemetry_thread(client):
    import random
    while True:
        time.sleep(60)
        payload = {"tempF": round(random.uniform(68, 76), 1),
                   "rh": round(random.uniform(40, 55))}
        client.publish("station/telemetry", json.dumps(payload))


def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="virtual-device")
    client.username_pw_set(SEC["mqtt_user"], SEC["mqtt_pass"])
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(SEC["mqtt_host"], int(SEC.get("mqtt_port", 1883)), 60)
    client.loop_start()

    threading.Thread(target=alarm_thread, args=(client,), daemon=True).start()
    threading.Thread(target=telemetry_thread, args=(client,), daemon=True).start()

    print(__doc__)
    draw()
    while True:
        try:
            cmd = input("device> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break
        if cmd in ("quit", "exit", "q"):
            break
        elif cmd == "knock":
            with lock:
                ringing = state["ringing"]
            if ringing:
                with lock:
                    state["ringing"] = False
                    state["snooze_at"] = time.time() + 300
                client.publish("station/event", json.dumps({"type": "alarm", "action": "snoozed"}))
                print("[device] snoozed 5 min")
            else:
                client.publish("station/event", json.dumps({"type": "knock", "count": 2}))
                print("[device] knock sent - service should refresh")
            draw()
        elif cmd == "update":
            client.publish("station/event", json.dumps({"type": "key", "id": "update"}))
            print("[device] update key sent")
        elif cmd == "next":
            with lock:
                state["cur"] += 1
            draw()
        elif cmd == "dismiss":
            with lock:
                state["ringing"], state["snooze_at"] = False, None
            client.publish("station/event", json.dumps({"type": "alarm", "action": "dismissed"}))
            draw()
        elif cmd == "ring":
            with lock:
                state["ringing"] = True
            client.publish("station/event", json.dumps({"type": "alarm", "action": "ringing"}))
            draw()
        elif cmd == "temp":
            import random
            client.publish("station/telemetry", json.dumps(
                {"tempF": round(random.uniform(68, 76), 1), "rh": round(random.uniform(40, 55))}))
            print("[device] telemetry sent")
        elif cmd in ("help", "?", ""):
            print(__doc__)
        else:
            print("unknown - try: knock update next dismiss ring temp quit")

    client.loop_stop()
    client.disconnect()
    print("bye")


if __name__ == "__main__":
    main()
