"""Known data sources.

Why this file exists: a language model asked to "add the Lakers" will happily
invent an RSS URL that 404s. So the model never writes URLs — it only picks
KEYS from this catalog, and deterministic code turns a key into a real source.
Hallucination becomes impossible by construction.

To support something new, add a line here. That's the whole extension story.
"""

CATALOG = {
    # --- news -------------------------------------------------------------
    "world":   {"name": "World",    "kind": "rss", "url": "https://feeds.bbci.co.uk/news/rss.xml"},
    "us":      {"name": "US News",  "kind": "rss", "url": "https://feeds.npr.org/1001/rss.xml"},
    "tech":    {"name": "Tech",     "kind": "rss", "url": "https://feeds.arstechnica.com/arstechnica/index"},
    "hn":      {"name": "HackerNews", "kind": "rss", "url": "https://hnrss.org/frontpage"},
    "science": {"name": "Science",  "kind": "rss", "url": "https://feeds.npr.org/1007/rss.xml"},
    "business": {"name": "Business", "kind": "rss", "url": "https://feeds.npr.org/1006/rss.xml"},

    # --- sports -----------------------------------------------------------
    "nba":     {"name": "NBA",      "kind": "rss", "url": "https://www.espn.com/espn/rss/nba/news"},
    "nfl":     {"name": "NFL",      "kind": "rss", "url": "https://www.espn.com/espn/rss/nfl/news"},
    "mlb":     {"name": "MLB",      "kind": "rss", "url": "https://www.espn.com/espn/rss/mlb/news"},
    "nhl":     {"name": "NHL",      "kind": "rss", "url": "https://www.espn.com/espn/rss/nhl/news"},
    "soccer":  {"name": "Soccer",   "kind": "rss", "url": "https://www.espn.com/espn/rss/soccer/news"},
    "college": {"name": "NCAA FB",  "kind": "rss", "url": "https://www.espn.com/espn/rss/ncf/news"},

    # --- finance ----------------------------------------------------------
    "bitcoin":  {"name": "BTC", "kind": "coingecko", "ids": "bitcoin",  "label": "BTC"},
    "ethereum": {"name": "ETH", "kind": "coingecko", "ids": "ethereum", "label": "ETH"},
    "solana":   {"name": "SOL", "kind": "coingecko", "ids": "solana",   "label": "SOL"},
    "dogecoin": {"name": "DOGE", "kind": "coingecko", "ids": "dogecoin", "label": "DOGE"},
}

# Words that map onto a catalog key without any model involved. This is the
# fallback path when Ollama is off, and it covers most real phrasings.
ALIASES = {
    "world": ["world", "international", "global", "bbc"],
    "us": ["us news", "national", "npr", "america"],
    "tech": ["tech", "technology", "ars technica", "gadgets"],
    "hn": ["hacker news", "hackernews", "hn", "startups"],
    "science": ["science", "space", "research"],
    "business": ["business", "markets", "economy", "finance news"],
    "nba": ["nba", "basketball", "lakers", "warriors", "celtics", "clippers"],
    "nfl": ["nfl", "football", "49ers", "rams", "chargers"],
    "mlb": ["mlb", "baseball", "dodgers", "angels", "padres"],
    "nhl": ["nhl", "hockey", "ducks", "kings"],
    "soccer": ["soccer", "premier league", "la liga", "champions league", "futbol"],
    "college": ["college football", "ncaa", "cfb"],
    "bitcoin": ["bitcoin", "btc"],
    "ethereum": ["ethereum", "eth"],
    "solana": ["solana", "sol"],
    "dogecoin": ["dogecoin", "doge"],
}


def key_list():
    return sorted(CATALOG.keys())


def describe_catalog():
    """One compact line per source, used inside the Gemma prompt."""
    return "\n".join(f"- {k}: {v['name']} ({v['kind']})" for k, v in sorted(CATALOG.items()))


def match_keywords(text):
    """Deterministic alias matching. Returns catalog keys found in the text."""
    t = " " + text.lower() + " "
    hits = []
    for key, words in ALIASES.items():
        if any(w in t for w in words):
            hits.append(key)
    return hits


def topic_from_key(key):
    src = CATALOG.get(key)
    if not src:
        return None
    return dict(src, key=key)
