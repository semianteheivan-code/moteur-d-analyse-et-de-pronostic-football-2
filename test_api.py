"""
Script de non-regression de l'API (etape 6 / T5, complete A10, A11, A13, A16, A17, A14).
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
    ok = data.get("status") == "league_not_available" and data.get("available") == ["La Liga"]
    record("GET /fixtures?league=premier_league -> league_not_available",
           "OK" if ok else "FAIL", f"body={data}")
except Exception as e:
    record("GET /fixtures?league=premier_league -> league_not_available", "FAIL", f"exception: {e}")

# ---------------------------------------------------------------------
# Test 4 : /analyze sur un vrai match decouvert via /fixtures
# ---------------------------------------------------------------------
test4_name = "POST /analyze sur un match reel decouvert via /fixtures"
analyze_real_match_data = None
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
            if ok:
                analyze_real_match_data = data
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
# Test 9 (A10) : /fixtures expose un champ "started" booleen par match
# ---------------------------------------------------------------------
test9_name = "GET /fixtures expose un champ 'started' booleen (A10)"
if not fixtures_list:
    record(test9_name, "SKIP", "aucun match disponible actuellement dans /fixtures")
else:
    ok = all(isinstance(fx.get("started"), bool) for fx in fixtures_list)
    record(test9_name, "OK" if ok else "FAIL",
           f"started={[fx.get('started') for fx in fixtures_list]}")

# ---------------------------------------------------------------------
# Test 10 (A10) : /analyze expose un champ "started" booleen
# ---------------------------------------------------------------------
test10_name = "POST /analyze expose un champ 'started' booleen (A10)"
if analyze_real_match_data is None:
    record(test10_name, "SKIP", "test 4 n'a pas produit de reponse exploitable")
else:
    ok = isinstance(analyze_real_match_data.get("started"), bool)
    record(test10_name, "OK" if ok else "FAIL",
           f"started={analyze_real_match_data.get('started')!r}")

# ---------------------------------------------------------------------
# Test 11 (A10) : /daily-batch accepte min_minutes_before_kickoff
# ---------------------------------------------------------------------
try:
    r = requests.post(f"{BASE}/daily-batch", json={
        "combo_definitions": [{"name": "T", "min_odds": 1.0, "max_odds": 10.0}],
        "save": False,
        "min_minutes_before_kickoff": 15,
    })
    data = r.json()
    ok = r.status_code == 200
    record("POST /daily-batch accepte min_minutes_before_kickoff (A10)",
           "OK" if ok else "FAIL", f"status_code={r.status_code}, status_reponse={data.get('status')!r}")
except Exception as e:
    record("POST /daily-batch accepte min_minutes_before_kickoff (A10)", "FAIL", f"exception: {e}")

# ---------------------------------------------------------------------
# Test 12 (A11) : nom mal ecrit -> unknown_team, pas match_not_available
# ---------------------------------------------------------------------
try:
    r = requests.post(f"{BASE}/analyze", json={"home_team": "Levante", "away_team": "FC Seville"})
    data = r.json()
    ok = data.get("status") == "unknown_team" and data.get("unknown") == ["FC Seville"]
    record("POST /analyze Levante/FC Seville -> unknown_team avec unknown=['FC Seville'] (A11)",
           "OK" if ok else "FAIL", f"body={data}")
except Exception as e:
    record("POST /analyze Levante/FC Seville -> unknown_team avec unknown=['FC Seville'] (A11)",
           "FAIL", f"exception: {e}")

# ---------------------------------------------------------------------
# Test 13 (A11) : deux noms connus, match absent -> match_not_available
# ---------------------------------------------------------------------
try:
    r = requests.post(f"{BASE}/analyze", json={"home_team": "Barcelona", "away_team": "Girona"})
    data = r.json()
    ok = data.get("status") == "match_not_available"
    record("POST /analyze Barcelona/Girona (pas au calendrier) -> match_not_available (A11)",
           "OK" if ok else "FAIL", f"status={data.get('status')!r}")
except Exception as e:
    record("POST /analyze Barcelona/Girona (pas au calendrier) -> match_not_available (A11)",
           "FAIL", f"exception: {e}")

# ---------------------------------------------------------------------
# Test 14 (A13) : GET /leagues liste La Liga par defaut
# ---------------------------------------------------------------------
try:
    r = requests.get(f"{BASE}/leagues")
    data = r.json()
    leagues_list = data.get("leagues", [])
    ok = (
        data.get("default_league") == "La Liga"
        and len(leagues_list) == 1
        and leagues_list[0].get("name") == "La Liga"
        and leagues_list[0].get("country") == "Espagne"
        and "la liga" in leagues_list[0].get("aliases", [])
    )
    record("GET /leagues -> default_league='La Liga' avec une entree complete (A13)",
           "OK" if ok else "FAIL", f"body={data}")
except Exception as e:
    record("GET /leagues -> default_league='La Liga' avec une entree complete (A13)",
           "FAIL", f"exception: {e}")

# ---------------------------------------------------------------------
# Test 15 (A16) : surnom accepte, insensible a la casse
# ---------------------------------------------------------------------
try:
    r1 = requests.get(f"{BASE}/fixtures", params={"league": "liga"})
    r2 = requests.get(f"{BASE}/fixtures", params={"league": "LA LIGA"})
    ok = r1.json().get("league") == "La Liga" and r2.json().get("league") == "La Liga"
    record("GET /fixtures?league=liga et league=LA LIGA -> La Liga (A16)",
           "OK" if ok else "FAIL",
           f"league1={r1.json().get('league')!r}, league2={r2.json().get('league')!r}")
except Exception as e:
    record("GET /fixtures?league=liga et league=LA LIGA -> La Liga (A16)", "FAIL", f"exception: {e}")

# ---------------------------------------------------------------------
# Test 16 (A16) : championnat inconnu -> available liste les championnats
# ---------------------------------------------------------------------
try:
    r = requests.get(f"{BASE}/fixtures", params={"league": "premier league"})
    data = r.json()
    ok = data.get("status") == "league_not_available" and data.get("available") == ["La Liga"]
    record("GET /fixtures?league=premier league -> available=['La Liga'] (A16)",
           "OK" if ok else "FAIL", f"body={data}")
except Exception as e:
    record("GET /fixtures?league=premier league -> available=['La Liga'] (A16)", "FAIL", f"exception: {e}")

# ---------------------------------------------------------------------
# Test 17 (A17) : /fixtures expose un fixture_id par match
# ---------------------------------------------------------------------
test17_name = "GET /fixtures expose un champ 'fixture_id' par match (A17)"
if not fixtures_list:
    record(test17_name, "SKIP", "aucun match disponible actuellement dans /fixtures")
else:
    ok = all(fx.get("fixture_id") is not None for fx in fixtures_list)
    record(test17_name, "OK" if ok else "FAIL",
           f"fixture_ids={[fx.get('fixture_id') for fx in fixtures_list]}")

# ---------------------------------------------------------------------
# Test 18 (A17) : /analyze avec fixture_id seul (sans noms d'equipes)
# ---------------------------------------------------------------------
test18_name = "POST /analyze avec fixture_id seul resout le bon match (A17)"
if not fixtures_list or not fixtures_list[0].get("fixture_id"):
    record(test18_name, "SKIP", "aucun fixture_id disponible via /fixtures")
else:
    fid = fixtures_list[0]["fixture_id"]
    try:
        r = requests.post(f"{BASE}/analyze", json={"fixture_id": fid})
        data = r.json()
        ok = data.get("status") in ("ok", "refused", "insufficient_history") and data.get("fixture_id") == fid
        record(test18_name, "OK" if ok else "FAIL", f"fixture_id={fid!r}, body={data}")
    except Exception as e:
        record(test18_name, "FAIL", f"exception: {e}")

# ---------------------------------------------------------------------
# Test 19 (A17) : /analyze avec fixture_id invalide -> match_not_available
# ---------------------------------------------------------------------
try:
    r = requests.post(f"{BASE}/analyze", json={"fixture_id": "99999999999"})
    data = r.json()
    ok = data.get("status") == "match_not_available"
    record("POST /analyze avec fixture_id invalide -> match_not_available (A17)",
           "OK" if ok else "FAIL", f"body={data}")
except Exception as e:
    record("POST /analyze avec fixture_id invalide -> match_not_available (A17)", "FAIL", f"exception: {e}")

# ---------------------------------------------------------------------
# Test 20 (A14) : /fixtures expose un champ "league" par match
# ---------------------------------------------------------------------
test20_name = "GET /fixtures expose un champ 'league' par match (A14)"
if not fixtures_list:
    record(test20_name, "SKIP", "aucun match disponible actuellement dans /fixtures")
else:
    ok = all(fx.get("league") == "La Liga" for fx in fixtures_list)
    record(test20_name, "OK" if ok else "FAIL",
           f"leagues={[fx.get('league') for fx in fixtures_list]}")

# ---------------------------------------------------------------------
# Test 21 (A14) : /analyze expose un champ "league" sur un match identifie
# ---------------------------------------------------------------------
test21_name = "POST /analyze expose un champ 'league' sur un match identifie (A14)"
if analyze_real_match_data is None:
    record(test21_name, "SKIP", "test 4 n'a pas produit de reponse exploitable")
else:
    ok = analyze_real_match_data.get("league") == "La Liga"
    record(test21_name, "OK" if ok else "FAIL",
           f"league={analyze_real_match_data.get('league')!r}")

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
