from scipy.stats import poisson
from db.database import get_connection

MAX_GOALS = 8  # au-delà, la probabilité est négligeable


def compute_team_strengths(season: str) -> dict:
    """Calcule les forces d'attaque/défense de chaque équipe pour une saison."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT home_team, away_team, home_goals, away_goals FROM matches "
        "WHERE season = ? AND home_goals IS NOT NULL",
        (season,),
    ).fetchall()

    if not rows:
        raise ValueError(f"Aucun match trouvé pour la saison {season}")

    league_avg_home = sum(r["home_goals"] for r in rows) / len(rows)
    league_avg_away = sum(r["away_goals"] for r in rows) / len(rows)

    teams = {r["home_team"] for r in rows} | {r["away_team"] for r in rows}
    strengths = {}

    for team in teams:
        home_matches = [r for r in rows if r["home_team"] == team]
        away_matches = [r for r in rows if r["away_team"] == team]

        home_attack = (sum(r["home_goals"] for r in home_matches) / len(home_matches)) / league_avg_home if home_matches else 1.0
        home_defense = (sum(r["away_goals"] for r in home_matches) / len(home_matches)) / league_avg_away if home_matches else 1.0
        away_attack = (sum(r["away_goals"] for r in away_matches) / len(away_matches)) / league_avg_away if away_matches else 1.0
        away_defense = (sum(r["home_goals"] for r in away_matches) / len(away_matches)) / league_avg_home if away_matches else 1.0

        strengths[team] = {
            "home_attack": home_attack,
            "home_defense": home_defense,
            "away_attack": away_attack,
            "away_defense": away_defense,
        }

    return {
        "teams": strengths,
        "league_avg_home": league_avg_home,
        "league_avg_away": league_avg_away,
    }


def predict_match(home_team: str, away_team: str, season: str) -> dict:
    data = compute_team_strengths(season)
    teams = data["teams"]

    if home_team not in teams or away_team not in teams:
        raise ValueError("Équipe inconnue pour cette saison")

    # Buts attendus : attaque du receveur x défense du visiteur x moyenne de la ligue
    exp_home_goals = teams[home_team]["home_attack"] * teams[away_team]["away_defense"] * data["league_avg_home"]
    exp_away_goals = teams[away_team]["away_attack"] * teams[home_team]["home_defense"] * data["league_avg_away"]

    # Matrice des probabilités pour chaque score exact
    home_probs = [poisson.pmf(i, exp_home_goals) for i in range(MAX_GOALS + 1)]
    away_probs = [poisson.pmf(i, exp_away_goals) for i in range(MAX_GOALS + 1)]

    p_home_win = p_draw = p_away_win = 0.0
    p_over_25 = 0.0

    for i in range(MAX_GOALS + 1):
        for j in range(MAX_GOALS + 1):
            p = home_probs[i] * away_probs[j]
            if i > j:
                p_home_win += p
            elif i == j:
                p_draw += p
            else:
                p_away_win += p
            if i + j > 2.5:
                p_over_25 += p

    return {
        "expected_home_goals": round(exp_home_goals, 2),
        "expected_away_goals": round(exp_away_goals, 2),
        "1": round(p_home_win, 4),
        "X": round(p_draw, 4),
        "2": round(p_away_win, 4),
        "1X": round(p_home_win + p_draw, 4),
        "X2": round(p_draw + p_away_win, 4),
        "12": round(p_home_win + p_away_win, 4),
        "over_2.5": round(p_over_25, 4),
        "under_2.5": round(1 - p_over_25, 4),
    }