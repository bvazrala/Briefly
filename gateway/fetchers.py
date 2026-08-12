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


def web_search(query, max_results=5):
    """Keyless web search via DuckDuckGo. Returns [{title, body}] or None.
    The package was renamed from duckduckgo_search to ddgs; accept either."""
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
    except ImportError:
        print("[fetch] web_search unavailable: pip install ddgs")
        return None
    try:
        out = []
        for r in DDGS().text(query, max_results=max_results):
            title = (r.get("title") or "").strip()
            body = (r.get("body") or "").strip()
            if title or body:
                out.append({"title": title[:160], "body": body[:400]})
        return out or None
    except Exception as e:
        print(f"[fetch] web_search {query!r} failed:", e)
        return None


def geocode(place):
    """Place name -> {name, lat, lon} using Open-Meteo's keyless geocoder."""
    try:
        url = ("https://geocoding-api.open-meteo.com/v1/search"
               f"?name={requests.utils.quote(str(place))}&count=1&language=en&format=json")
        r = requests.get(url, timeout=10, headers=UA)
        r.raise_for_status()
        results = r.json().get("results") or []
        if not results:
            return None
        top = results[0]
        label = top["name"]
        if top.get("admin1"):
            label += f", {top['admin1']}"
        return {"name": label, "lat": top["latitude"], "lon": top["longitude"]}
    except Exception as e:
        print(f"[fetch] geocode {place!r} failed:", e)
        return None


def stock(ticker):
    """Free, keyless quote. Tries Stooq CSV first, falls back to Yahoo chart JSON.
    Returns {"price": float, "chg": percent} or None."""
    t = (ticker or "").strip()
    if not t:
        return None

    # --- Stooq (simple CSV, no key, no rate limit in practice) ------------
    try:
        url = f"https://stooq.com/q/l/?s={t.lower()}.us&f=sd2t2ohlcv&h&e=csv"
        r = requests.get(url, timeout=10, headers=UA)
        r.raise_for_status()
        lines = [ln for ln in r.text.strip().splitlines() if ln.strip()]
        if len(lines) >= 2:
            hdr = [h.strip().lower() for h in lines[0].split(",")]
            row = [c.strip() for c in lines[1].split(",")]
            d = dict(zip(hdr, row))
            close, openp = float(d["close"]), float(d["open"])
            if close > 0 and openp > 0:
                return {"price": close, "chg": (close - openp) / openp * 100.0}
    except Exception as e:
        print(f"[fetch] stooq {t} failed:", e)

    # --- Yahoo fallback ----------------------------------------------------
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{t.upper()}"
        r = requests.get(url, timeout=10, headers=UA)
        r.raise_for_status()
        meta = r.json()["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice")
        prev = meta.get("chartPreviousClose") or meta.get("previousClose")
        if price:
            chg = ((price - prev) / prev * 100.0) if prev else 0.0
            return {"price": float(price), "chg": float(chg)}
    except Exception as e:
        print(f"[fetch] yahoo {t} failed:", e)

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
