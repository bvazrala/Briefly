"""Tool registry.

The model never fetches anything and never writes a URL. It emits a tool name
and a dict of arguments; this module validates both against a schema and then
builds and executes the request itself. Adding a capability means adding a tool
here, not widening a whitelist of sources.

Every tool returns a plain dict (or None on failure) and is wrapped in a short
TTL cache so a burst of refreshes doesn't hammer a public API.
"""
import time

import fetchers

# name -> {"desc", "args": {arg: (type, required)}, "fn"}
REGISTRY = {}

# The model's training data predates recent listings, so it cannot be expected
# to know every ticker. Resolve well-known names here instead of hoping.
TICKERS = {
    "spacex": "SPCX", "space x": "SPCX", "starlink": "SPCX",
    "tesla": "TSLA", "apple": "AAPL", "nvidia": "NVDA", "microsoft": "MSFT",
    "google": "GOOGL", "alphabet": "GOOGL", "amazon": "AMZN", "meta": "META",
    "facebook": "META", "netflix": "NFLX", "palantir": "PLTR", "amd": "AMD",
    "intel": "INTC", "coinbase": "COIN", "robinhood": "HOOD",
    "s&p 500": "SPY", "sp500": "SPY", "nasdaq": "QQQ", "dow": "DIA",
}


def resolve_ticker(text):
    """Accept a ticker or a company name and return a ticker symbol."""
    t = " ".join(str(text or "").lower().split())
    t = t.replace(" stock", "").replace(" shares", "").replace(" share price", "")
    t = t.replace("$", "").strip()
    if t in TICKERS:
        return TICKERS[t]
    bare = t.upper()
    if 1 <= len(bare) <= 5 and bare.isalpha():
        return bare
    for name, sym in TICKERS.items():          # "spacex stock price" etc.
        if name in t:
            return sym
    return bare[:8] if bare else None

_CACHE = {}
CACHE_TTL = 120  # seconds


def tool(name, desc, args):
    def deco(fn):
        REGISTRY[name] = {"desc": desc, "args": args, "fn": fn}
        return fn
    return deco


# --------------------------------------------------------------- the tools --
@tool("web_search",
      "Search the live web for CURRENT events: scores, results, breaking news "
      "about a team, person, company, or place. Write the query the way a news "
      "search would be written, not an encyclopedia lookup.",
      {"query": (str, True)})
def _web_search(query):
    hits = fetchers.web_search(query, max_results=5)
    return {"query": query, "results": hits} if hits else None


@tool("stock_quote",
      "ALWAYS use this when the interest mentions a stock, shares, a ticker, "
      "or a share price. Accepts a ticker OR a company name (SpaceX, Tesla, "
      "Apple) — you do not need to know the symbol.",
      {"ticker": (str, True)})
def _stock_quote(ticker):
    sym = resolve_ticker(ticker)
    if not sym:
        return None
    q = fetchers.stock(sym)
    return dict(q, ticker=sym) if q else None


@tool("crypto_price",
      "Current price and 24h change for one cryptocurrency, using its "
      "CoinGecko id, e.g. bitcoin, ethereum, solana.",
      {"coin_id": (str, True)})
def _crypto_price(coin_id):
    q = fetchers.coin(coin_id)
    return dict(q, coin=coin_id) if q else None


@tool("weather",
      "Current conditions and today's forecast for a named place, e.g. "
      "'Irvine, CA' or 'Tokyo'.",
      {"place": (str, True)})
def _weather(place):
    loc = fetchers.geocode(place)
    if not loc:
        return None
    w = fetchers.weather(loc["lat"], loc["lon"])
    return dict(w, place=loc["name"]) if w else None


@tool("headlines",
      "Top headlines for a broad news category. Category must be one of: "
      "world, us, tech, science, business, space.",
      {"category": (str, True)})
def _headlines(category):
    feeds = {
        "world":    "https://feeds.bbci.co.uk/news/rss.xml",
        "us":       "https://feeds.npr.org/1001/rss.xml",
        "tech":     "https://feeds.arstechnica.com/arstechnica/index",
        "science":  "https://feeds.npr.org/1007/rss.xml",
        "business": "https://feeds.npr.org/1006/rss.xml",
        "space":    "https://www.space.com/feeds/all",
    }
    url = feeds.get(str(category).strip().lower())
    if not url:
        return None
    heads = fetchers.rss_headlines(url, 3)
    return {"category": category, "headlines": heads} if heads else None


# ------------------------------------------------------------- description --
def describe():
    """The tool menu injected into the model prompt."""
    lines = []
    for name, spec in REGISTRY.items():
        args = ", ".join(f"{a}: string" for a in spec["args"])
        lines.append(f'- {name}({args}) — {spec["desc"]}')
    return "\n".join(lines)


def names():
    return sorted(REGISTRY)


# --------------------------------------------------------------- validation --
def validate(call):
    """Check a model-proposed call. Returns (ok, name, args, error)."""
    if not isinstance(call, dict):
        return False, None, None, "not an object"

    name = call.get("tool") or call.get("name")
    if not isinstance(name, str) or name not in REGISTRY:
        return False, None, None, f"unknown tool {name!r}"

    raw = call.get("args") or call.get("arguments") or {}
    if not isinstance(raw, dict):
        return False, None, None, "args is not an object"

    spec = REGISTRY[name]["args"]
    clean = {}
    for arg, (typ, required) in spec.items():
        if arg not in raw:
            if required:
                return False, None, None, f"missing arg {arg!r}"
            continue
        val = raw[arg]
        if typ is str:
            if not isinstance(val, (str, int, float)):
                return False, None, None, f"arg {arg!r} has wrong type"
            val = str(val).strip()[:200]
            if not val:
                return False, None, None, f"arg {arg!r} is empty"
        clean[arg] = val

    unknown = set(raw) - set(spec)
    if unknown:                      # ignore extras rather than fail the call
        print(f"[tools] ignoring unexpected args {sorted(unknown)} for {name}")

    return True, name, clean, None


# ---------------------------------------------------------------- execution --
def execute(name, args):
    """Run a validated call, with a short TTL cache. Returns a dict or None."""
    key = (name, tuple(sorted(args.items())))
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]

    started = time.time()
    try:
        out = REGISTRY[name]["fn"](**args)
    except Exception as e:
        print(f"[tools] {name} raised: {e}")
        return None

    print(f"[tools] {name}({args}) -> {'ok' if out else 'no data'} "
          f"in {time.time() - started:.1f}s")
    if out:
        _CACHE[key] = (time.time(), out)
    return out


def clear_cache():
    _CACHE.clear()
