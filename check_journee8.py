from datetime import datetime, timezone
from sources.five_dollar_football import get_la_liga_fixtures

matches = get_la_liga_fixtures(datetime(2026, 10, 9, tzinfo=timezone.utc), 4)
for m in matches:
    print(m["kickoff_utc"], "-", m["teams"]["home"]["name"], "vs", m["teams"]["away"]["name"])