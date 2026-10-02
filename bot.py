import os
import requests
import time
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ==================== SECRETS ====================
THE_ODDS_API_KEY = os.environ.get("THE_ODDS_API_KEY", "")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")

# ==================== ΡΥΘΜΙΣΕΙΣ ====================
# Κύρια πρωταθλήματα (υψηλή προτεραιότητα)
PRIMARY_SPORTS = [
    "soccer_argentina_primera_division",
    "soccer_brazil_campeonato",
    "soccer_brazil_serie_b",
    "soccer_chile_campeonato",
    "soccer_mexico_ligamx",
]

# Δευτερεύοντα (χαμηλή προτεραιότητα - πολύ αραιά)
SECONDARY_SPORTS = [
    # India & Cambodia σχεδόν δεν υπάρχουν στο free tier
    # Τα αφήνουμε για μελλοντική επέκταση
]

# Soft bookies που θέλουμε να ελέγξουμε (ό,τι υπάρχει στο eu region)
TARGET_BOOKIES = ["bet365", "pinnacle", "onexbet", "marathonbet", "unibet", "williamhill"]

# Ελάχιστη διαφορά απόδοσης για να θεωρηθεί value
MIN_EDGE = 0.22

# Αρχείο για να μην στέλνουμε το ίδιο alert πολλές φορές
ALERT_CACHE_FILE = Path("alert_cache.json")
CACHE_HOURS = 3  # Μην ξαναστείλεις το ίδιο alert για 3 ώρες

# ==================== ΒΟΗΘΗΤΙΚΕΣ ΣΥΝΑΡΤΗΣΕΙΣ ====================

def send_telegram(message: str):
    """Στέλνει μήνυμα στο Telegram με σωστό URL"""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("⚠️ Λείπουν TELEGRAM_TOKEN ή CHAT_ID", flush=True)
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
    """Φορτώνει τα πρόσφατα alerts για να αποφύγουμε διπλότυπα"""
    if ALERT_CACHE_FILE.exists():
        try:
            with open(ALERT_CACHE_FILE, "r") as f:
                data = json.load(f)
            # Καθαρίζουμε παλιά entries
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
        print(f"Σφάλμα αποθήκευσης cache: {e}", flush=True)


def already_alerted(cache: dict, key: str) -> bool:
    return key in cache


def mark_alerted(cache: dict, key: str):
    cache[key] = datetime.now(timezone.utc).isoformat()


def get_odds_for_sport(sport_key: str) -> list:
    """
    Καλεί The Odds API ΜΟΝΟ για totals (Over/Under).
    Κόστος: 1 credit ανά κλήση (για 1 market + 1 region).
    """
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
        print(f"  [{sport_key}] Status {res.status_code} | Remaining credits: {remaining} | Used: {used}", flush=True)

        if res.status_code != 200:
            print(f"  Error body: {res.text[:200]}", flush=True)
            return []

        return res.json()
    except Exception as e:
        print(f"  Σφάλμα κλήσης {sport_key}: {e}", flush=True)
        return []


def find_value_bets(matches: list, sport_title: str, cache: dict):
    """
    Ψάχνει για value σε ΟΠΟΙΟΔΗΠΟΤΕ Over line.
    Συγκρίνει Pinnacle (sharp) με τις υπόλοιπες bookies.
    """
    for match in matches:
        home = match.get("home_team", "")
        away = match.get("away_team", "")
        event_id = match.get("id", "")

        pinnacle_overs = {}  # point → price

        # 1. Βρίσκουμε όλες τις Over τιμές της Pinnacle
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

        # 2. Συγκρίνουμε με τις άλλες bookies
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
                        # Δημιουργούμε μοναδικό κλειδί για το alert
                        alert_key = f"{event_id}_{book_key}_{point}"

                        if already_alerted(cache, alert_key):
                            continue

                        # Στέλνουμε alert
                        msg = (
                            f"🚨 *VALUE BET ΕΝΤΟΠΙΣΤΗΚΕ!*\n\n"
                            f"⚽ *{home}* vs *{away}*\n"
                            f"🏆 {sport_title}\n"
                            f"🎯 Αγορά: *Over {point}*\n\n"
                            f"📉 Pinnacle: `{pinnacle_price}`\n"
                            f"🔥 {book_key.upper()}: *{soft_price}*\n"
                            f"📈 Edge: `+{edge:.2f}`\n\n"
                            f"⏰ Πρόλαβε πριν αλλάξει!"
                        )
                        send_telegram(msg)
                        mark_alerted(cache, alert_key)
                        print(f"  ✅ Alert στάλθηκε: {home} vs {away} | Over {point} @ {book_key}", flush=True)


# ==================== ΚΥΡΙΑ ΛΟΓΙΚΗ ====================

def main():
    print("=" * 50, flush=True)
    print(f"🚀 Betting Bot ξεκίνησε | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    print("=" * 50, flush=True)

    if not THE_ODDS_API_KEY:
        print("❌ Λείπει THE_ODDS_API_KEY", flush=True)
        return

    cache = load_alert_cache()
    total_alerts = 0

    # --- Κύρια πρωταθλήματα ---
    for sport in PRIMARY_SPORTS:
        print(f"\n🔍 Σκανάρω: {sport}", flush=True)
        matches = get_odds_for_sport(sport)

        if matches:
            # Παίρνουμε ωραίο όνομα πρωταθλήματος
            title = matches[0].get("sport_title", sport) if matches else sport
            find_value_bets(matches, title, cache)
        else:
            print(f"  Καμία ζωντανή/επικείμενη αναμέτρηση", flush=True)

        # Μικρή παύση για να μην χτυπήσουμε rate limit
        time.sleep(1.5)

    # --- Δευτερεύοντα (προς το παρόν άδεια) ---
    # for sport in SECONDARY_SPORTS:
    #     ...

    save_alert_cache(cache)
    print("\n✅ Ο κύκλος ολοκληρώθηκε επιτυχώς.", flush=True)


if __name__ == "__main__":
    main()

