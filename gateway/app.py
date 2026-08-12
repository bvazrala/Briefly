"""Briefly dashboard.

    streamlit run app.py

Three tabs:
  Brief     - what the device is showing, refresh/beep/alarm controls, chat
  Analytics - charts from device events + indoor climate (and cloud aggregates)
  Settings  - topics, location, Gemma status

The chat router is deliberately layered: the commands you use every day
("update", alarm phrases) are hard-coded string/regex matches that never touch
a model, so they cannot fail. Only free-form sentences reach Gemma.
"""
import json
import pathlib
import re

import pandas as pd
import paho.mqtt.client as mqtt
import requests
import streamlit as st

import brain
import catalog
import tools

BASE = pathlib.Path(__file__).resolve().parent


def load_json(name, default=None):
    try:
        return json.loads((BASE / name).read_text())
    except Exception:
        return default


def save_cfg(cfg):
    (BASE / "config.json").write_text(json.dumps(cfg, indent=2))


SEC = load_json("secrets.json")
if not SEC:
    st.error("Missing gateway/secrets.json - copy secrets.example.json and edit it.")
    st.stop()


def publish_once(topic, obj):
    try:
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        c.username_pw_set(SEC["mqtt_user"], SEC["mqtt_pass"])
        c.connect(SEC["mqtt_host"], int(SEC.get("mqtt_port", 1883)), 30)
        c.loop_start()
        c.publish(topic, json.dumps(obj), qos=1).wait_for_publish(5)
        c.loop_stop()
        c.disconnect()
        return True
    except Exception as e:
        st.error(f"MQTT publish failed: {e}  (is Mosquitto running?)")
        return False


def set_alarm(hh, mm, days):
    return publish_once("station/command",
                        {"type": "set_alarm", "time": f"{hh:02d}:{mm:02d}", "days": days})


def read_events():
    p = BASE / "state" / "events.log"
    if not p.exists():
        return pd.DataFrame()
    rows = []
    for line in p.read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["ts"], errors="coerce")
    return df.dropna(subset=["ts"])


st.set_page_config(page_title="Briefly", page_icon="🗞️", layout="wide")
st.title("Briefly")

CFG = load_json("config.json", {}) or {}
tab_brief, tab_analytics, tab_settings = st.tabs(["Brief", "Analytics", "Settings"])

# ================================================================== BRIEF ===
with tab_brief:
    state = load_json("state/cards.json")
    if state:
        st.caption(f"Cards generated {state.get('generated', '?')}")
        cards = state.get("cards", [])
        cols = st.columns(min(4, max(1, len(cards))))
        for i, c in enumerate(cards):
            with cols[i % len(cols)]:
                st.markdown(f"**{c.get('title','')}**")
                st.code(f"{c.get('line1','')}\n{c.get('line2','')}", language=None)
    else:
        st.info("No cards yet. Run `python service.py` in another terminal, then Refresh.")

    c1, c2, c3, c4 = st.columns(4)
    if c1.button("Refresh now", use_container_width=True):
        if publish_once("gateway/control", {"type": "refresh"}):
            st.success("Refresh requested.")
    if c2.button("Test beep", use_container_width=True):
        publish_once("station/command", {"type": "beep"})
    if c3.button("Clear alarms", use_container_width=True):
        publish_once("station/command", {"type": "clear_alarms"})
    if c4.button("Clear answer card", use_container_width=True):
        publish_once("gateway/control", {"type": "clear_temp"})

    with st.expander("Set an alarm"):
        t = st.time_input("Time")
        daynames = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        picked = st.multiselect("Days", daynames, default=daynames)
        if st.button("Set alarm"):
            if set_alarm(t.hour, t.minute, [daynames.index(d) for d in picked]):
                st.success(f"Alarm set for {t.strftime('%H:%M')}.")

    st.divider()
    ALARM_RE = re.compile(
        r"(?:alarm|wake me(?: up)?)(?:\s*(?:at|for))?\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?",
        re.IGNORECASE)

    chat = st.chat_input("Try: update  ·  alarm 7:00  ·  I care about the Steelers and SpaceX stock")
    if chat:
        txt = chat.strip()
        low = txt.lower()

        # ---- layer 1: hard-coded commands, no model involved ---------------
        if low == "update":
            if publish_once("gateway/control", {"type": "refresh"}):
                st.success("Updating all cards.")
        elif any(k in low for k in ("clear alarm", "alarms off", "no alarm")):
            publish_once("station/command", {"type": "clear_alarms"})
            st.success("Alarms cleared.")
        elif ALARM_RE.search(low):
            m = ALARM_RE.search(low)
            hh, mm = int(m.group(1)), int(m.group(2) or 0)
            ap = (m.group(3) or "").lower()
            if ap == "pm" and hh < 12:
                hh += 12
            if ap == "am" and hh == 12:
                hh = 0
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                if set_alarm(hh, mm, list(range(7))):
                    st.success(f"Alarm set for {hh:02d}:{mm:02d} every day.")
            else:
                st.warning("Couldn't read that time.")
        else:
            # ---- layer 2: language understanding ---------------------------
            kind = brain.classify(CFG, txt)
            if kind == "preferences":
                add, rem, reply = brain.parse_preferences(CFG, txt)
                if add or rem:
                    CFG = brain.apply_preferences(CFG, add, rem)
                    save_cfg(CFG)
                    publish_once("gateway/control", {"type": "refresh"})
                    st.success(reply)
                    st.caption(f"added: {add or '-'}   removed: {rem or '-'}")
                else:
                    st.warning("I couldn't tell what to add or remove.")
                    st.caption("Try naming it plainly, e.g. \"I care about the "
                               "Steelers and SpaceX stock\", or edit the list "
                               "directly in the Settings tab.")
            else:
                c = brain.answer_card(CFG, txt)
                if c:
                    publish_once("gateway/control",
                                 {"type": "temp_card", "card": c, "minutes": 10})
                    st.success(f"Sent to the device: {c['line1']} / {c['line2']}")
                else:
                    st.info("Answering questions needs Ollama running "
                            "(the Settings tab shows its status).")

