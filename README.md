# Briefing Station

Private, minimalist briefing assistant + alarm clock. CS 147 final project.

ESP32 device (clock, alarms, knock-to-snooze, card display) ⇄ MQTT over Wi-Fi ⇄
Python gateway on a laptop (fetches weather/calendar/news/topics, publishes
cards, forwards events to Azure). **No AI required to run this MVP** — the
Gemma integration is a clearly marked seam in `gateway/brain.py` for later.

```
firmware/    PlatformIO project (C++), complete           -> milestones M1-M3
gateway/     service.py (always-on) + app.py (Streamlit)  -> the brief
mosquitto/   broker config (auth + LAN listener)
tools/       publish_test_card.py (M2 sanity check)
```

## 0. Prerequisites (one-time installs)

* VS Code + the **PlatformIO** extension (compiles/flashes the firmware)
* **Python 3.11+**
* **Mosquitto** MQTT broker — macOS `brew install mosquitto`, Windows installer
  from mosquitto.org, Linux `sudo apt install mosquitto mosquitto-clients`
* A **phone hotspot** (campus eduroam fights ESP32s — don't bother)
* USB driver for the board if no serial port appears (CP210x or CH340 —
  whichever the board's product page names)

## 1. Broker (5 minutes)

```bash
cd mosquitto
mosquitto_passwd -c passwd stationuser        # pick the MQTT password here
mosquitto -c mosquitto.conf -v                # leave this terminal running
```

If `password_file ./passwd` errors on your OS, replace it with the absolute
path to the `passwd` file you just created.

## 2. Firmware (milestone M1)

1. Copy `firmware/include/secrets_example.h` → `firmware/include/secrets.h`,
   fill in hotspot SSID/password, your **laptop's IP on that hotspot**
   (macOS: `ipconfig getifaddr en0`), and the MQTT user/password from step 1.
2. Open the `firmware/` folder in VS Code → PlatformIO → **Upload**, then
   **Monitor** (115200 baud).
3. Expected serial output — this is M1 passing:

```
=== Briefing Station boot ===
[BOOT] OLED  0x3C  [OK]
[BOOT] CAP1188      [--] (touch pads optional)   <- fine before soldering
[BOOT] DHT20 0x38   [OK]
[BOOT] LSM6DSO knock[OK]
[WIFI] connected, ip 172.20.10.4
[MQTT] connected
```

The color LCD shows the clock (NTP-synced, Pacific time). Any `[--]`
peripheral is skipped gracefully — bring hardware up in stages.

## 3. Gateway (milestones M2-M3)

```bash
cd gateway
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp secrets.example.json secrets.json                  # then edit it
python ../tools/publish_test_card.py                  # M2: cards appear on OLED?
python service.py                                     # terminal 2: live cards
streamlit run app.py                                  # terminal 3: dashboard
```

`secrets.json`: `mqtt_host` is `127.0.0.1` (broker runs on this laptop);
`calendar_ics_url` is Google Calendar → Settings → *Secret address in iCal
format* (treat it like a password); leave `azure_connection_string` empty
until the Azure milestone.

## Using it

| You do | It does |
|---|---|
| type `update` in the dashboard chat | refreshes every card on the device |
| type `alarm 7:00` / `wake me at 7am` | sets the on-chip alarm |
| **double-knock the case** | snoozes a ringing alarm (5 min); otherwise requests a fresh brief |
| button A (GPIO0) short press | request update |
| button B (GPIO35) short press / touch pad 1 | next card |
| hold either button ~1.2 s / any touch pad | dismiss a ringing alarm |
| type `clear alarms` | clears alarms |

Alarms are stored in on-chip flash and time comes from NTP — **the clock and
alarms keep working with the laptop off.** Cards keep their last content
(retained MQTT) and the OLED footer shows live indoor temp/humidity.

## MQTT topics (for debugging with `mosquitto_sub -t 'station/#' -v`)

| topic | direction | payload |
|---|---|---|
| `station/cards` | gateway → device (retained) | `{"v":1,"cards":[{"id","title","line1","line2"}]}` |
| `station/command` | gateway → device | `set_alarm` / `clear_alarms` / `beep` |
| `station/event` | device → gateway | `boot` / `knock` / `key` / `alarm` actions |
| `station/telemetry` | device → gateway | `{"tempF":71.2,"rh":48}` every 5 min |
| `gateway/control` | dashboard → service | `{"type":"refresh"}` |

## Azure (later milestone)

Sign up for Azure for Students → create an **IoT Hub (F1 free tier)** →
register a device → paste its connection string into `secrets.json`. Every
event and telemetry message then flows up automatically (`gateway/cloud.py`).
Avoid IoT Central — it has a retirement notice; IoT Hub is the stable pillar.

## Gemma (later milestone)

One file: `gateway/brain.py`. Flip `USE_GEMMA`, implement
`condense_with_gemma()` (a working sketch is in its docstring), and keep the
deterministic formatters as the fallback. Nothing else in the system changes.

## Troubleshooting

| Symptom | Fix |
|---|---|
| No serial port | install the CP210x/CH340 driver; try another cable (data, not charge-only) |
| LCD stays black | build flags in `platformio.ini` are the TFT config — don't edit library files; check ribbon isn't damaged |
| `[MQTT] connect failed rc=-2` | wrong `MQTT_HOST` IP, broker not running, or Mosquitto still bound to localhost — use `mosquitto/mosquitto.conf` |
| Cards never render | you're publishing >256-byte JSON without our `setBufferSize(4096)` — already handled; check `mosquitto_sub -t station/cards -v` shows the payload |
| Wi-Fi won't connect | eduroam/WPA2-Enterprise — use the phone hotspot |
| Knock too sensitive / deaf | tap thresholds in `imuInitDoubleTap()` (`0x57/0x58/0x59`, higher = less sensitive) |
| Time shows `--:--` | NTP needs internet; hotspot data on? |

## Repo hygiene

`secrets.h` / `secrets.json` are gitignored — **never** commit Wi-Fi, MQTT,
Azure, or calendar credentials. Push everything else; the course wants the
GitHub link in both reports.
