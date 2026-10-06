import os
import requests
import time
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ==================== SECRETS ====================
SHARP_API_KEY = os.environ.get("SHARP_API_KEY", "")
THE_ODDS_API_KEY = os.environ.get("THE_ODDS_API_KEY", "")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")

# ==================== ΡΥΘΜΙΣΕΙΣ ====================
LEAGUE_MAPPING = {
    "argentina": "soccer_argentina_primera_division",
    "brazil": ["soccer_brazil_campeonato", "soccer_brazil_serie_b"],
    "chile": "soccer_chile_campeonato",
    "mexico": "soccer_mexico_ligamx",
    "colombia": "soccer_colombia_primera_a",
    "japan": "soccer_japan_j_league",
    "korea": "soccer_korea_kleague1",
    "australia": "soccer_australia_aleague",
}

TARGET_BOOKIES = [
    "bet365", "pinnacle", "onexbet", "marathonbet", "unibet", "williamhill",
    "novibet", "fonbet", "superbet", "sportingbet", "stoiximan", "betano"
]

MIN_EDGE = 0.18          # Βελτίωση 3: χαμηλότερο threshold
HOURS_AHEAD = 1.5        # Βελτίωση 1: μόνο αγώνες που ξεκινούν σε ≤ 1.5 ώρα
ALERT_CACHE_FILE = Path("alert_cache.json")
CACHE_HOURS = 4

# ==================== ΒΟΗΘΗΤΙΚΕΣ ====================

def send_telegram(message: str):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("⚠️ Λείπουν TELEGRAM credentials", flush=True)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        res = requests.post(url, json=payload, timeout=12)
        print(f"Telegram → {res.status_code}", flush=True)
    except Exception as e:
        print(f"Σφάλμα Telegram: {e}", flush=True)


def load_alert_cache() -> dict:
    if ALERT_CACHE_FILE.exists():
        try:
            with open(ALERT_CACHE_FILE, "r") as f:
                data = json.load(f)
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=CACHE_HOURS)).isoformat()
            return {k: v for k, v in data.items() if v > cutoff}
        except Exception:
            return {}
    return {}


def save_alert_cache(cache: dict):
    try:
        with open(ALERT_CACHE_FILE, "w") as f:
            json.dump(cache, f)
    except Exception as e:
        print(f"Σφάλμα cache: {e}", flush=True)


def already_alerted(cache: dict, key: str) -> bool:
    return key in cache


def mark_alerted(cache: dict, key: str):
    cache[key] = datetime.now(timezone.utc).isoformat()


# ==================== SHARPAPI PRE-FILTER ====================

def get_relevant_sports_from_sharp() -> list:
    if not SHARP_API_KEY:
        print("⚠️ Λείπει SHARP_API_KEY – θα σκανάρω όλα", flush=True)
        all_sports = []
        for v in LEAGUE_MAPPING.values():
            if isinstance(v, list):
                all_sports.extend(v)
            else:
                all_sports.append(v)
        return all_sports

    url = "https://api.sharpapi.io/api/v1/events"
    headers = {"X-API-Key": SHARP_API_KEY}
    params = {"live": "true", "limit": 80}

    try:
        res = requests.get(url, headers=headers, params=params, timeout=12)
        print(f"SharpAPI Events → Status {res.status_code}", flush=True)

        if res.status_code != 200:
            print(f"  SharpAPI error: {res.text[:150]}", flush=True)
            return []

        data = res.json()
        events = data.get("data", [])

        found_keys = set()
        for event in events:
            league = str(event.get("league", "")).lower()
            home = event.get("home_team", "")
            away = event.get("away_team", "")

            for keyword, sport_key in LEAGUE_MAPPING.items():
                if keyword in league:
                    if isinstance(sport_key, list):
                        found_keys.update(sport_key)
                    else:
                        found_keys.add(sport_key)
                    print(f"  → Βρέθηκε: {home} vs {away} ({league})", flush=True)
                    break

        if found_keys:
            print(f"✅ Βρέθηκαν {len(found_keys)} σχετικά πρωταθλήματα → καλούμε μόνο αυτά", flush=True)
            return list(found_keys)
        else:
            print("→ Κανένα σχετικό live event → δεν καλούμε The Odds API", flush=True)
            return []

    except Exception as e:
        print(f"Σφάλμα SharpAPI: {e}", flush=True)
        return []


# ==================== THE ODDS API ====================

