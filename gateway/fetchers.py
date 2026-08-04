"""Data fetchers. Every function returns None (or []) on failure so the
service skips a card it can't build instead of crashing. All sources are
free and keyless."""
import datetime as dt
import requests
import feedparser

UA = {"User-Agent": "briefing-station/0.1 (CS147 course project)"}


def weather(lat, lon, unit="fahrenheit"):
    try:
        url = ("https://api.open-meteo.com/v1/forecast"
               f"?latitude={lat}&longitude={lon}"
               "&current=temperature_2m,relative_humidity_2m,precipitation"
               "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max"
               f"&temperature_unit={unit}&timezone=auto&forecast_days=1")
        r = requests.get(url, timeout=10, headers=UA)
        r.raise_for_status()
        j = r.json()
        return {
            "now": round(j["current"]["temperature_2m"]),
            "hi": round(j["daily"]["temperature_2m_max"][0]),
            "lo": round(j["daily"]["temperature_2m_min"][0]),
            "rain_pct": j["daily"]["precipitation_probability_max"][0],
        }
    except Exception as e:
        print("[fetch] weather failed:", e)
        return None


def rss_headlines(url, n=3):
    try:
        feed = feedparser.parse(url)
        return [e.title for e in feed.entries[:n]] or None
    except Exception as e:
        print("[fetch] rss failed:", url, e)
        return None


def coin(ids="bitcoin"):
    try:
        url = ("https://api.coingecko.com/api/v3/simple/price"
               f"?ids={ids}&vs_currencies=usd&include_24hr_change=true")
        r = requests.get(url, timeout=10, headers=UA)
        r.raise_for_status()
        j = r.json()[ids]
        return {"price": j["usd"], "chg": j.get("usd_24h_change", 0.0)}
    except Exception as e:
        print("[fetch] coin failed:", e)
        return None


def calendar_next(ics_url):
    """Next event within 7 days from a (secret) ICS feed URL.
    Note: recurring events (RRULE) are not expanded in the MVP."""
    try:
        from icalendar import Calendar
        r = requests.get(ics_url, timeout=10, headers=UA)
        r.raise_for_status()
        cal = Calendar.from_ical(r.content)
        now = dt.datetime.now(dt.timezone.utc)
        best = None
        for ev in cal.walk("VEVENT"):
            d = ev.get("dtstart")
            if d is None:
                continue
            start = d.dt
            if isinstance(start, dt.datetime):
                if start.tzinfo is None:
                    start = start.replace(tzinfo=dt.timezone.utc)
            else:  # all-day event: treat as 9:00 UTC that day
                start = dt.datetime.combine(start, dt.time(9, 0), tzinfo=dt.timezone.utc)
            if now <= start <= now + dt.timedelta(days=7):
                if best is None or start < best[0]:
                    best = (start, str(ev.get("summary", "event")))
        if not best:
            return None
        local = best[0].astimezone()
        return {"summary": best[1], "when": local.strftime("%a %H:%M")}
    except Exception as e:
        print("[fetch] calendar failed:", e)
        return None
