"""MQTT connection for the gateway service.

Topics:
  station/cards      gateway -> device (retained card set)
  station/command    gateway -> device (alarms, beeps)
  station/event      device -> gateway (knock, keys, alarm actions, boot)
  station/telemetry  device -> gateway (temp/humidity)
  gateway/control    dashboard -> service (refresh requests)
"""
import json
import paho.mqtt.client as mqtt

T_CARDS, T_COMMAND = "station/cards", "station/command"
T_EVENT, T_TELEMETRY, T_CONTROL = "station/event", "station/telemetry", "gateway/control"


class Link:
    def __init__(self, host, port, user, password, on_event=None, on_control=None):
        self.host, self.port = host, int(port)
        self.on_event, self.on_control = on_event, on_control
        self.c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="gateway-service")
        self.c.username_pw_set(user, password)
        self.c.on_connect = self._connected
        self.c.on_message = self._message

    def _connected(self, client, userdata, flags, reason_code, properties):
        print(f"[mqtt] connected to {self.host} ({reason_code})")
        client.subscribe([(T_EVENT, 0), (T_TELEMETRY, 0), (T_CONTROL, 0)])

    def _message(self, client, userdata, msg):
        try:
            obj = json.loads(msg.payload.decode("utf-8", "replace"))
        except Exception:
            print(f"[mqtt] non-JSON on {msg.topic}: {msg.payload[:80]!r}")
            return
        if msg.topic == T_CONTROL:
            if self.on_control:
                self.on_control(obj)
        elif self.on_event:
            self.on_event(msg.topic, obj)

    def start(self):
        self.c.connect(self.host, self.port, keepalive=60)
        self.c.loop_start()

    def publish_cards(self, cards):
        payload = json.dumps({"v": 1, "cards": cards})
        self.c.publish(T_CARDS, payload, qos=1, retain=True)

    def publish_command(self, cmd: dict):
        self.c.publish(T_COMMAND, json.dumps(cmd), qos=1)
