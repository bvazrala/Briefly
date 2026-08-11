"""Briefly cloud analytics - Azure Functions (Python v2 model).

Two functions:
  daily_rollup   timer, 08:30 UTC daily. Reads the raw event blobs that IoT Hub
                 message routing drops into Blob Storage, aggregates them per
                 day, and writes one row per day to Table Storage.
  aggregates     HTTP GET. Returns the last 30 daily rows as JSON, which the
                 Streamlit dashboard charts (set azure_function_url in
                 gateway/secrets.json).

This satisfies the course requirement for "data analytics and visualization
using available services at the cloud": the analytics run in Azure, not on the
laptop, and the dashboard only renders the result.

Deployment notes live in azure/README.md.
"""
import base64
import collections
import datetime
import json
import logging
import os

import azure.functions as func
from azure.data.tables import TableServiceClient
from azure.storage.blob import BlobServiceClient

app = func.FunctionApp()

CONN = os.environ.get("STORAGE_CONNECTION_STRING", "")
CONTAINER = os.environ.get("EVENTS_CONTAINER", "iot-events")
TABLE = os.environ.get("AGGREGATE_TABLE", "dailyaggregates")
PARTITION = "station"


def _records_from_blob(text):
    """IoT Hub routing writes newline-delimited JSON records. With the endpoint
    encoding set to JSON (and our messages tagged application/json + utf-8),
    Body arrives as a JSON object; older/AVRO-ish payloads arrive base64. Handle
    both so a misconfigured route still produces data instead of a crash."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        body = rec.get("Body", rec)
        if isinstance(body, str):
            try:
                body = json.loads(base64.b64decode(body).decode("utf-8"))
            except Exception:
                try:
                    body = json.loads(body)
                except Exception:
                    continue
        if not isinstance(body, dict):
            continue
        ts = (rec.get("EnqueuedTimeUtc") or rec.get("enqueuedTime") or "")[:10]
        out.append((ts, body))
    return out


def _aggregate(records):
    days = collections.defaultdict(lambda: {
        "events": 0, "knocks": 0, "updates": 0, "snoozes": 0, "dismissals": 0,
        "alarms_rung": 0, "temp_sum": 0.0, "temp_n": 0, "rh_sum": 0.0, "rh_n": 0,
    })
    for day, b in records:
        if not day:
            continue
        d = days[day]
        d["events"] += 1
        t = b.get("type")
        if t == "knock":
            d["knocks"] += 1
        elif t == "key" and b.get("id") == "update":
            d["updates"] += 1
        elif t == "alarm":
            a = b.get("action")
            if a == "snoozed":
                d["snoozes"] += 1
            elif a == "dismissed":
                d["dismissals"] += 1
            elif a == "ringing":
                d["alarms_rung"] += 1
        if "tempF" in b:
            try:
                d["temp_sum"] += float(b["tempF"]); d["temp_n"] += 1
            except (TypeError, ValueError):
                pass
        if "rh" in b:
            try:
                d["rh_sum"] += float(b["rh"]); d["rh_n"] += 1
            except (TypeError, ValueError):
                pass

    rows = []
    for day, d in sorted(days.items()):
        rows.append({
            "PartitionKey": PARTITION,
            "RowKey": day,
            "events": d["events"],
            "knocks": d["knocks"],
            "updates": d["updates"],
            "snoozes": d["snoozes"],
            "dismissals": d["dismissals"],
            "alarms_rung": d["alarms_rung"],
            "avg_tempF": round(d["temp_sum"] / d["temp_n"], 1) if d["temp_n"] else None,
            "avg_rh": round(d["rh_sum"] / d["rh_n"], 1) if d["rh_n"] else None,
        })
    return rows


@app.timer_trigger(schedule="0 30 8 * * *", arg_name="timer", run_on_startup=False)
def daily_rollup(timer: func.TimerRequest) -> None:
    if not CONN:
        logging.error("STORAGE_CONNECTION_STRING not set")
        return

    blobs = BlobServiceClient.from_connection_string(CONN)
    container = blobs.get_container_client(CONTAINER)
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30)

    records = []
    for b in container.list_blobs():
        if b.last_modified and b.last_modified < cutoff:
            continue
        try:
            text = container.download_blob(b.name).readall().decode("utf-8", "replace")
        except Exception as e:
            logging.warning("skip blob %s: %s", b.name, e)
            continue
        records.extend(_records_from_blob(text))

    rows = _aggregate(records)
    tables = TableServiceClient.from_connection_string(CONN)
    try:
        tables.create_table(TABLE)
    except Exception:
        pass  # already exists
    tc = tables.get_table_client(TABLE)
    for row in rows:
        tc.upsert_entity(row)
    logging.info("daily_rollup wrote %d day rows from %d records", len(rows), len(records))


@app.route(route="aggregates", auth_level=func.AuthLevel.FUNCTION, methods=["GET"])
def aggregates(req: func.HttpRequest) -> func.HttpResponse:
    if not CONN:
        return func.HttpResponse("storage not configured", status_code=500)
    try:
        tc = TableServiceClient.from_connection_string(CONN).get_table_client(TABLE)
        rows = [dict(e) for e in tc.query_entities(f"PartitionKey eq '{PARTITION}'")]
    except Exception as e:
        return func.HttpResponse(f"query failed: {e}", status_code=500)

    rows.sort(key=lambda r: r.get("RowKey", ""))
    out = [{k: v for k, v in r.items() if k not in ("PartitionKey", "Timestamp", "etag")}
           for r in rows[-30:]]
    for r in out:
        r["day"] = r.pop("RowKey", "")
    return func.HttpResponse(json.dumps(out), mimetype="application/json")
