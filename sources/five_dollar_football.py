from datetime import datetime, timedelta, timezone
import json

import requests
from config_secrets import FIVEDOLLAR_API_KEY
from config import FIXTURES_CACHE_TTL_HOURS, ODDS_CACHE_TTL_HOURS
from db.database import get_connection

BASE_URL = "https://api.5dollarfootballapi.com/v1"
HEADERS = {"Authorization": f"Bearer {FIVEDOLLAR_API_KEY}"}
LA_LIGA_ID = 4212821298


def _day_bounds(day: datetime) -> tuple:
    """Calcule start_time/end_time (secondes Unix UTC) pour une journée (contrainte 24h max)."""
    start = datetime(day.year, day.month, day.day, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=23, minutes=59)
    return int(start.timestamp()), int(end.timestamp())


def get_la_liga_fixtures(start_date: datetime, num_days: int) -> list:
    """Récupère les matchs de La Liga jour par jour sur la période demandée."""
    all_fixtures = []
    for offset in range(num_days):
        day = start_date + timedelta(days=offset)
        start_ts, end_ts = _day_bounds(day)
        response = requests.get(
            f"{BASE_URL}/fixtures",
            params={"league": LA_LIGA_ID, "start_time": start_ts, "end_time": end_ts},
            headers=HEADERS,
        )
        response.raise_for_status()
        all_fixtures.extend(response.json().get("data", []))
    return all_fixtures


def _extract_bet365(payload: dict) -> dict:
    """Isole le bloc de cotes Bet365 (seul bookmaker disponible sur le palier gratuit)."""
    for bookmaker in payload.get("data", {}).get("bookmakers", []):
        if bookmaker.get("slug") == "bet365":
            return bookmaker.get("odds", {})
    return {}


def get_fixture_odds(fixture_id: int) -> dict:
    """
    Récupère les cotes d'un match et les convertit au format attendu par
    engine.analyze_match : clés "1", "X", "2", "over_2.5", "under_2.5".
    """
    odds = {}

    r_1x2 = requests.get(f"{BASE_URL}/fixtures/{fixture_id}/odds", params={"market": "1x2"}, headers=HEADERS)
    if r_1x2.status_code == 200:
        closing = _extract_bet365(r_1x2.json()).get("1x2", {}).get("closing")
        if closing:
            odds["1"] = closing.get("home")
            odds["X"] = closing.get("draw")
            odds["2"] = closing.get("away")

    r_goals = requests.get(f"{BASE_URL}/fixtures/{fixture_id}/odds", params={"market": "goal_line"}, headers=HEADERS)
    if r_goals.status_code == 200:
        closing = _extract_bet365(r_goals.json()).get("goal_line", {}).get("closing")
        # On ignore la cote si la ligne du bookmaker n'est pas 2.5 : une cote sur
        # une autre ligne (3.5, 1.5...) n'est pas comparable à notre marché over_2.5.
        if closing and closing.get("line") == 2.5:
            odds["over_2.5"] = closing.get("over")
            odds["under_2.5"] = closing.get("under")

    return {k: v for k, v in odds.items() if v is not None}


def build_match_requests(start_date: datetime, num_days: int, train_season: str) -> list:
    """
    Construit la liste de matchs prête pour engine.analyze_matches.
    Les noms d'équipes ne sont PAS traduits ici : analyze_match applique déjà
    normalize() (sources/team_names.py) sur chaque nom reçu.
    """
    fixtures = get_la_liga_fixtures(start_date, num_days)
    result = []
    for fx in fixtures:
        result.append({
            "home_team": fx["teams"]["home"]["name"],
            "away_team": fx["teams"]["away"]["name"],
            "match_date": fx["kickoff_utc"][:10],
            "train_season": train_season,
            "odds": get_fixture_odds(fx["id"]),
        })
    return result


