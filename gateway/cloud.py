"""Azure IoT Hub forwarding over plain REST.

Why REST and not the official SDK: azure-iot-device pins the paho MQTT client
to version 1, while the gateway is written against version 2. The two cannot
share one environment. IoT Hub accepts device to cloud messages over HTTPS,
which needs nothing beyond requests and the standard library, so the conflict
disappears entirely.

Setup: create an IoT Hub (F1 free tier), register a device, and paste its
connection string into secrets.json as azure_connection_string. It looks like
HostName=<hub>.azure-devices.net;DeviceId=<id>;SharedAccessKey=<key>
With that field empty this module stays a silent no-op.
"""
import base64
import hashlib
import hmac
import json
import time
import urllib.parse
from typing import Optional

import requests

API_VERSION = "2021-04-12"


class AzureLink:
    def __init__(self, conn_str: str) -> None:
        self.host: Optional[str] = None
        self.device: Optional[str] = None
        self.key: Optional[str] = None
        self._token: str = ""
        self._token_expiry: float = 0.0

        if not conn_str:
            print("[azure] no connection string - cloud forwarding off")
            return
        try:
            parts = dict(p.split("=", 1) for p in conn_str.split(";") if "=" in p)
            self.host = parts["HostName"]
            self.device = parts["DeviceId"]
            self.key = parts["SharedAccessKey"]
            print(f"[azure] REST sender ready: {self.device} -> {self.host}")
        except Exception as e:
            print("[azure] connection string not understood:", e)
            self.host = None

    # --- SAS token, cached and refreshed shortly before it expires ---------
    def _sas(self) -> str:
        if not (self.host and self.device and self.key):
            return ""
        if time.time() < self._token_expiry - 120:
            return self._token
        uri = f"{self.host}/devices/{self.device}"
        expiry = int(time.time()) + 3600
        to_sign = (urllib.parse.quote_plus(uri) + "\n" + str(expiry)).encode()
        signature = base64.b64encode(
            hmac.new(base64.b64decode(self.key), to_sign, hashlib.sha256).digest()
        ).decode()
        self._token = (
            "SharedAccessSignature sr=" + urllib.parse.quote_plus(uri)
            + "&sig=" + urllib.parse.quote_plus(signature)
            + "&se=" + str(expiry)
        )
        self._token_expiry = float(expiry)
        return self._token

    # --- one event or telemetry reading -> one D2C message -----------------
    def send(self, obj: dict) -> None:
        if not self.host:
            return
        try:
            url = (f"https://{self.host}/devices/{self.device}"
                   f"/messages/events?api-version={API_VERSION}")
            r = requests.post(
                url,
                data=json.dumps(obj).encode("utf-8"),
                timeout=5,
                headers={
                    "Authorization": self._sas(),
                    "Content-Type": "application/json; charset=utf-8",
                    "iothub-contenttype": "application/json",
                    "iothub-contentencoding": "utf-8",
                },
            )
            if r.status_code not in (200, 201, 204):
                print(f"[azure] send failed: HTTP {r.status_code} {r.text[:120]}")
        except Exception as e:
            print("[azure] send failed:", e)
            