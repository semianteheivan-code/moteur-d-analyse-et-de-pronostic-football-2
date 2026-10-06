from db.database import get_connection
from models.cards_corners import predict_stat

conn = get_connection()
matches = conn.execute("""
    SELECT season, date, home_team, away_team,
           home_corners, away_corners, home_yellow, away_yellow, home_red, away_red
    FROM matches
    WHERE season = '2526' AND home_corners IS NOT NULL
    ORDER BY date DESC
    LIMIT 10
""").fetchall()

for m in matches:
    print(f"\n{m['date']} : {m['home_team']} vs {m['away_team']}")
    try:
        pred_corners = predict_stat(m["home_team"], m["away_team"], season="2425", stat="corners")
        pred_cards = predict_stat(m["home_team"], m["away_team"], season="2425", stat="cards")
    except ValueError as e:
        print(f"  Impossible de predire : {e}")
        continue

    actual_corners = m["home_corners"] + m["away_corners"]
    actual_cards = m["home_yellow"] + m["home_red"] + m["away_yellow"] + m["away_red"]

    print(f"  Corners  : predit {pred_corners['expected_total']:.1f} (over 9.5 = {pred_corners['over']:.0%}) | reel = {actual_corners}"
          f" | {'OVER' if actual_corners > 9.5 else 'UNDER'} s'est realise")
    print(f"  Cartons  : predit {pred_cards['expected_total']:.1f} (over 4.5 = {pred_cards['over']:.0%}) | reel = {actual_cards}"
          f" | {'OVER' if actual_cards > 4.5 else 'UNDER'} s'est realise")
