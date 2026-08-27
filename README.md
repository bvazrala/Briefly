# Briefly

An ESP32 desk station that answers questions out loud on a small OLED, driven by a
locally-hosted language model. Sensor readings and user interactions are forwarded to
Azure IoT Hub, aggregated daily by an Azure Function, and charted on a Streamlit
dashboard.

---

## Demo

[![Briefly demo](https://img.youtube.com/vi/FEe-nwqJ1Is/maxresdefault.jpg)]([https://youtu.be/VIDEO_ID](https://youtu.be/FEe-nwqJ1Is))

---

## What it does

A LILYGO TTGO ESP32 on the desk reads temperature and humidity, detects knocks and
capacitive touches, and shows short "cards" on its OLED. It talks over WiFi to a local
MQTT broker. A Python gateway on a laptop subscribes to that broker, runs a local
Gemma 4 model through Ollama in a tool-calling loop, and pushes rendered cards back to
the device.

Every event the device emits is also forwarded to Azure IoT Hub. IoT Hub message
routing archives the raw events as JSON in Blob Storage; an Azure Function rolls them
into per-day aggregates in Table Storage and serves those aggregates over HTTP to the
dashboard. The analytics run in the cloud, not on the laptop — the dashboard only
renders the result.

---

## Architecture

```
  ┌──────────────────┐
  │  ESP32 station   │   SSD1306 OLED · CAP1188 touch
  │  (LILYGO TTGO)   │   LSM6DSO IMU · DHT20 temp/RH
  └────────┬─────────┘
           │ WiFi + MQTT
           ▼
  ┌──────────────────┐
  │ Mosquitto broker │   local, password-protected
  └────────┬─────────┘
           │
           ▼
  ┌──────────────────────────────────────────┐
  │ Python gateway  (laptop)                 │
  │                                          │
  │   mqtt_link.py  ── broker I/O            │
  │   brain.py      ── Gemma 4 via Ollama,   │
  │                    tool-calling loop     │
  │   tools.py      ── tool schemas          │
  │   fetchers.py   ── external data         │
  │   catalog.py    ── card catalog          │
  │   cloud.py      ── D2C REST forwarding   │
  │   service.py    ── main service loop     │
  │   app.py        ── Streamlit dashboard   │
  └────────┬─────────────────────────┬───────┘
           │ HTTPS (REST)            │ HTTPS
           ▼                         │
  ┌──────────────────┐               │
  │ Azure IoT Hub    │               │
  │   cs47IotHub     │               │
  └────────┬─────────┘               │
           │ message route "to-blob" │
           │ (JSON, 60s batches)     │
           ▼                         │
  ┌──────────────────┐               │
  │ Blob Storage     │               │
  │   iot-events     │               │
  └────────┬─────────┘               │
           │                         │
           ▼                         │
  ┌──────────────────────────────┐   │
  │ Azure Function               │   │
  │   daily_rollup  (timer)      │   │
  │   aggregates    (HTTP GET) ──┼───┘
  └────────┬─────────────────────┘
           │
           ▼
  ┌──────────────────┐
  │ Table Storage    │
  │  dailyaggregates │
  └──────────────────┘
```

### Why the model never touches the network

`brain.py` runs Gemma 4 locally through Ollama. The model's only job is to choose a
tool and its arguments. It does not emit URLs, headers, or request bodies. The gateway
validates the model's choice against a schema in `tools.py` and constructs every
outbound request itself. A malformed or hallucinated tool call fails validation and is
discarded rather than executed.

---

## Hardware

| Component | Role |
|---|---|
| LILYGO TTGO ESP32 | MCU, WiFi |
| SSD1306 OLED | Card display |
| CAP1188 | Capacitive touch input |
| LSM6DSO | IMU — knock detection |
| DHT20 | Temperature and humidity |

<!-- TODO: add wiring table or Fritzing diagram — pin assignments live in firmware/include/config.h -->

---

## Repository layout

```
firmware/
  include/config.h              pin map and tuning constants
  include/secrets_example.h     template — copy to secrets.h
  src/main.cpp                  device firmware
  platformio.ini                PlatformIO build config

gateway/
  service.py                    main loop: MQTT in, cards out, cloud forward
  mqtt_link.py                  broker connection
  brain.py                      Ollama tool-calling loop
  tools.py                      tool schemas and validation
  fetchers.py                   external data sources
  catalog.py                    card catalog
  cloud.py                      IoT Hub device-to-cloud REST sender
  app.py                        Streamlit dashboard
  config.json                   non-secret configuration
  secrets.example.json          template — copy to secrets.json
  requirements.txt

azure/
  function_app.py               daily_rollup + aggregates (Python v2 model)
  host.json
  requirements.txt
  local.settings.example.json
  README.md                     deployment notes

mosquitto/
  mosquitto.conf                broker config
  passwd                        broker credentials (gitignored)

tools/
  virtual_device.py             simulates the ESP32 for testing without hardware
  publish_test_card.py          publishes a single card to the device
```

---

## MQTT topics

| Topic | Direction | Payload |
|---|---|---|
| `station/telemetry` | device → gateway | `{"topic": "station/telemetry", "tempF": 72.4, "rh": 46}` |
| `station/event` | device → gateway | `{"topic": "station/event", "type": "knock", "count": 2}` |

Event `type` values are `knock`, `key` (with an `id`, e.g. `update`), and `alarm`
(with an `action` of `ringing`, `snoozed`, or `dismissed`).

Telemetry is a periodic heartbeat, roughly once a minute. Events are user-initiated.
The rollup treats these differently — see [Design notes](#design-notes).

---

## Setup

### 1. Broker

```bash
mosquitto_passwd -c mosquitto/passwd stationuser
mosquitto -c mosquitto/mosquitto.conf
```

The generated `passwd` file is gitignored.

### 2. Gateway

Requires Python 3.11+ and [Ollama](https://ollama.com) with a Gemma 4 model pulled.

```bash
cd gateway
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp secrets.example.json secrets.json   # then fill it in — see Configuration
python service.py
```

Dashboard, in a second terminal with the same venv active:

```bash
streamlit run app.py
```

### 3. Firmware

```bash
cd firmware
cp include/secrets_example.h include/secrets.h   # add WiFi + MQTT credentials
pio run --target upload
pio device monitor
```

### 4. Testing without hardware

`tools/virtual_device.py` publishes to the same topics as the real device, so the
gateway and the whole cloud path can be exercised from a laptop alone:

```bash
python tools/virtual_device.py
```

---

## Configuration

`gateway/secrets.json` is gitignored and must be created from
`gateway/secrets.example.json`. Its shape:

```json
{
  "mqtt_host": "127.0.0.1",
  "mqtt_port": 1883,
  "mqtt_user": "stationuser",
  "mqtt_pass": "",
  "calendar_ics_url": "",  // Optional Calender Integration
  "azure_connection_string": "HostName=<hub>.azure-devices.net;DeviceId=<device>;SharedAccessKey=<key>",
  "azure_function_url": "https://<app>.azurewebsites.net/api/aggregates?code=<function-key>"
}
```

`azure_connection_string` is the IoT **device** connection string (IoT Hub → Devices →
your device). `azure_function_url` comes from the Function App after deployment
(Overview → `aggregates` → Get function URL → default). Both are credentials; neither
belongs in the repo.

---

### Resources

| Resource | Name |
|---|---|
| Resource group | `cs147group` (East US) |
| IoT Hub | `cs47IotHub` |
| Device | `147esp32` |
| Storage account | `cs147briefly` |
| Blob container | `iot-events` |
| Table | `dailyaggregates` |
| Function App | `cs147briefly-fn` (Flex Consumption, Linux, Python 3.12) |

### Ingestion

`gateway/cloud.py` posts each event to the IoT Hub device-to-cloud REST endpoint with
`iothub-contenttype: application/json` and `iothub-contentencoding: utf-8`. A
successful send returns HTTP 204. Those two headers are what cause IoT Hub to store
`Body` as a JSON object rather than a base64 string.

Plain REST is deliberate. The `azure-iot-device` SDK pins paho-mqtt 1.x, which would
break the gateway's broker client — see [Design notes](#design-notes).

### Routing

An IoT Hub message route named `to-blob` sends all device telemetry
(`routing query: true`) to a custom Storage endpoint `iot-events-blob`, writing into
the `iot-events` container.

Endpoint settings that matter:

- **Encoding: JSON.** Defaults to AVRO and **cannot be changed after the endpoint is
  created** — a wrong choice here means deleting and recreating the endpoint.
- **Batch frequency: 60s**, chunk size 10 MB. The 300s default makes testing painful.

Blobs land under `cs47IotHub/{partition}/{YYYY}/{MM}/{DD}/{HH}/{mm}.json` as
newline-delimited JSON, one record per line.

Note that once a custom route with query `true` exists, telemetry stops flowing to the
built-in `events` endpoint. That is expected here; nothing reads from built-in.

### Function

Deployed from `azure/`:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
func azure functionapp publish cs147briefly-fn --python --build remote
```

Python 3.12 specifically: remote build is not yet supported for Python 3.14 on Flex
Consumption, and remote build is what produces the Linux wheels.

Required app settings on the Function App:

| Setting | Value |
|---|---|
| `STORAGE_CONNECTION_STRING` | connection string for `cs147briefly` |
| `EVENTS_CONTAINER` | `iot-events` |
| `AGGREGATE_TABLE` | `dailyaggregates` |

**`daily_rollup`** — timer trigger, 08:30 UTC. Lists blobs in `iot-events` from the
last 30 days, parses every record, aggregates by day, and upserts one row per day into
Table Storage. Idempotent: rerunning it recomputes and overwrites the same rows.

**`aggregates`** — HTTP GET, function-key auth. Returns the most recent 30 day rows as
JSON for the dashboard.

Response shape:

```json
[
  {
    "events": 4,
    "knocks": 4,
    "updates": 0,
    "snoozes": 0,
    "dismissals": 0,
    "alarms_rung": 0,
    "avg_tempF": 72.8,
    "avg_rh": 51.2,
    "day": "2026-08-25"
  }
]
```

To trigger the rollup on demand rather than waiting for the timer: Function App →
Overview → `daily_rollup` → Code + Test → Test/Run → Run.

---

## Design notes

**paho-mqtt 2.x is a hard constraint.** The gateway's broker client requires
paho-mqtt 2.x. `azure-iot-device` depends on paho-mqtt 1.x, so installing it would
silently break MQTT. Cloud forwarding therefore uses plain HTTPS REST in `cloud.py`
and `azure-iot-device` is never added to any requirements file.

**Telemetry is excluded from the event count.** The heartbeat produces roughly 1440
records per day. Counting it in `events` would swamp the user-initiated knocks and
alarm interactions and flatten the dashboard chart, so `_aggregate()` skips records on
`station/telemetry` when incrementing `events`. Those records still feed `avg_tempF`
and `avg_rh`.

**Two Body shapes.** Telemetry records carry `tempF` and `rh`; event records carry
`type` and `count`. There is no field common to both, so the parser branches rather
than assuming a fixed schema. `_records_from_blob()` also handles a base64 `Body`,
which is what IoT Hub produces if the content-type headers are ever dropped — the
tolerant parse means a misconfigured route degrades instead of crashing.

**Aggregates bucket by UTC date.** `EnqueuedTimeUtc` is UTC, so events generated after
5 PM Pacific land in the next day's row. This is correct but can look wrong on the
dashboard during an evening demo.

---

## License

See [LICENSE](LICENSE).
