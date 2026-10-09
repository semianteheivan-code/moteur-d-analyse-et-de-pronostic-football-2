import json
from datetime import datetime, timedelta, timezone
from sources.five_dollar_football import get_la_liga_fixtures, get_fixture_odds
from daily_batch import run_daily_batch

fixtures_bruts = get_la_liga_fixtures(datetime(2026, 10, 9, tzinfo=timezone.utc), 4)

fixtures = [
    {
        "home_team": fx["teams"]["home"]["name"],
        "away_team": fx["teams"]["away"]["name"],
        "odds": get_fixture_odds(fx["id"]),
    }
    for fx in fixtures_bruts
]

combo_definitions = [
    {"name": "SAFE", "min_odds": 2.0, "max_odds": 3.0},
    {"name": "MEDIUM", "min_odds": 3.0, "max_odds": 5.0},
]

result = run_daily_batch(
    fixtures,
    train_season="2526",
    combo_definitions=combo_definitions,
    batch_date="2026-10-09",
)

print(f"Matchs analysés : {result['matches_analyzed']} (dont {result['matches_ok']} réussis)")
for name, combo in result["combos"].items():
    print(f"\n=== Combiné {name} ===")
    print(combo)

with open("detail_journee8.json", "w", encoding="utf-8") as f:
    json.dump(result["details"], f, indent=2, ensure_ascii=False)
print("\nDétail écrit dans detail_journee8.json")