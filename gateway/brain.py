"""Card generation and language understanding.

Two layers, kept deliberately separate:

  DETERMINISTIC  weather, calendar, clock, alarms, and the small fast-path
                 table in catalog.py. No model, no Ollama, no surprises.
                 This layer alone is a working product.

  TOOL LOOP      anything else. Gemma picks a tool and arguments, tools.py
                 validates them and executes the request, results come back to
                 Gemma, and Gemma writes the two display lines.

The model never fetches anything and never writes a URL. Every model path has a
hard timeout and a deterministic fallback, so a slow or absent Ollama degrades
the product rather than breaking it.

No extra pip install is needed for the model: Ollama is reached over HTTP.
"""
import json
import re
import time

import requests

import catalog
import fetchers
import tools

FIT = 21  # an SSD1306 fits 21 characters per line at text size 1

SYS_PICK = (
    "Pick one tool. Reply with only JSON: "
    "{\"tool\": \"<name>\", \"args\": {...}}. "
    "Use only the listed tools. Never invent a tool or a URL.\n"
    "Rules: if the interest mentions a stock, shares, ticker or share price, "
    "use stock_quote. If it names a cryptocurrency, use crypto_price. "
    "Otherwise use web_search, and write the query so it finds THIS WEEK'S "
    "news — recent results, scores, or announcements, not background history.\n"
)

SYS_CARD = (
    "You write cards for a tiny two-line display. "
    f"HARD LIMIT: {FIT} characters per line, including spaces. "
    "Reply with only JSON: {\"title\": \"...\", \"line1\": \"...\", \"line2\": \"...\"}. "
    "title is at most 12 characters.\n"
    "Report only what is NEW or CURRENT: the latest score, price, result, or "
    "announcement in the data. Never write background facts such as founding "
    "dates, franchise history, team colors, or general descriptions — the "
    "reader already knows what the thing is, they want today's update.\n"
    "Prefer concrete numbers, names and outcomes. No filler, no trailing "
    "punctuation. If the data contains nothing current, write \"no recent "
    "update\" in line1 rather than padding with trivia."
)

SYS_PREFS = (
    "Extract what the user wants their display to show.\n"
    "Reply with only JSON: {\"add\": [...], \"remove\": [...], \"reply\": \"one short sentence\"}.\n"
    "Each entry is a short natural-language interest, e.g. \"Steelers\", "
    "\"SpaceX stock\", \"world news\". Keep the user's own wording. "
    "Use empty lists when nothing applies."
)

