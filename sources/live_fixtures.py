import requests
from config_secrets import API_FOOTBALL_KEY
from sources.team_names import normalize

BASE_URL = "https://v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_FOOTBALL_KEY}
LA_LIGA_ID = 140


def get_next_fixtures(count: int = 15, season: int = 2026) -> list:
    """Recupere les N prochains matchs reels de La Liga, sans supposer de date."""
    response = requests.get(
        f"{BASE_URL}/fixtures",
        headers=HEADERS,
        params={"league": LA_LIGA_ID, "season": season, "next": count},
    )
    response.raise_for_status()
    data = response.json()

    fixtures = []
    for item in data.get("response", []):
        fixtures.append({
            "fixture_id": item["fixture"]["id"],
            "date": item["fixture"]["date"][:10],
            "home_team_raw": item["teams"]["home"]["name"],
            "away_team_raw": item["teams"]["away"]["name"],
            "home_team_normalized": normalize(item["teams"]["home"]["name"]),
            "away_team_normalized": normalize(item["teams"]["away"]["name"]),
        })
    return fixtures


if __name__ == "__main__":
    import json
    fixtures = get_next_fixtures()
    print(f"{len(fixtures)} match(s) a venir trouve(s) :\n")
    print(json.dumps(fixtures, indent=2, ensure_ascii=False))
