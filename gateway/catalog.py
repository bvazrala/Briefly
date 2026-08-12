"""Fast path.

A small table of interests that are so common it would be wasteful to spend a
model call on them. If an interest matches here, the gateway fetches it
directly and skips Gemma entirely — the card appears in milliseconds instead of
seconds, and it still works with Ollama switched off.

Anything that does NOT match here goes to the tool-calling loop in brain.py.
This table is an optimization, not a limit on what the product can show.
"""
import re

FAST = {
    "world news":    {"tool": "headlines",    "args": {"category": "world"},    "label": "World"},
    "us news":       {"tool": "headlines",    "args": {"category": "us"},       "label": "US News"},
    "tech news":     {"tool": "headlines",    "args": {"category": "tech"},     "label": "Tech"},
    "science news":  {"tool": "headlines",    "args": {"category": "science"},  "label": "Science"},
    "business news": {"tool": "headlines",    "args": {"category": "business"}, "label": "Business"},
    "space news":    {"tool": "headlines",    "args": {"category": "space"},    "label": "Space"},
    "bitcoin":       {"tool": "crypto_price", "args": {"coin_id": "bitcoin"},   "label": "BTC"},
    "ethereum":      {"tool": "crypto_price", "args": {"coin_id": "ethereum"},  "label": "ETH"},
    "solana":        {"tool": "crypto_price", "args": {"coin_id": "solana"},    "label": "SOL"},
}

# phrase -> canonical key above
_ALIASES = {
    "world news": ["world news", "world", "international news", "global news"],
    "us news": ["us news", "national news", "america news"],
    "tech news": ["tech news", "tech", "technology"],
    "science news": ["science news", "science"],
    "business news": ["business news", "business", "markets"],
    "space news": ["space news", "space"],
    "bitcoin": ["bitcoin", "btc"],
    "ethereum": ["ethereum", "eth"],
    "solana": ["solana", "sol"],
}

_SORTED = sorted(
    ((key, phrase) for key, ps in _ALIASES.items() for phrase in ps),
    key=lambda kv: -len(kv[1]),
)


def lookup(interest):
    """Return a fast-path plan for this interest, or None to use the model."""
    t = " ".join(str(interest).lower().split())
    for key, phrase in _SORTED:
        if re.fullmatch(re.escape(phrase), t):
            return dict(FAST[key], key=key)
    return None


def keys():
    return sorted(FAST)