SYS_CLASSIFY = (
    "Classify the user's message. "
    "\"preferences\" = they want to change what their display shows. "
    "\"question\" = they are asking for information right now. "
    "Reply with only JSON: {\"kind\": \"preferences\"} or {\"kind\": \"question\"}."
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
    """Is Ollama reachable right now? Drives the dashboard status light."""
    base = _gcfg(cfg).get("url", "http://127.0.0.1:11434").rstrip("/")
    try:
        r = requests.get(base + "/api/tags", timeout=3)
        r.raise_for_status()
        return True, [m.get("name", "") for m in r.json().get("models", [])]
    except Exception as e:
        return False, str(e)


def _loads(raw):
    """Parse model output that may arrive wrapped in fences or prose."""
    if not raw:
        return None
    txt = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
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


def _today():
    return time.strftime("%A, %B %d, %Y")


def _chat(cfg, system, user, timeout=None, max_tokens=200, label=""):
    """One JSON-mode call to Ollama. Returns a dict, or None on any failure.

    Reasoning models (gemma4 among them) emit an internal monologue before
    answering, which is slow and pure overhead when all we want is a small JSON
    object. We ask Ollama to skip it with think=false, and retry without that
    parameter if the model doesn't support it. keep_alive holds the weights in
    memory so only the first call of a session pays the load cost.
    """
    g = _gcfg(cfg)
    if not g.get("enabled", False):
        return None
    base = g.get("url", "http://127.0.0.1:11434").rstrip("/")
    payload = {
        "model": g.get("model", "gemma4:12b"),
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "stream": False,
        "format": "json",
        "keep_alive": g.get("keep_alive", "30m"),
        "options": {
            "temperature": g.get("temperature", 0.2),
            "num_predict": max_tokens,
        },
    }
    if not g.get("think", False):
        payload["think"] = False

    started = time.time()
    for attempt in (1, 2):
        try:
            r = requests.post(base + "/api/chat", json=payload,
                              timeout=timeout or g.get("timeout_s", 180))
            r.raise_for_status()
            out = _loads(r.json()["message"]["content"])
            print(f"[gemma] {label or 'call'} in {time.time() - started:.1f}s")
            return out
        except requests.HTTPError as e:
            # some models reject think=false; drop it and try once more
            if attempt == 1 and "think" in payload:
                payload.pop("think")
                print("[gemma] model rejected think=false, retrying with thinking on")
                continue
            print(f"[gemma] {label or 'call'} failed after "
                  f"{time.time() - started:.1f}s:", e)
            return None
        except Exception as e:
            print(f"[gemma] {label or 'call'} failed after "
                  f"{time.time() - started:.1f}s:", e)
            return None
    return None


# --------------------------------------------------- deterministic wording --
def weather_lines(w):
    l1 = f"{w['now']}F now, high {w['hi']}"
    rain = w.get("rain_pct")
    l2 = f"rain {rain}% today" if rain and rain >= 20 else f"low {w['lo']}F, dry"
    return l1, l2


def calendar_lines(c):
    return c["summary"], c["when"]


def _plain_lines(result):
    """Readable two lines from a raw tool result, with no model involved.
    This is the fallback whenever Gemma is off, slow, or unparseable."""
    if not isinstance(result, dict):
        return None
    if "price" in result and "ticker" in result:
        p = result["price"]
        return (f"${p:,.2f}" if p < 1000 else f"${p:,.0f}"), f"{result['chg']:+.1f}% today"
    if "price" in result:
        return f"${result['price']:,.0f}", f"{result['chg']:+.1f}% 24h"
    if result.get("headlines"):
        h = result["headlines"]
        return h[0], (h[1] if len(h) > 1 else "")
    if result.get("results"):
        r = result["results"][0]
        return r.get("title", ""), r.get("body", "")
    if "now" in result and "hi" in result:
        return weather_lines(result)
    return None


# ------------------------------------------------------------- the tool loop --
_PICK_CACHE = {}
PICK_TTL = 3600  # an interest routes to the same tool for an hour


def resolve_interest(cfg, interest):
    """One interest string -> one card. Fast path first, then the model."""
    label = fit(str(interest), 12)

    plan = catalog.lookup(interest)
    if plan:                                   # fast path, no model call
        result = tools.execute(plan["tool"], plan["args"])
        lines = _plain_lines(result) if result else None
        if lines:
            return card(f"f-{plan['key'][:8]}", plan.get("label", label), *lines)
        return None

    if not enabled(cfg):
        return None                            # dynamic topics need the model

    # routing is stable, so cache it: only the first refresh pays for the pick
    key = str(interest).lower().strip()
    hit = _PICK_CACHE.get(key)
    if hit and time.time() - hit[0] < PICK_TTL:
        name, args = hit[1], hit[2]
    else:
        picked = _chat(cfg, SYS_PICK + tools.describe(),
                       f"TODAY: {_today()}\nINTEREST: {interest}",
                       timeout=_gcfg(cfg).get("pick_timeout_s", 120),
                       max_tokens=120, label=f"pick {interest!r}")
        ok, name, args, err = tools.validate(picked)
        if not ok:
            print(f"[brain] {interest!r}: bad tool call ({err})")
            return None
        _PICK_CACHE[key] = (time.time(), name, args)

    result = tools.execute(name, args)
    if not result:
        return None

    fallback = _plain_lines(result)
    obj = _chat(cfg, SYS_CARD,
                f"TODAY: {_today()}\nTOPIC: {interest}\n"
                f"DATA: {json.dumps(result, default=str)[:900]}",
                max_tokens=150, label=f"card {interest!r}")
    if isinstance(obj, dict) and fit(obj.get("line1", "")):
        return card(f"d-{re.sub(r'[^a-z0-9]+', '', str(interest).lower())[:8]}",
                    obj.get("title") or label,
                    obj.get("line1", ""), obj.get("line2", ""))
    if fallback:
        print(f"[brain] {interest!r}: using deterministic lines")
        return card(f"d-{re.sub(r'[^a-z0-9]+', '', str(interest).lower())[:8]}",
                    label, *fallback)
    return None


def answer_card(cfg, question):
    """A one-off question -> a temporary card, backed by live search."""
    if not enabled(cfg):
        return None
    picked = _chat(cfg, SYS_PICK + tools.describe(), f"QUESTION: {question}",
                   timeout=_gcfg(cfg).get("pick_timeout_s", 120),
                   max_tokens=120, label="pick for question")
    ok, name, args, err = tools.validate(picked)
    if not ok:
        ok, name, args = True, "web_search", {"query": str(question)[:200]}
    result = tools.execute(name, args)
    if not result:
        return None
    obj = _chat(cfg, SYS_CARD,
                f"TODAY: {_today()}\nQUESTION: {question}\n"
                f"DATA: {json.dumps(result, default=str)[:900]}",
                max_tokens=150, label="answer card")
    if isinstance(obj, dict) and fit(obj.get("line1", "")):
        return card("ask", obj.get("title") or "Answer",
                    obj.get("line1", ""), obj.get("line2", ""))
    lines = _plain_lines(result)
    return card("ask", "Answer", *lines) if lines else None


# -------------------------------------------------------------- preferences --
_LEADINS = re.compile(
    r"^\s*(i (?:really )?(?:care about|want|like|follow)|show me|add|include|"
    r"give me|track|keep an eye on)\b[:,]?\s*", re.IGNORECASE)
_NEGATIVE = re.compile(
    r"\b(no|not|drop|remove|skip|stop|without|delete|unfollow|hide)\b", re.IGNORECASE)
_ARTICLE = re.compile(r"^(the|a|an|my|any|some|more)\s+", re.IGNORECASE)


def _split_interests(text):
    """Best-effort extraction when Gemma is unavailable."""
    add, remove = [], []
    for clause in re.split(r",|;|\band\b|\bbut\b|\balso\b", text):
        c = _LEADINS.sub("", clause).strip(" .!")
        if not c:
            continue
        negative = bool(_NEGATIVE.search(c))
        c = _NEGATIVE.sub("", c).strip(" .!")
        c = _LEADINS.sub("", c).strip(" .!")
        c = _ARTICLE.sub("", c).strip(" .!")
        if 1 < len(c) <= 40:
            (remove if negative else add).append(c)
    return add, remove


def classify(cfg, text):
    """preferences | question. Heuristic first, model only if it's ambiguous."""
    t = text.lower()
    if any(w in t for w in ("care about", "i like", "add ", "remove ", "drop ",
                            "skip ", "stop showing", "follow ", "unfollow ",
                            "no more", "don't want", "dont want")):
        return "preferences"
    if t.split(" ", 1)[0] in ("what", "who", "when", "where", "why", "how",
                              "did", "is", "are", "does", "will"):
        return "question"
    if enabled(cfg):
        obj = _chat(cfg, SYS_CLASSIFY, text, timeout=60, max_tokens=40, label="classify")
        if isinstance(obj, dict) and obj.get("kind") in ("preferences", "question"):
            return obj["kind"]
    return "question" if text.strip().endswith("?") else "preferences"


def parse_preferences(cfg, text):
    """Return (add, remove, reply) as lists of natural-language interests."""
    if enabled(cfg):
        obj = _chat(cfg, SYS_PREFS, text, timeout=120, max_tokens=200, label="preferences")
        if isinstance(obj, dict):
            add = [fit(x, 40) for x in obj.get("add", []) if str(x).strip()][:8]
            rem = [fit(x, 40) for x in obj.get("remove", []) if str(x).strip()][:8]
            if add or rem:
                return add, rem, fit(obj.get("reply", ""), 120) or "Updated your topics."

    add, rem = _split_interests(text)
    if add and rem:
        reply = f"Added {', '.join(add)}; removed {', '.join(rem)}."
    elif add:
        reply = f"Added {', '.join(add)}."
    elif rem:
        reply = f"Removed {', '.join(rem)}."
    else:
        reply = ""
    return add, rem, reply


def apply_preferences(cfg, add, remove):
    """Interests are plain strings, so this is deliberately simple."""
    interests = [str(i) for i in cfg.get("interests", [])]
    lower = {i.lower() for i in interests}
    for a in add:
        if a.lower() not in lower:
            interests.append(a)
            lower.add(a.lower())
    if remove:
        drop = {r.lower() for r in remove}
        interests = [i for i in interests
                     if i.lower() not in drop
                     and not any(d in i.lower() for d in drop)]
    cfg["interests"] = interests[:8]
    return cfg


# ------------------------------------------------------------ card builder --
def build_cards(cfg, secrets):
    """Weather and calendar are always deterministic. Interests go through
    the fast path, then the tool loop."""
    cards = []

    loc = cfg.get("location", {})
    w = fetchers.weather(loc.get("lat", 33.6405), loc.get("lon", -117.8443),
                         cfg.get("units", "fahrenheit"))
    if w:
        cards.append(card("wx", "Weather", *weather_lines(w)))

    ics = (secrets or {}).get("calendar_ics_url", "")
    if ics:
        c = fetchers.calendar_next(ics)
        if c:
            cards.append(card("cal", "Next up", *calendar_lines(c)))

    for interest in cfg.get("interests", [])[:6]:
        try:
            c = resolve_interest(cfg, interest)
        except Exception as e:
            print(f"[brain] {interest!r} failed:", e)
            c = None
        if c:
            cards.append(c)

    return cards[:8]
