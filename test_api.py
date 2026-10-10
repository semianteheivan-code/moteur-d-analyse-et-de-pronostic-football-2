"""
Script de non-regression de l'API (etape 6 / T5).
Suppose que le serveur tourne deja (uvicorn api.main:app).
Usage : python test_api.py
"""

import sys
import requests

BASE = "http://127.0.0.1:8000"

results = []  # liste de tuples (nom, statut) ou statut in {"OK", "FAIL", "SKIP"}


def record(name, status, detail=""):
    line = f"{status:<4} - {name}"
    if detail:
        line += f"  ({detail})"
    print(line)
    results.append((name, status))


def extract_team_names(fixture):
    """
    Essaie d'extraire (home, away) d'un objet fixture renvoye par /fixtures,
    sans supposer un format unique : teste plusieurs formes possibles et
    renvoie None si aucune n'est reconnue (plutot que de deviner).
    """
    if "home_team" in fixture and "away_team" in fixture:
        return fixture["home_team"], fixture["away_team"]
    if "teams" in fixture:
        teams = fixture["teams"]
        try:
            return teams["home"]["name"], teams["away"]["name"]
        except (KeyError, TypeError):
            return None
    return None


# ---------------------------------------------------------------------
# Test 1 : /health
# ---------------------------------------------------------------------
try:
    r = requests.get(f"{BASE}/health")
    data = r.json()
    ok = r.status_code == 200 and "status" in data
    record("GET /health repond 200 avec un champ status", "OK" if ok else "FAIL",
           f"status_code={r.status_code}, body={data}")
except Exception as e:
    record("GET /health repond 200 avec un champ status", "FAIL", f"exception: {e}")

# ---------------------------------------------------------------------
# Test 2 : /fixtures par defaut -> La Liga
# ---------------------------------------------------------------------
fixtures_list = []
try:
    r = requests.get(f"{BASE}/fixtures")
    data = r.json()
    ok = data.get("league") == "La Liga" and isinstance(data.get("fixtures"), list)
    record("GET /fixtures renvoie La Liga par defaut", "OK" if ok else "FAIL",
           f"league={data.get('league')!r}")
    if ok:
        fixtures_list = data["fixtures"]
except Exception as e:
    record("GET /fixtures renvoie La Liga par defaut", "FAIL", f"exception: {e}")

# ---------------------------------------------------------------------
# Test 3 : /fixtures avec league invalide -> league_not_available
# ---------------------------------------------------------------------
try:
    r = requests.get(f"{BASE}/fixtures", params={"league": "premier_league"})
    data = r.json()
    ok = data.get("status") == "league_not_available"
    record("GET /fixtures?league=premier_league -> league_not_available",
           "OK" if ok else "FAIL", f"body={data}")
except Exception as e:
    record("GET /fixtures?league=premier_league -> league_not_available", "FAIL", f"exception: {e}")

# ---------------------------------------------------------------------
# Test 4 : /analyze sur un vrai match decouvert via /fixtures
# ---------------------------------------------------------------------
test4_name = "POST /analyze sur un match reel decouvert via /fixtures"
if not fixtures_list:
    record(test4_name, "SKIP", "aucun match disponible actuellement dans /fixtures")
else:
    names = None
    for fx in fixtures_list:
        names = extract_team_names(fx)
        if names:
            break
    if not names:
        record(test4_name, "SKIP", "format des fixtures non reconnu, impossible d'extraire les equipes")
    else:
        home, away = names
        try:
            r = requests.post(f"{BASE}/analyze", json={"home_team": home, "away_team": away})
            data = r.json()
            valid_statuses = {"ok", "refused", "insufficient_history", "unknown_team", "match_not_available"}
            ok = data.get("status") in valid_statuses
            record(test4_name, "OK" if ok else "FAIL",
                   f"{home} vs {away} -> status={data.get('status')!r}")
        except Exception as e:
            record(test4_name, "FAIL", f"exception: {e}")

# ---------------------------------------------------------------------
# Test 5 : /analyze sur un match improbable -> match_not_available (ou ok)
# ---------------------------------------------------------------------
try:
    r = requests.post(f"{BASE}/analyze", json={"home_team": "Real Madrid", "away_team": "Barcelona"})
    data = r.json()
    ok = data.get("status") in ("match_not_available", "ok")
    record("POST /analyze Real Madrid vs Barcelona -> match_not_available ou ok",
           "OK" if ok else "FAIL", f"status={data.get('status')!r}")
except Exception as e:
    record("POST /analyze Real Madrid vs Barcelona -> match_not_available ou ok", "FAIL", f"exception: {e}")

# ---------------------------------------------------------------------
# Test 6 : /analyze avec league invalide -> league_not_available
# ---------------------------------------------------------------------
try:
    r = requests.post(f"{BASE}/analyze", json={
        "home_team": "Real Madrid", "away_team": "Barcelona", "league": "premier_league"
    })
    data = r.json()
    ok = data.get("status") == "league_not_available"
    record("POST /analyze league=premier_league -> league_not_available",
           "OK" if ok else "FAIL", f"body={data}")
except Exception as e:
    record("POST /analyze league=premier_league -> league_not_available", "FAIL", f"exception: {e}")

# ---------------------------------------------------------------------
# Test 7 : /daily-batch avec league invalide -> league_not_available
# ---------------------------------------------------------------------
try:
    r = requests.post(f"{BASE}/daily-batch", json={
        "combo_definitions": [{"name": "T", "min_odds": 1.0, "max_odds": 10.0}],
        "league": "premier_league",
    })
    data = r.json()
    ok = data.get("status") == "league_not_available"
    record("POST /daily-batch league=premier_league -> league_not_available",
           "OK" if ok else "FAIL", f"body={data}")
except Exception as e:
    record("POST /daily-batch league=premier_league -> league_not_available", "FAIL", f"exception: {e}")

# ---------------------------------------------------------------------
# Test 8 : /daily-batch avec save=false -> aucune ecriture en base
# ---------------------------------------------------------------------
try:
    from db.database import get_connection

    conn = get_connection()
    before = conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]

    r = requests.post(f"{BASE}/daily-batch", json={
        "combo_definitions": [{"name": "T", "min_odds": 1.0, "max_odds": 10.0}],
        "save": False,
    })
    data = r.json()

    after = conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
    conn.close()

    ok = before == after
    record("POST /daily-batch save=false n'ecrit rien dans predictions",
           "OK" if ok else "FAIL",
           f"avant={before}, apres={after}, status_reponse={data.get('status')!r}")
except Exception as e:
    record("POST /daily-batch save=false n'ecrit rien dans predictions", "FAIL", f"exception: {e}")

# ---------------------------------------------------------------------
# Resume final
# ---------------------------------------------------------------------
print()
n_ok = sum(1 for _, s in results if s == "OK")
n_fail = sum(1 for _, s in results if s == "FAIL")
n_skip = sum(1 for _, s in results if s == "SKIP")
print(f"Resultat : {n_ok} OK, {n_fail} FAIL, {n_skip} SKIP (sur {len(results)} tests)")

if n_fail > 0:
    sys.exit(1)
else:
    sys.exit(0)
