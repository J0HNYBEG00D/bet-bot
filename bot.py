import os
import requests
import time
from datetime import datetime

# ==================== ΑΣΦΑΛΕΙΣ ΡΥΘΜΙΣΕΙΣ GITHUB ====================
SHARP_API_KEY = os.environ.get(sk_live_R3DYcn94iH9E3i4Ty7Fpj5)
THE_ODDS_API_KEY = os.environ.get(10623a7bf6655a94344f3806bfbdd221)
TELEGRAM_TOKEN = os.environ.get(8681374737:AAGw8nJlT8We0oaT1FiIafnpCMoJMDJYZ3g)
CHAT_ID = os.environ.get(5429007872)

GREEK_BOOKIES = ['bet365', 'stoiximan', 'betano']
# ===================================================================

def send_telegram_alert(message):
    url = f"https://telegram.org{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try: requests.post(url, json=payload)
    except Exception as e: print(f"Σφάλμα Telegram: {e}")

def check_live_matches_sharp():
    print(f"[{datetime.now().strftime('%H:%M')}] Έλεγχος SharpAPI...")
    sharp_url = f"https://sharpapi.io"
    headers = {"Authorization": f"Bearer {SHARP_API_KEY}"}
    
    try:
        response = requests.get(sharp_url, headers=headers).json()
        suspicious_matches = []
        matches = response.get('results', response.get('data', []))
        for match in matches:
            league = match.get('league', {}).get('name', '')
            if "India" in league or "Cambodia" in league:
                if match.get('dropping_odds', False) or match.get('odds_drop_pct', 0) >= 15:
                    suspicious_matches.append(match)
        return suspicious_matches
    except Exception as e:
        print(f"Σφάλμα στο SharpAPI: {e}")
        return []

def find_value_in_greek_bookies(home_team, away_team):
    print(f"🚨 Ύποπτος αγώνας! Έλεγχος στο The Odds API: {home_team} vs {away_team}")
    odds_url = f"https://the-odds-api.com{THE_ODDS_API_KEY}&regions=eu&markets=totals"
    
    try:
        response = requests.get(odds_url).json()
        for match in response:
            if home_team.lower() in match['home_team'].lower() or match['home_team'].lower() in home_team.lower():
                pinnacle_over_odd = None
                for bookmaker in match.get('bookmakers', []):
                    if bookmaker['key'] == 'pinnacle':
                        for market in bookmaker['markets']:
                            if market['key'] == 'totals':
                                for outcome in market['outcomes']:
                                    if outcome['name'] == 'Over' and outcome['point'] == 2.5:
                                        pinnacle_over_odd = outcome['price']

                if pinnacle_over_odd:
                    for bookmaker in match.get('bookmakers', []):
                        bookie_name = bookmaker['key']
                        if bookie_name in GREEK_BOOKIES:
                            for market in bookmaker['markets']:
                                if market['key'] == 'totals':
                                    for outcome in market['outcomes']:
                                        if outcome['name'] == 'Over' and outcome['point'] == 2.5:
                                            greek_odd = outcome['price']
                                            if greek_odd >= (pinnacle_over_odd + 0.25):
                                                alert_msg = (
                                                    f"🚨 *VALUE BET ΕΝΤΟΠΙΣΤΗΚΕ!*\n\n"
                                                    f"⚽ Αγώνας: {match['home_team']} vs {match['away_team']}\n"
                                                    f"🎯 Αγορά: Over 2.5 Γκολ\n\n"
                                                    f"📉 Sharp Τιμή (Pinnacle): {pinnacle_over_odd}\n"
                                                    f"🔥 Στοιχηματική: *{bookie_name.upper()}*\n"
                                                    f"💰 Απόδοση: *{greek_odd}*\n\n"
                                                    f"⏰ Πρόλαβε πριν αλλάξει!"
                                                )
                                                send_telegram_alert(alert_msg)
    except Exception as e:
        print(f"Σφάλμα στο The Odds API: {e}")

# ==================== MAIN LOOP ====================
while True:
    current_hour = datetime.now().hour
    if 11 <= current_hour < 20:
        suspicious_list = check_live_matches_sharp()
        for match in suspicious_list:
            home = match.get('home_team', match.get('home', ''))
            away = match.get('away_team', match.get('away', ''))
            if home and away:
                find_value_in_greek_bookies(home, away)
        time.sleep(300)
    else:
        print("Εκτός ωραρίου Ασίας. Παύση 30 λεπτών...")
        time.sleep(1800)