# ============================================================== ANALYTICS ===
with tab_analytics:
    df = read_events()
    if df.empty:
        st.info("No events logged yet. Events appear once the device (or the "
                "virtual device in tools/) starts talking to the broker.")
    else:
        ev = df[df["topic"] == "station/event"].copy()
        tl = df[df["topic"] == "station/telemetry"].copy()

        a, b, c = st.columns(3)
        a.metric("Events logged", len(ev))
        knocks = int((ev.get("type") == "knock").sum()) if "type" in ev else 0
        b.metric("Knocks", knocks)
        if "action" in ev:
            c.metric("Snoozes", int((ev["action"] == "snoozed").sum()))

        if "type" in ev and not ev.empty:
            st.subheader("Events per day")
            per_day = (ev.assign(day=ev["ts"].dt.date)
                         .groupby(["day", "type"]).size().unstack(fill_value=0))
            st.bar_chart(per_day)

            st.subheader("When you interact (by hour)")
            per_hour = (ev.assign(hour=ev["ts"].dt.hour)
                          .groupby("hour").size().reindex(range(24), fill_value=0))
            st.bar_chart(per_hour)

        if not tl.empty and "tempF" in tl:
            st.subheader("Indoor climate")
            clim = tl.set_index("ts")[[c for c in ("tempF", "rh") if c in tl]]
            st.line_chart(clim)

    url = SEC.get("azure_function_url", "")
    if url:
        st.divider()
        st.subheader("Cloud aggregates (Azure Function)")
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            cloud_df = pd.DataFrame(r.json())
            st.dataframe(cloud_df, use_container_width=True)
        except Exception as e:
            st.warning(f"Couldn't reach the Function: {e}")

# =============================================================== SETTINGS ===
with tab_settings:
    st.subheader("Interests")
    st.caption("Plain English, one per line. Anything with a live source works — "
               "a team, a ticker, a city, a topic. Gemma picks the tool.")
    txt = st.text_area("What the device shows",
                       value="\n".join(CFG.get("interests", [])), height=170)
    if st.button("Save interests"):
        CFG["interests"] = [ln.strip() for ln in txt.splitlines() if ln.strip()][:8]
        save_cfg(CFG)
        publish_once("gateway/control", {"type": "refresh"})
        st.success(f"Saved {len(CFG['interests'])} interests.")
    st.caption("Fast path (no model call needed): " + ", ".join(catalog.keys()))

    st.subheader("Location")
    loc = CFG.get("location", {})
    lat = st.number_input("Latitude", value=float(loc.get("lat", 33.6405)), format="%.4f")
    lon = st.number_input("Longitude", value=float(loc.get("lon", -117.8443)), format="%.4f")
    mins = st.slider("Refresh every (minutes)", 2, 60, int(CFG.get("refresh_minutes", 15)))
    if st.button("Save location & refresh rate"):
        CFG["location"] = {"lat": lat, "lon": lon, "label": loc.get("label", "")}
        CFG["refresh_minutes"] = mins
        save_cfg(CFG)
        st.success("Saved.")

    st.subheader("Gemma (local AI)")
    g = CFG.get("gemma", {})
    on = st.toggle("Enable Gemma", value=bool(g.get("enabled", False)))
    model = st.text_input("Ollama model tag", value=g.get("model", "gemma4"))
    if st.button("Save Gemma settings"):
        CFG["gemma"] = dict(g, enabled=on, model=model)
        save_cfg(CFG)
        publish_once("gateway/control", {"type": "refresh"})
        st.success("Saved.")

    st.caption("Tools Gemma can call: " + ", ".join(tools.names()))

    ok, info = brain.available(CFG)
    if ok:
        st.success("Ollama is reachable.")
        st.caption("Installed models: " + (", ".join(info) if info else "none pulled yet"))
    else:
        st.warning(f"Ollama not reachable ({info}).")
        st.caption("Weather, calendar, alarms and fast-path interests still work. "
                   "Dynamic interests and questions need Ollama running.")
