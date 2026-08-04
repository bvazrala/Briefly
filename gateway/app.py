"""Briefing Station dashboard.

Run alongside service.py:
    streamlit run app.py

The chat understands, deterministically (no AI involved):
    update                      -> refresh all cards now
    alarm 7:00 / wake me at 7am -> set the alarm on the device
    clear alarms / alarms off   -> clear alarms
Anything else is where Gemma plugs in later.
"""
import json
import pathlib
import re

import streamlit as st
import paho.mqtt.client as mqtt

BASE = pathlib.Path(__file__).resolve().parent


def load_json(name, default=None):
    p = BASE / name
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


SEC = load_json("secrets.json")
if not SEC:
    st.error("Missing gateway/secrets.json - copy secrets.example.json and edit it.")
    st.stop()
CFG = load_json("config.json", {}) or {}


def publish_once(topic, obj):
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    c.username_pw_set(SEC["mqtt_user"], SEC["mqtt_pass"])
    c.connect(SEC["mqtt_host"], int(SEC.get("mqtt_port", 1883)), 30)
    c.loop_start()
    info = c.publish(topic, json.dumps(obj), qos=1)
    info.wait_for_publish(5)
    c.loop_stop()
    c.disconnect()


def set_alarm(hh, mm, days):
    publish_once("station/command",
                 {"type": "set_alarm", "time": f"{hh:02d}:{mm:02d}", "days": days})


# ------------------------------------------------------------------ layout --
st.set_page_config(page_title="Briefing Station", page_icon="🗞️")
st.title("Briefing Station")

state = load_json("state/cards.json")
if state:
    st.caption(f"Cards last generated {state.get('generated', '?')} "
               f"(service.py must be running)")
    cols = st.columns(2)
    for i, c in enumerate(state.get("cards", [])):
        with cols[i % 2]:
            st.markdown(f"**{c.get('title','')}**  \n"
                        f"`{c.get('line1','')}`  \n"
                        f"`{c.get('line2','')}`")
else:
    st.info("No cards yet. Start `python service.py` in another terminal, "
            "then press Refresh.")

c1, c2, c3 = st.columns(3)
if c1.button("Refresh now"):
    publish_once("gateway/control", {"type": "refresh"})
    st.success("Refresh requested.")
if c2.button("Test beep"):
    publish_once("station/command", {"type": "beep"})
    st.success("Beep sent.")
if c3.button("Clear alarms"):
    publish_once("station/command", {"type": "clear_alarms"})
    st.success("Alarms cleared.")

with st.expander("Set an alarm"):
    t = st.time_input("Time")
    daynames = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    picked = st.multiselect("Days", daynames, default=daynames)
    if st.button("Set alarm"):
        set_alarm(t.hour, t.minute, [daynames.index(d) for d in picked])
        st.success(f"Alarm set for {t.strftime('%H:%M')}.")

with st.expander("Preferences (topics on the device)"):
    st.write("Current topics:",
             [f"{x.get('name')} ({x.get('kind')})" for x in CFG.get("topics", [])] or "none")
    with st.form("add_rss"):
        st.write("Add an RSS topic")
        n = st.text_input("Name", key="rn")
        u = st.text_input("Feed URL", key="ru")
        if st.form_submit_button("Add RSS topic") and n and u:
            CFG.setdefault("topics", []).append({"name": n, "kind": "rss", "url": u})
            (BASE / "config.json").write_text(json.dumps(CFG, indent=2))
            publish_once("gateway/control", {"type": "refresh"})
            st.success(f"Added {n}.")
    with st.form("add_coin"):
        st.write("Add a coin (CoinGecko id, e.g. bitcoin, ethereum)")
        lbl = st.text_input("Label (e.g. BTC)", key="cl")
        cid = st.text_input("CoinGecko id", key="ci")
        if st.form_submit_button("Add coin") and lbl and cid:
            CFG.setdefault("topics", []).append(
                {"name": lbl, "kind": "coingecko", "ids": cid, "label": lbl})
            (BASE / "config.json").write_text(json.dumps(CFG, indent=2))
            publish_once("gateway/control", {"type": "refresh"})
            st.success(f"Added {lbl}.")

# -------------------------------------------------------------- chat router --
ALARM_RE = re.compile(
    r"(?:alarm|wake me(?: up)?)(?:\s*(?:at|for))?\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?",
    re.IGNORECASE)

chat = st.chat_input("Type 'update', or 'alarm 7:00', or 'wake me at 7am'")
if chat:
    txt = chat.strip().lower()
    if txt == "update":                                   # deterministic keyword
        publish_once("gateway/control", {"type": "refresh"})
        st.success("Updating all cards.")
    elif any(k in txt for k in ("clear alarm", "alarms off", "no alarm")):
        publish_once("station/command", {"type": "clear_alarms"})
        st.success("Alarms cleared.")
    else:
        m = ALARM_RE.search(txt)
        if m:
            hh = int(m.group(1))
            mm = int(m.group(2) or 0)
            ap = (m.group(3) or "").lower()
            if ap == "pm" and hh < 12:
                hh += 12
            if ap == "am" and hh == 12:
                hh = 0
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                set_alarm(hh, mm, list(range(7)))
                st.success(f"Alarm set for {hh:02d}:{mm:02d} every day.")
            else:
                st.warning("Couldn't parse that time.")
        else:
            st.info("Free-form requests are the Gemma milestone - for now use "
                    "'update', alarm phrases, or the Preferences panel above.")
