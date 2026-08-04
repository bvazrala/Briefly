"""Turns raw fetched data into 21-character card lines.

MVP: deterministic string formatting — no AI required, nothing to install.
LATER: flip USE_GEMMA and implement condense_with_gemma() to let a local
model write the lines instead (see the stub at the bottom). The rest of the
system never changes: a card is a card.
"""
import fetchers

FIT = 21          # SSD1306 fits 21 chars/line at text size 1
USE_GEMMA = False # the Gemma seam — leave False for the MVP


def fit(s, n=FIT):
    s = " ".join(str(s).split())
    return s[:n]


def card(cid, title, l1, l2=""):
    return {"id": cid, "title": fit(title, 18), "line1": fit(l1), "line2": fit(l2)}


# ------------------------------------------------ deterministic formatters --
def weather_card(w):
    l1 = f"{w['now']}F now, high {w['hi']}"
    rain = w.get("rain_pct")
    l2 = f"rain {rain}% today" if rain and rain >= 20 else f"low {w['lo']}F, dry"
    return card("wx", "Weather", l1, l2)


def calendar_card(c):
    return card("cal", "Next up", c["summary"], c["when"])


def news_card(heads):
    l1 = heads[0] if heads else ""
    l2 = heads[1] if len(heads) > 1 else ""
    return card("news", "Headlines", l1, l2)


def coin_card(label, c):
    return card(f"coin-{label.lower()}", label,
                f"${c['price']:,.0f}", f"{c['chg']:+.1f}% 24h")


def rss_topic_card(name, heads):
    l1 = heads[0] if heads else ""
    l2 = heads[1] if len(heads) > 1 else ""
    return card(f"rss-{name.lower()[:8]}", name, l1, l2)


# ------------------------------------------------------------ card builder --
def build_cards(cfg, secrets):
    cards = []

    loc = cfg.get("location", {})
    w = fetchers.weather(loc.get("lat", 33.6405), loc.get("lon", -117.8443),
                         cfg.get("units", "fahrenheit"))
    if w:
        cards.append(weather_card(w))

    ics = (secrets or {}).get("calendar_ics_url", "")
    if ics:
        c = fetchers.calendar_next(ics)
        if c:
            cards.append(calendar_card(c))

    for t in cfg.get("topics", []):
        kind = t.get("kind")
        if kind == "coingecko":
            c = fetchers.coin(t.get("ids", "bitcoin"))
            if c:
                cards.append(coin_card(t.get("label", t.get("name", "Coin")), c))
        elif kind == "rss":
            heads = fetchers.rss_headlines(t.get("url", ""), 2)
            if heads:
                cards.append(rss_topic_card(t.get("name", "Topic"), heads))

    for url in cfg.get("news_feeds", [])[:1]:
        heads = fetchers.rss_headlines(url, 2)
        if heads:
            cards.append(news_card(heads))

    return cards[:8]


# ------------------------------------------------------------- Gemma seam ---
def condense_with_gemma(kind, raw):
    """LATER. Replace a deterministic formatter with a local model call.

    Sketch (after `pip install ollama` and `ollama pull` a gemma4 tag):

        import ollama
        prompt = (
            "You write cards for a tiny 2-line display. Max 21 characters "
            "per line. Given the DATA, return only JSON: "
            '{"line1": "...", "line2": "..."}. Be concrete, no filler.\n'
            f"DATA: {raw}"
        )
        r = ollama.chat(model="gemma4",
                        messages=[{"role": "user", "content": prompt}],
                        format="json", options={"temperature": 0.2})
        import json
        out = json.loads(r["message"]["content"])
        return fit(out["line1"]), fit(out["line2"])

    Wire it in inside build_cards() behind `if USE_GEMMA:` so the
    deterministic path stays as the fallback when Ollama is down.
    """
    raise NotImplementedError("Gemma integration is a later milestone.")