def get_fixtures_for_daily_batch(day: datetime) -> list:
    """
    Récupère les matchs de La Liga d'une seule journée, au format minimal
    attendu par daily_batch.run_daily_batch : {home_team, away_team, odds}.
    """
    start_ts, end_ts = _day_bounds(day)
    response = requests.get(
        f"{BASE_URL}/fixtures",
        params={"league": LA_LIGA_ID, "start_time": start_ts, "end_time": end_ts},
        headers=HEADERS,
    )
    response.raise_for_status()
    fixtures = response.json().get("data", [])
    return [
        {
            "home_team": fx["teams"]["home"]["name"],
            "away_team": fx["teams"]["away"]["name"],
            "odds": get_fixture_odds(fx["id"]),
        }
        for fx in fixtures
    ]


# --- A partir d'ici : nouvelles fonctions avec cache (etape 2, A1 + D2) ---
# N'affectent pas les fonctions ci-dessus ni run_live_batch.py, qui restent inchanges.

def _cache_get(key: str, ttl_hours: float):
    conn = get_connection()
    row = conn.execute("SELECT payload, fetched_at FROM raw_cache WHERE key = ?", (key,)).fetchone()
    if not row:
        return None
    fetched_at = datetime.fromisoformat(row["fetched_at"])
    if datetime.now(timezone.utc) - fetched_at > timedelta(hours=ttl_hours):
        return None
    return json.loads(row["payload"])


def _cache_set(key: str, payload) -> None:
    conn = get_connection()
    conn.execute(
        "INSERT INTO raw_cache (key, payload, fetched_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET payload = excluded.payload, fetched_at = excluded.fetched_at",
        (key, json.dumps(payload), datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def get_la_liga_fixtures_cached(start_date: datetime, num_days: int) -> list:
    """
    Comme get_la_liga_fixtures, mais avec un cache par jour (table raw_cache),
    pour eviter de rappeler l'API a chaque requete /fixtures (D2).
    """
    all_fixtures = []
    for offset in range(num_days):
        day = start_date + timedelta(days=offset)
        day_key = f"fixtures_day:{LA_LIGA_ID}:{day.date().isoformat()}"
        cached = _cache_get(day_key, FIXTURES_CACHE_TTL_HOURS)
        if cached is not None:
            all_fixtures.extend(cached)
            continue
        fixtures = get_la_liga_fixtures(day, 1)
        _cache_set(day_key, fixtures)
        all_fixtures.extend(fixtures)
    return all_fixtures


def get_fixture_odds_cached(fixture_id: int) -> dict:
    """Comme get_fixture_odds, mais avec un cache par match (table raw_cache, D2)."""
    odds_key = f"odds:{fixture_id}"
    cached = _cache_get(odds_key, ODDS_CACHE_TTL_HOURS)
    if cached is not None:
        return cached
    odds = get_fixture_odds(fixture_id)
    _cache_set(odds_key, odds)
    return odds


if __name__ == "__main__":
    matches = build_match_requests(datetime(2026, 10, 18, tzinfo=timezone.utc), 1, "2526")
    print(json.dumps(matches, indent=2, ensure_ascii=False))
def find_fixture(home_team: str, away_team: str, days: int) -> dict | None:
    """
    Cherche, dans la fenetre de couverture live (cache), un match ou l'equipe
    a domicile correspond a home_team et l'equipe a l'exterieur a away_team
    (comparaison normalisee). En cas de plusieurs correspondances, renvoie
    celle dont le coup d'envoi est le plus proche. Renvoie None si aucun
    match ne correspond (le fixture brut de l'API, pas transforme).
    """
    from datetime import datetime, timezone
    from config import REFERENCE_TIMEZONE
    from zoneinfo import ZoneInfo
    from sources.team_names import normalize

    today = datetime.now(ZoneInfo(REFERENCE_TIMEZONE)).replace(hour=0, minute=0, second=0, microsecond=0)
    fixtures = get_la_liga_fixtures_cached(today, days)

    home_target = normalize(home_team)
    away_target = normalize(away_team)

    matches = [
        fx for fx in fixtures
        if normalize(fx["teams"]["home"]["name"]) == home_target
        and normalize(fx["teams"]["away"]["name"]) == away_target
    ]
    if not matches:
        return None
    return min(matches, key=lambda fx: fx["kickoff_utc"])
