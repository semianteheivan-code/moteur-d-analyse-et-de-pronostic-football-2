from db.database import get_connection
from models.poisson import compute_team_strengths, predict_match_from_strengths

conn = get_connection()
matches = conn.execute("""
    SELECT season, date, home_team, away_team, home_goals, away_goals
    FROM matches
    WHERE season = '2526' AND home_goals IS NOT NULL
    ORDER BY date DESC
    LIMIT 10
""").fetchall()

strengths = compute_team_strengths("2425")

for m in matches:
    print(f"\n{m['date']} : {m['home_team']} vs {m['away_team']}")
    try:
        probs = predict_match_from_strengths(strengths, m["home_team"], m["away_team"])
    except (KeyError, ValueError) as e:
        print(f"  Impossible de predire : {e}")
        continue

    actual_home, actual_away = m["home_goals"], m["away_goals"]
    actual_total = actual_home + actual_away

    if actual_home > actual_away:
        actual_result = "1"
    elif actual_home < actual_away:
        actual_result = "2"
    else:
        actual_result = "X"

    print(f"  Score reel : {actual_home}-{actual_away} (total {actual_total})")
    print(f"  1N2 predit : 1={probs['1']:.0%} X={probs['X']:.0%} 2={probs['2']:.0%}"
          f" | resultat reel = {actual_result}")
    print(f"  O/U 2.5 predit : over={probs['over_2.5']:.0%} under={probs['under_2.5']:.0%}"
          f" | reel = {'OVER' if actual_total > 2.5 else 'UNDER'}")