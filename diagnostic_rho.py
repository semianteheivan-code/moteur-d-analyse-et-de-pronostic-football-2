"""
Diagnostic ponctuel — pas un module permanent du projet, juste pour comprendre
pourquoi Dixon-Coles n'a presque pas changé les résultats.

Lancer avec : python -m diagnostic_rho
"""

from models.poisson import compute_team_strengths, predict_match_from_strengths
from db.database import get_connection

season_pairs = [
    ("2122", "2223"),
    ("2223", "2324"),
    ("2324", "2425"),
    ("2425", "2526"),
]

for train, test in season_pairs:
    strengths_data = compute_team_strengths(train)
    rho = strengths_data["rho"]

    conn = get_connection()
    matches = conn.execute(
        "SELECT home_team, away_team, result FROM matches "
        "WHERE season = ? AND home_goals IS NOT NULL",
        (test,),
    ).fetchall()

    total_p_draw = 0.0
    n = 0
    actual_draws = 0

    for m in matches:
        try:
            probs = predict_match_from_strengths(strengths_data, m["home_team"], m["away_team"])
        except ValueError:
            continue
        total_p_draw += probs["X"]
        n += 1
        if m["result"] == "D":
            actual_draws += 1

    avg_p_draw = total_p_draw / n if n else 0
    actual_rate = actual_draws / n if n else 0

    print(f"{train} -> {test} : rho={rho:+.4f} | proba nul moyenne prédite={avg_p_draw:.1%} | fréquence réelle de nul={actual_rate:.1%} | n={n}")
