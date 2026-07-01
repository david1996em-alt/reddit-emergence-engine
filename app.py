from flask import Flask, jsonify
import feedparser
import time
import re
from collections import defaultdict
import math
import threading
import requests

app = Flask(__name__)

SUBREDDITS = [
    "wallstreetbets",
    "stocks",
    "investing",
    "CryptoCurrency",
    "CryptoMoonShots"
]

WINDOW_SECONDS = 48 * 3600
STATE = []

CRYPTO_MAP = {
    "BITCOIN": "BTC",
    "ETHEREUM": "ETH",
    "SOLANA": "SOL",
    "DOGECOIN": "DOGE"
}

MACRO_EXCLUDE = {"SPY","QQQ","IWM","DIA","AAPL","MSFT","NVDA","JPM"}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (TrendEngine/1.0)"
}

# -------------------------
# SAFE FETCH (NO HANGS)
# -------------------------
def fetch_subreddit(sub):
    try:
        url = f"https://www.reddit.com/r/{sub}/new.rss"
        r = requests.get(url, headers=HEADERS, timeout=10)

        feed = feedparser.parse(r.content)

        posts = []
        for entry in feed.entries:
            posts.append({
                "title": entry.title,
                "ts": time.time(),
                "sub": sub
            })
        return posts

    except:
        return []

# -------------------------
# ENTITY EXTRACTION
# -------------------------
def extract(text):
    entities = set()

    tickers = re.findall(r'\b[A-Z]{2,6}\b', text)
    for t in tickers:
        if t not in MACRO_EXCLUDE:
            entities.add(t)

    for k, v in CRYPTO_MAP.items():
        if k in text:
            entities.add(v)

    return entities

# -------------------------
# BACKGROUND INGEST (SAFE)
# -------------------------
def ingest_loop():
    global STATE

    while True:
        new_state = []

        for sub in SUBREDDITS:
            posts = fetch_subreddit(sub)

            for p in posts:
                ents = extract(p["title"].upper())

                if ents:
                    new_state.append({
                        "ts": time.time(),
                        "entities": ents,
                        "sub": sub
                    })

        STATE = new_state
        time.sleep(60)

threading.Thread(target=ingest_loop, daemon=True).start()

# -------------------------
# CLEAN OLD DATA
# -------------------------
def clean_state():
    global STATE
    cutoff = time.time() - WINDOW_SECONDS
    STATE = [x for x in STATE if x["ts"] > cutoff]

# -------------------------
# CORE ENGINE
# -------------------------
def compute():
    clean_state()

    data = defaultdict(lambda: {
        "6h": 0,
        "24h": 0,
        "subs": set(),
        "first_seen": time.time()
    })

    now = time.time()

    for e in STATE:
        age = now - e["ts"]

        for ent in e["entities"]:
            d = data[ent]

            if age <= 6 * 3600:
                d["6h"] += 1
            if age <= 24 * 3600:
                d["24h"] += 1

            d["subs"].add(e["sub"])
            d["first_seen"] = min(d["first_seen"], e["ts"])

    results = []

    for k, v in data.items():
        if v["24h"] < 2:
            continue

        velocity = v["6h"] / max(v["24h"], 1)
        spread = len(v["subs"]) / len(SUBREDDITS)
        novelty = 1.0 if (now - v["first_seen"]) < 24 * 3600 else 0.0
        volume = math.log(v["24h"] + 1) / math.log(20)

        score = (velocity * 0.4) + (spread * 0.3) + (novelty * 0.2) + (volume * 0.1)

        results.append({
            "name": k,
            "mentions_6h": v["6h"],
            "mentions_24h": v["24h"],
            "velocity": round(velocity, 3),
            "spread": round(spread, 3),
            "novelty": novelty,
            "emergence_score": round(score, 4),
            "subreddits": list(v["subs"])
        })

    results.sort(key=lambda x: x["emergence_score"], reverse=True)
    return results[:15]

# -------------------------
# ROUTES (IMPORTANT FIX)
# -------------------------

@app.route("/")
def home():
    return "API running. Use /attention"

@app.route("/health")
def health():
    return "ok"

@app.route("/attention")
def attention():
    return jsonify({"signals": compute()})

# -------------------------
# START
# -------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
