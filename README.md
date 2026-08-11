# Briefly

A private, minimalist briefing station and alarm clock. CS 147 final project.

Tell it what you care about in plain English; type `update` to refresh. It
shows glanceable cards (weather, next event, headlines, your topics), rings
alarms that live on the chip, and snoozes when you knock the case. All AI runs
locally on your own laptop — no request ever leaves the network.

```
firmware/   ESP32 firmware (C++/PlatformIO)     - complete, unchanged since v1
gateway/    service.py + app.py + Gemma layer   - complete
mosquitto/  broker config
tools/      virtual_device.py, publish_test_card.py
azure/      Function App for cloud analytics
```

## Quick start

```bash
# 1. broker (terminal 1)
cd mosquitto
mosquitto_passwd -c passwd stationuser        # set the MQTT password
mosquitto -c mosquitto.conf -v

# 2. gateway (terminal 2)
cd gateway
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp secrets.example.json secrets.json                  # then edit it
python service.py

# 3. dashboard (terminal 3)
cd gateway && source .venv/bin/activate
streamlit run app.py

# 4. a device (terminal 4) - real board, or this if you don't have one:
python tools/virtual_device.py
```

## Working without the hardware

`tools/virtual_device.py` speaks the exact MQTT protocol the firmware speaks —
same topics, same payloads — and draws both screens as ASCII. Commands:
`knock`, `update`, `next`, `dismiss`, `ring`, `temp`, `quit`. Everything in the
gateway (cards, chat, alarms, analytics) can be built and demoed with it, so
whoever isn't holding the board is never blocked.

## The chat, layered on purpose

| You type | What happens | Model involved? |
|---|---|---|
| `update` | refresh every card now | **no** — exact string match |
| `alarm 7:00`, `wake me at 7am` | sets the on-chip alarm | **no** — regex |
| `clear alarms` | clears alarms | **no** |
| "I care about the Lakers and Bitcoin" | maps onto catalog sources, rewrites config | Gemma, with alias fallback |
| "how tall is the Eiffel Tower?" | answer pushed as a 10-minute card | Gemma only |

The commands you use daily can never be broken by a model. That's the design.

## Gemma (optional, off by default)

1. Install Ollama (ollama.com), then pull a model. **Check the exact tag** with
   `ollama list` / the model library and put it in `config.json` → `gemma.model`.
2. Settings tab → toggle **Enable Gemma**.

Three jobs: condensing raw feeds into 21-character card lines, mapping
preference sentences onto catalog keys, and answering one-off questions.
Every path has a deterministic fallback and a hard timeout — if Ollama is off,
slow, or returns nonsense, you get the plain formatted card instead of an error.

**Why the model never writes URLs:** `catalog.py` holds the real feeds; Gemma
may only pick *keys* from it. Hallucinated sources are impossible by
construction. To support something new, add one line to `catalog.py`.

## Cloud analytics

`azure/` is a Function App: a daily timer rolls raw IoT Hub event blobs into
per-day aggregates in Table Storage, and an HTTP endpoint serves the last 30
days as JSON. Put that URL in `secrets.json` → `azure_function_url` and the
dashboard's Analytics tab renders it. Full deployment steps in `azure/README.md`.

The Analytics tab also charts locally from `state/events.log` (events per day,
interactions by hour, indoor climate) so you have visuals before Azure is up.

## MQTT topics

| topic | direction | payload |
|---|---|---|
| `station/cards` | gateway → device (retained) | `{"v":1,"cards":[{"id","title","line1","line2"}]}` |
| `station/command` | gateway → device | `set_alarm` / `clear_alarms` / `beep` |
| `station/event` | device → gateway | `boot` / `knock` / `key` / `alarm` actions |
| `station/telemetry` | device → gateway | `{"tempF":71.2,"rh":48}` |
| `gateway/control` | dashboard → service | `refresh` / `temp_card` / `clear_temp` |

Watch everything: `mosquitto_sub -h localhost -u stationuser -P <pw> -t '#' -v`

## Verified

Card build, 21-char clamping, preference parsing (with and without Gemma),
negation handling, model-output parsing (code fences / prose / garbage), and a
full loop against a real Mosquitto broker: retained cards reaching a late-
joining device, device→gateway events, gateway→device commands, payload size
vs. the firmware's 4096-byte buffer (386 bytes typical). The **firmware itself
is unchanged from v1** — your partner can keep flashing the same build.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Connection refused` on any MQTT call | Mosquitto isn't running, or 2.x is still localhost-only — use `mosquitto/mosquitto.conf` |
| Broker: "Unable to open pwfile" | it dropped privileges; make `passwd` readable (`chmod 644`) or run the broker as your own user |
| Device connects, no cards | is `service.py` running? check `mosquitto_sub -t station/cards -v` |
| Gemma slow or timing out | raise `gemma.timeout_s`, or use a smaller model tag |
| Cards show odd text with Gemma on | turn off "Let Gemma write the card lines" — deterministic formatting returns |
| Streamlit edits don't reach the device | the service hot-reloads `config.json` on each refresh; press Refresh now |

## Repo hygiene

`gateway/secrets.json`, `firmware/include/secrets.h`, and
`azure/local.settings.json` are gitignored. Never commit Wi-Fi, MQTT, Azure, or
calendar credentials.