def get_odds_for_sport(sport_key: str) -> list:
    url = (
        f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
        f"?apiKey={THE_ODDS_API_KEY}"
        f"&regions=eu"
        f"&markets=totals"
        f"&oddsFormat=decimal"
    )
    try:
        res = requests.get(url, timeout=15)
        remaining = res.headers.get("x-requests-remaining", "?")
        used = res.headers.get("x-requests-used", "?")
        print(f"  [{sport_key}] Status {res.status_code} | Remaining: {remaining} | Used: {used}", flush=True)
        return res.json() if res.status_code == 200 else []
    except Exception as e:
        print(f"  Σφάλμα The Odds API: {e}", flush=True)
        return []


def is_relevant_match(match: dict) -> bool:
    commence_str = match.get("commence_time")
    if not commence_str:
        return False
    try:
        commence = datetime.fromisoformat(commence_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        hours_until = (commence - now).total_seconds() / 3600
        return 0 <= hours_until <= HOURS_AHEAD
    except Exception:
        return False


def find_value_bets(matches: list, sport_title: str, cache: dict, remaining_credits: str):
    for match in matches:
        if not is_relevant_match(match):
            continue

        home = match.get("home_team", "")
        away = match.get("away_team", "")
        event_id = match.get("id", "")

        pinnacle_overs = {}

        for book in match.get("bookmakers", []):
            if book.get("key") == "pinnacle":
                for market in book.get("markets", []):
                    if market.get("key") == "totals":
                        for outcome in market.get("outcomes", []):
                            if outcome.get("name") == "Over":
                                point = outcome.get("point")
                                price = outcome.get("price")
                                if point is not None and price:
                                    pinnacle_overs[point] = price

        if not pinnacle_overs:
            continue

        for book in match.get("bookmakers", []):
            book_key = book.get("key", "")
            if book_key == "pinnacle" or book_key not in TARGET_BOOKIES:
                continue

            for market in book.get("markets", []):
                if market.get("key") != "totals":
                    continue

                for outcome in market.get("outcomes", []):
                    if outcome.get("name") != "Over":
                        continue

                    point = outcome.get("point")
                    soft_price = outcome.get("price")
                    if point is None or soft_price is None:
                        continue

                    pinnacle_price = pinnacle_overs.get(point)
                    if not pinnacle_price:
                        continue

                    edge = soft_price - pinnacle_price
                    if edge >= MIN_EDGE:
                        alert_key = f"{event_id}_{book_key}_{point}"
                        if already_alerted(cache, alert_key):
                            continue

                        # Βελτίωση 5: καλύτερο μήνυμα
                        now_greece = datetime.now(timezone(timedelta(hours=3))).strftime("%H:%M")
                        msg = (
                            f"🚨 *VALUE BET - ΑΞΙΖΕΙ*\n\n"
                            f"⚽ *{home}* vs *{away}*\n"
                            f"🏆 {sport_title}\n"
                            f"🎯 Αγορά: *Over {point}*\n\n"
                            f"📉 Pinnacle: `{pinnacle_price:.2f}`\n"
                            f"🔥 {book_key.upper()}: *{soft_price:.2f}*\n"
                            f"📈 Edge: `+{edge:.2f}`\n\n"
                            f"⏰ Ώρα Ελλάδος: {now_greece}\n"
                            f"💳 Credits που απομένουν: {remaining_credits}\n\n"
                            f"✅ Πρόλαβε πριν κλείσει!"
                        )
                        send_telegram(msg)
                        mark_alerted(cache, alert_key)
                        print(f"  ✅ Alert: {home} vs {away} | Over {point} @ {book_key} | Edge +{edge:.2f}", flush=True)


# ==================== MAIN ====================

def main():
    print("=" * 60, flush=True)
    print(f"🚀 Hybrid Bot v3 (Strict Value) | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    print("=" * 60, flush=True)

    sports_to_check = get_relevant_sports_from_sharp()

    if not sports_to_check:
        print("\n✅ Τέλος κύκλου – δεν κάηκαν credits", flush=True)
        return

    if not THE_ODDS_API_KEY:
        print("❌ Λείπει THE_ODDS_API_KEY", flush=True)
        return

    cache = load_alert_cache()
    remaining = "?"

    for sport in sports_to_check:
        print(f"\n🔍 Σκανάρω: {sport}", flush=True)
        matches = get_odds_for_sport(sport)
        if matches:
            # Παίρνουμε τα remaining credits από το header του τελευταίου call
            title = matches[0].get("sport_title", sport)
            find_value_bets(matches, title, cache, remaining)
        time.sleep(1.2)

    save_alert_cache(cache)
    print("\n✅ Ο κύκλος ολοκληρώθηκε.", flush=True)


if __name__ == "__main__":
    main()
