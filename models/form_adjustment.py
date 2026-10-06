import numpy as np
from scipy.stats import poisson
from models.poisson import compute_team_strengths, MAX_GOALS, _dixon_coles_tau_vec
from features.form import compute_match_features


def _form_based_expected_goals(feats: dict) -> tuple:
    home_scored = feats.get("home_form_goals_scored")
    away_conceded = feats.get("away_form_goals_conceded")
    away_scored = feats.get("away_form_goals_scored")
    home_conceded = feats.get("home_form_goals_conceded")

    if None in (home_scored, away_conceded, away_scored, home_conceded):
        return None, None

    exp_home = (home_scored + away_conceded) / 2
    exp_away = (away_scored + home_conceded) / 2
    return exp_home, exp_away


def predict_match_blended(home_team: str, away_team: str, match_date: str, train_season: str, alpha: float) -> dict:
    """
    alpha = 0   -> identique au Poisson+Dixon-Coles existant (aucun changement)
    alpha = 1   -> uniquement base sur la forme recente
    """
    strengths = compute_team_strengths(train_season)
    teams = strengths["attack"]
    if home_team not in teams or away_team not in teams:
        raise ValueError("Equipe inconnue pour cette saison")

    exp_home_poisson = np.exp(strengths["attack"][home_team] + strengths["defense"][away_team] + strengths["home_advantage"])
    exp_away_poisson = np.exp(strengths["attack"][away_team] + strengths["defense"][home_team])

    if alpha > 0:
        feats = compute_match_features(home_team, away_team, match_date)
        exp_home_form, exp_away_form = _form_based_expected_goals(feats)
        if exp_home_form is not None:
            exp_home = (1 - alpha) * exp_home_poisson + alpha * exp_home_form
            exp_away = (1 - alpha) * exp_away_poisson + alpha * exp_away_form
        else:
            exp_home, exp_away = exp_home_poisson, exp_away_poisson
    else:
        exp_home, exp_away = exp_home_poisson, exp_away_poisson

    rho = strengths["rho"]

    matrix = np.zeros((MAX_GOALS + 1, MAX_GOALS + 1))
    for i in range(MAX_GOALS + 1):
        for j in range(MAX_GOALS + 1):
            p = poisson.pmf(i, exp_home) * poisson.pmf(j, exp_away)
            p *= _dixon_coles_tau_vec(np.array([i]), np.array([j]), np.array([exp_home]), np.array([exp_away]), rho)[0]
            matrix[i, j] = max(p, 0.0)
    matrix /= matrix.sum()

    p_home_win = float(np.tril(matrix, -1).sum())
    p_draw = float(np.trace(matrix))
    p_away_win = float(np.triu(matrix, 1).sum())
    p_over_25 = float(sum(
        matrix[i, j] for i in range(MAX_GOALS + 1) for j in range(MAX_GOALS + 1) if i + j > 2.5
    ))

    return {
        "1": round(p_home_win, 4), "X": round(p_draw, 4), "2": round(p_away_win, 4),
        "over_2.5": round(p_over_25, 4), "under_2.5": round(1 - p_over_25, 4),
    }


if __name__ == "__main__":
    for alpha in [0.0, 0.2, 0.4]:
        result = predict_match_blended("Real Madrid", "Barcelona", "2026-01-01", "2425", alpha=alpha)
        print(f"alpha={alpha} : {result}")
