from datetime import datetime, timedelta, timezone

import requests
from config_secrets import FIVEDOLLAR_API_KEY

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

if __name__ == "__main__":
    import json
    matches = build_match_requests(datetime(2026, 10, 18, tzinfo=timezone.utc), 1, "2526")
    print(json.dumps(matches, indent=2, ensure_ascii=False))