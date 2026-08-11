"""Card generation and language understanding.

Two layers, kept deliberately separate:

  DETERMINISTIC  formatting, keyword routing, catalog lookups. No model, no
                 Ollama, no surprises. This layer alone is a working product.

  GEMMA          optional. Condenses raw feeds into better lines, maps
                 free-form preference sentences onto catalog keys, and answers
                 one-off questions.

Every Gemma path has a deterministic fallback and a hard timeout, so a model
that is slow, off, or talking nonsense degrades the product instead of
breaking it. Turn the whole layer on/off with config.json -> gemma.enabled.

No extra pip install is needed: Ollama is reached over plain HTTP.
"""
import json
import re

import requests

import catalog
import fetchers

FIT = 21  # SSD1306 fits 21 characters per line at text size 1

SYS_CONDENSE = (
    "You write cards for a tiny two-line display. "
    f"HARD LIMIT: {FIT} characters per line, including spaces. "
    'Reply with only JSON: {"line1": "...", "line2": "..."}. '
    "Be concrete and specific: numbers, names, outcomes. "
    "No filler words, no greetings, no punctuation at the end."
)

SYS_PREFS = (
    "You map a user's request onto a fixed catalog of information sources. "
    "You may ONLY use keys from the catalog; never invent a key or a URL. "
    'Reply with only JSON: {"add": ["key"], "remove": ["key"], "reply": "one short sentence"}. '
    "Use empty lists when nothing applies."
)

SYS_CLASSIFY = (
    "Classify the user's message. "
    '"preferences" = they want to change what topics their display shows. '
    '"question" = they are asking for information. '
    'Reply with only JSON: {"kind": "preferences"} or {"kind": "question"}.'
)

SYS_ANSWER = (
    "You answer a question for a tiny two-line display. "
    f"HARD LIMIT: {FIT} characters per line. "
    'Reply with only JSON: {"title": "...", "line1": "...", "line2": "..."}. '
    "title is at most 14 characters. Be direct. If you do not know, say so in line1."
)


# --------------------------------------------------------------- utilities --
def fit(s, n=FIT):
    return " ".join(str(s or "").split())[:n]


def card(cid, title, l1, l2=""):
    return {"id": cid, "title": fit(title, 18), "line1": fit(l1), "line2": fit(l2)}


def _gcfg(cfg):
    return (cfg or {}).get("gemma", {})


def enabled(cfg):
    return bool(_gcfg(cfg).get("enabled", False))


def available(cfg):
    """Is Ollama reachable right now? Used by the dashboard status light."""
    g = _gcfg(cfg)
    base = g.get("url", "http://127.0.0.1:11434").rstrip("/")
    try:
        r = requests.get(base + "/api/tags", timeout=3)
        r.raise_for_status()
        names = [m.get("name", "") for m in r.json().get("models", [])]
        return True, names
    except Exception as e:
        return False, str(e)


def _chat(cfg, system, user, timeout=None):
    """One JSON-mode call to Ollama. Returns a dict, or None on any failure."""
    g = _gcfg(cfg)
    if not g.get("enabled", False):
        return None
    base = g.get("url", "http://127.0.0.1:11434").rstrip("/")
    payload = {
        "model": g.get("model", "gemma4"),
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "stream": False,
        "format": "json",
        "options": {"temperature": g.get("temperature", 0.2)},
    }
    try:
        r = requests.post(base + "/api/chat", json=payload,
                          timeout=timeout or g.get("timeout_s", 45))
        r.raise_for_status()
        raw = r.json()["message"]["content"]
    except Exception as e:
        print("[gemma] call failed:", e)
        return None
    return _loads(raw)


def _loads(raw):
    """Parse model output that may be wrapped in prose or code fences."""
    if not raw:
        return None
    txt = raw.strip()
    txt = re.sub(r"^```(?:json)?|```$", "", txt, flags=re.MULTILINE).strip()
    try:
        return json.loads(txt)
    except Exception:
        m = re.search(r"\{.*\}", txt, re.DOTALL)
        if not m:
            print("[gemma] unparseable output:", txt[:120])
            return None
        try:
            return json.loads(m.group(0))
        except Exception:
            print("[gemma] unparseable output:", txt[:120])
            return None


# ------------------------------------------------ deterministic formatters --
def weather_lines(w):
    l1 = f"{w['now']}F now, high {w['hi']}"
    rain = w.get("rain_pct")
    l2 = f"rain {rain}% today" if rain and rain >= 20 else f"low {w['lo']}F, dry"
    return l1, l2


def calendar_lines(c):
    return c["summary"], c["when"]


def headline_lines(heads):
    return (heads[0] if heads else ""), (heads[1] if len(heads) > 1 else "")


def coin_lines(c):
    return f"${c['price']:,.0f}", f"{c['chg']:+.1f}% 24h"


