import json
from datetime import datetime, timezone
from sources.five_dollar_football import build_match_requests
from engine import analyze_matches

matches = build_match_requests(datetime(2026, 10, 18, tzinfo=timezone.utc), 1, "2526")
results = analyze_matches(matches)
print(json.dumps(results, indent=2, ensure_ascii=False))