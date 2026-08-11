# Cloud analytics (Azure)

Runs the analytics **in Azure**, not on the laptop — that's what course
requirement 4 asks for. The dashboard only renders the result.

```
device --MQTT--> gateway --IoT Hub--> [routing] --> Blob Storage
                                                        |
                                          daily_rollup (timer) --> Table Storage
                                                        |
                                          aggregates (HTTP) --> Streamlit chart
```

## Setup

1. **IoT Hub** (F1 free tier) → *Message routing* → add a route:
   - Endpoint: a **Blob Storage** container named `iot-events`
   - Data source: *Device Telemetry Messages*, query `true`
   - **Encoding: JSON** (not AVRO — the rollup handles both, but JSON is simpler)
   - Batch frequency 60 s / 100 MB (smallest chunks, fastest feedback)
2. **Function App**: Python 3.11, Consumption plan, same region.
3. App settings on the Function App: `STORAGE_CONNECTION_STRING` (the storage
   account holding `iot-events`), optionally `EVENTS_CONTAINER`,
   `AGGREGATE_TABLE`.
4. Deploy from this folder:
   ```bash
   func azure functionapp publish <your-function-app-name>
   ```
5. Copy the `aggregates` function URL (with its `?code=` key) into
   `gateway/secrets.json` as `azure_function_url`. The dashboard's Analytics
   tab will then show the cloud table.

## Local test

```bash
pip install -r requirements.txt
cp local.settings.example.json local.settings.json   # then edit
func start
```

Blobs take a few minutes to appear after the device sends its first event —
IoT Hub batches. The timer runs at 08:30 UTC; to test immediately, invoke
`daily_rollup` from the portal's *Test/Run*, or temporarily set
`run_on_startup=True`.

## What lands in the table

One row per day: total events, knocks, update requests, alarms rung, snoozes,
dismissals, average indoor temperature and humidity. That's the analytics
story for the final report — usage patterns over the quarter.