# ------------------------------------------------------------ Gemma layer ---
def condense(cfg, topic, raw, fallback):
    """Ask Gemma for nicer lines; fall back to the deterministic pair."""
    if not enabled(cfg):
        return fallback
    obj = _chat(cfg, SYS_CONDENSE,
                f"TOPIC: {topic}\nDATA: {json.dumps(raw, default=str)[:2000]}")
    if not isinstance(obj, dict):
        return fallback
    l1, l2 = fit(obj.get("line1", "")), fit(obj.get("line2", ""))
    if not l1:                       # empty or malformed -> keep the safe version
        return fallback
    return l1, l2


def classify(cfg, text):
    """preferences | question. Deterministic heuristic when Gemma is off."""
    t = text.lower()
    pref_words = ("care about", "i like", "add ", "remove ", "drop ", "skip ",
                  "stop showing", "show me more", "follow ", "unfollow ",
                  "no more", "don't want", "dont want", "instead of")
    if any(w in t for w in pref_words):
        return "preferences"
    if enabled(cfg):
        obj = _chat(cfg, SYS_CLASSIFY, text, timeout=20)
        if isinstance(obj, dict) and obj.get("kind") in ("preferences", "question"):
            return obj["kind"]
    return "question" if text.strip().endswith("?") else "preferences"


def parse_preferences(cfg, text):
    """Return (add_keys, remove_keys, reply). Model picks catalog keys only."""
    if enabled(cfg):
        obj = _chat(cfg, SYS_PREFS,
                    f"CATALOG:\n{catalog.describe_catalog()}\n\nUSER: {text}",
                    timeout=30)
        if isinstance(obj, dict):
            valid = set(catalog.CATALOG)
            add = [k for k in obj.get("add", []) if k in valid]
            rem = [k for k in obj.get("remove", []) if k in valid]
            reply = fit(obj.get("reply", ""), 120) or "Updated your topics."
            if add or rem:
                return add, rem, reply

    # deterministic fallback: alias matching, with negation detection
    hits = catalog.match_keywords(text)
    negative = any(w in text.lower() for w in
                   ("no ", "not ", "drop", "remove", "skip", "stop", "without", "don't", "dont"))
    if negative:
        return [], hits, "Removed what I could match."
    return hits, [], "Added what I could match."


def apply_preferences(cfg, add_keys, remove_keys):
    """Mutate cfg['topics'] deterministically. Returns the new cfg."""
    topics = list(cfg.get("topics", []))
    have = {t.get("key") or t.get("name", "").lower() for t in topics}

    for k in add_keys:
        if k in have:
            continue
        t = catalog.topic_from_key(k)
        if t:
            topics.append(t)
            have.add(k)

    if remove_keys:
        rm = set(remove_keys)
        topics = [t for t in topics
                  if (t.get("key") or t.get("name", "").lower()) not in rm]

    cfg["topics"] = topics[:8]
    return cfg


def answer_card(cfg, question):
    """One-off question -> a temporary card, or None if Gemma is unavailable."""
    if not enabled(cfg):
        return None
    obj = _chat(cfg, SYS_ANSWER, question)
    if not isinstance(obj, dict):
        return None
    l1 = fit(obj.get("line1", ""))
    if not l1:
        return None
    return card("ask", obj.get("title", "Answer"), l1, obj.get("line2", ""))


# ------------------------------------------------------------ card builder --
def build_cards(cfg, secrets):
    cards = []
    use_ai = enabled(cfg) and cfg.get("gemma", {}).get("condense_cards", True)

    loc = cfg.get("location", {})
    w = fetchers.weather(loc.get("lat", 33.6405), loc.get("lon", -117.8443),
                         cfg.get("units", "fahrenheit"))
    if w:
        fb = weather_lines(w)
        l1, l2 = condense(cfg, "weather today", w, fb) if use_ai else fb
        cards.append(card("wx", "Weather", l1, l2))

    ics = (secrets or {}).get("calendar_ics_url", "")
    if ics:
        c = fetchers.calendar_next(ics)
        if c:
            l1, l2 = calendar_lines(c)
            cards.append(card("cal", "Next up", l1, l2))

    for t in cfg.get("topics", []):
        kind = t.get("kind")
        label = t.get("label") or t.get("name", "Topic")
        if kind == "coingecko":
            c = fetchers.coin(t.get("ids", "bitcoin"))
            if c:
                fb = coin_lines(c)
                l1, l2 = condense(cfg, f"{label} price", c, fb) if use_ai else fb
                cards.append(card(f"coin-{label.lower()}", label, l1, l2))
        elif kind == "rss":
            heads = fetchers.rss_headlines(t.get("url", ""), 3)
            if heads:
                fb = headline_lines(heads)
                l1, l2 = condense(cfg, f"{label} headlines", heads, fb) if use_ai else fb
                cards.append(card(f"rss-{label.lower()[:8]}", label, l1, l2))

    for url in cfg.get("news_feeds", [])[:1]:
        heads = fetchers.rss_headlines(url, 3)
        if heads:
            fb = headline_lines(heads)
            l1, l2 = condense(cfg, "top news headlines", heads, fb) if use_ai else fb
            cards.append(card("news", "Headlines", l1, l2))

    return cards[:8]
