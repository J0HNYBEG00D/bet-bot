import os
import requests
import time
from datetime import datetime

# ==================== GITHUB SECRETS ====================
SHARP_API_KEY = os.environ.get("SHARP_API_KEY", "")
THE_ODDS_API_KEY = os.environ.get("THE_ODDS_API_KEY", "")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")

GREEK_BOOKIES = ['bet365', 'stoiximan', 'betano', 'novibet', 'superbet', 'fonbet', 'sportingbet']
# ========================================================

def send_telegram_alert(message):
    url = f"https://telegram.org{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        res = requests.post(url, json=payload, timeout=10)
        print(f"Απάντηση Telegram: {res.status_code} - {res.text}", flush=True)
    except Exception as e:
        print(f"Σφάλμα Telegram: {e}", flush=True)

def check_live_matches_sharp():
    print(f"[{datetime.now().strftime('%H:%M')}] Έλεγχος SharpAPI...", flush=True)
    sharp_url = f"https://sharpapi.io"
    headers = {"Authorization": f"Bearer {SHARP_API_KEY}"}
    
    try:
        res = requests.get(sharp_url, headers=headers, timeout=15)
        if res.status_code != 200:
            print(f"SharpAPI Error Code: {res.status_code}", flush=True)
            return []
            
        response = res.json()
        suspicious_matches = []
        matches = response.get('results', response.get('data', []))
        if not isinstance(matches, list):
            return []
            
        for match in matches:
            if not isinstance(match, dict):
                continue
            league = match.get('league', {}).get('name', '') if isinstance(match.get('league'), dict) else ''
            
            if "India" in league or "Cambodia" in league or "Argentina" in league:
                if match.get('dropping_odds', False) or match.get('odds_drop_pct', 0) >= 15:
                    suspicious_matches.append(match)
        return suspicious_matches
    except Exception as e:
        print(f"Σφάλμα στο SharpAPI: {e}", flush=True)
        return []

def find_value_in_greek_bookies(home_team, away_team):
    print(f"🚨 Ύποπτος αγώνας! Έλεγχος στο The Odds API: {home_team} vs {away_team}", flush=True)
    odds_url = f"https://the-odds-api.com{THE_ODDS_API_KEY}&regions=eu&markets=totals"
    
    try:
        res = requests.get(odds_url, timeout=15)
        if res.status_code != 200:
            return
            
        response = res.json()
        if not isinstance(response, list):
            return

        for match in response:
            if not isinstance(match, dict):
                continue
            h_team = match.get('home_team', '')
            a_team = match.get('away_team', '')
            
            if home_team.lower() in h_team.lower() or h_team.lower() in home_team.lower():
                pinnacle_over_odd = None
                
                for bookmaker in match.get('bookmakers', []):
                    if bookmaker.get('key') == 'pinnacle':
                        for market in bookmaker.get('markets', []):
                            if market.get('key') == 'totals':
                                for outcome in market.get('outcomes', []):
                                    if outcome.get('name') == 'Over' and outcome.get('point') == 2.5:
                                        pinnacle_over_odd = outcome.get('price')

                if pinnacle_over_odd:
                    for bookmaker in match.get('bookmakers', []):
                        bookie_name = bookmaker.get('key', '')
                        if bookie_name in GREEK_BOOKIES:
                            for market in bookmaker.get('markets', []):
                                if market.get('key') == 'totals':
                                    for outcome in market.get('outcomes', []):
                                        if outcome.get('name') == 'Over' and outcome.get('point') == 2.5:
                                            greek_odd = outcome.get('price')
                                            if greek_odd and greek_odd >= (pinnacle_over_odd + 0.25):
                                                alert_msg = (
                                                    f"🚨 *VALUE BET ΕΝΤΟΠΙΣΤΗΚΕ!*\n\n"
                                                    f"⚽ Αγώνας: {h_team} vs {a_team}\n"
                                                    f"🎯 Αγορά: Over 2.5 Γκολ\n\n"
                                                    f"📉 Sharp Τιμή (Pinnacle): {pinnacle_over_odd}\n"
                                                    f"🔥 Στοιχηματική: *{bookie_name.upper()}*\n"
                                                    f"💰 Απόδοση: *{greek_odd}*\n\n"
                                                    f"⏰ Πρόλαβε πριν αλλάξει!"
                                                )
                                                send_telegram_alert(alert_msg)
    except Exception as e:
        print(f"Σφάλμα στο The Odds API: {e}", flush=True)

# ==================== MAIN LOOP ====================
print("🚀 Το Betting Bot ξεκίνησε επιτυχώς!", flush=True)

# Στέλνουμε το δοκιμαστικό
send_telegram_alert("✅ *Το Betting Bot είναι Online!* Ωράριο: 11:00 - 23:00.")

while True:
    current_hour = datetime.now().hour
    if 11 <= current_hour < 23:
        suspicious_list = check_live_matches_sharp()
        for match in suspicious_list:
            home = match.get('home_team', match.get('home', ''))
            away = match.get('away_team', match.get('away', ''))
            if home and away:
                find_value_in_greek_bookies(home, away)
        time.sleep(300)
    else:
        print("Νυχτερινή παύση (23:00 - 11:00). Ύπνος για 30 λεπτά...", flush=True)
        time.sleep(1800)

