"""Azure IoT Hub forwarding. Completely optional: with no connection string
in secrets.json this is a silent no-op, so milestones M1-M3 need zero cloud
setup. Add the device connection string later (Azure IoT Hub F1 free tier)
and every device event + telemetry reading flows upward unchanged."""
import json


class AzureLink:
    def __init__(self, conn_str: str):
        self.client = None
        if not conn_str:
            print("[azure] no connection string - cloud forwarding off (fine for M1-M3)")
            return
        try:
            from azure.iot.device import IoTHubDeviceClient
            self.client = IoTHubDeviceClient.create_from_connection_string(conn_str)
            self.client.connect()
            print("[azure] connected to IoT Hub")
        except Exception as e:
            print("[azure] disabled:", e)
            self.client = None

    def send(self, obj: dict):
        if not self.client:
            return
        try:
            from azure.iot.device import Message
            m = Message(json.dumps(obj))
            m.content_type = "application/json"
            m.content_encoding = "utf-8"
            self.client.send_message(m)
        except Exception as e:
            print("[azure] send failed:", e)
