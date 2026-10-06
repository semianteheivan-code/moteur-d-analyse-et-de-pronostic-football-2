import numpy as np
from scipy.stats import poisson
from scipy.optimize import minimize
from db.database import get_connection

CORNERS_THRESHOLD = 9.5
CARDS_THRESHOLD = 4.5

DEFAULT_SHRINKAGE = {"corners": 0.03, "cards": 0.0}

_STRENGTHS_CACHE = {}


def _neg_log_likelihood(params, n_teams, home_idx, away_idx, home_stat, away_stat, shrinkage_lambda):
    attack = params[:n_teams]
    defense = params[n_teams:2 * n_teams]
    home_adv = params[2 * n_teams]

    lam_h = np.exp(attack[home_idx] + defense[away_idx] + home_adv)
    lam_a = np.exp(attack[away_idx] + defense[home_idx])

    ll = np.sum(poisson.logpmf(home_stat, lam_h)) + np.sum(poisson.logpmf(away_stat, lam_a))
    penalty = shrinkage_lambda * (np.sum(attack ** 2) + np.sum(defense ** 2))
    return -ll + penalty


def _fit_strengths(rows, home_col, away_col, shrinkage_lambda):
    teams = sorted({r["home_team"] for r in rows} | {r["away_team"] for r in rows})
    n = len(teams)
    team_to_idx = {t: i for i, t in enumerate(teams)}

    home_idx = np.array([team_to_idx[r["home_team"]] for r in rows])
    away_idx = np.array([team_to_idx[r["away_team"]] for r in rows])
    home_stat = np.array([r[home_col] for r in rows], dtype=float)
    away_stat = np.array([r[away_col] for r in rows], dtype=float)

    x0 = np.concatenate([np.zeros(n), np.zeros(n), [0.1]])
    constraints = [{"type": "eq", "fun": lambda p, n=n: np.sum(p[:n])}]
    bounds = [(-3, 3)] * n + [(-3, 3)] * n + [(-2, 2)]

    result = minimize(
        _neg_log_likelihood, x0, args=(n, home_idx, away_idx, home_stat, away_stat, shrinkage_lambda),
        constraints=constraints, bounds=bounds, method="SLSQP", options={"maxiter": 300, "ftol": 1e-7},
    )
    if not result.success:
        print(f"Attention : optimisation non pleinement convergee ({result.message})")

    params = result.x
    attack = dict(zip(teams, params[:n]))
    defense = dict(zip(teams, params[n:2 * n]))
    return {"attack": attack, "defense": defense, "home_advantage": float(params[2 * n])}


def compute_stat_strengths(season: str, stat: str, shrinkage_lambda: float = None) -> dict:
    if shrinkage_lambda is None:
        shrinkage_lambda = DEFAULT_SHRINKAGE.get(stat, 0.0)

    cache_key = (season, stat, shrinkage_lambda)
    if cache_key in _STRENGTHS_CACHE:
        return _STRENGTHS_CACHE[cache_key]

    conn = get_connection()
    if stat == "corners":
        rows = conn.execute("""
            SELECT home_team, away_team, home_corners, away_corners FROM matches
            WHERE season = ? AND home_corners IS NOT NULL
              AND (home_corners + away_corners) <= 24
              AND ABS(home_corners - away_corners) <= 15
        """, (season,)).fetchall()
        strengths = _fit_strengths(rows, "home_corners", "away_corners", shrinkage_lambda)
    elif stat == "cards":
        rows = conn.execute("""
            SELECT home_team, away_team,
                   (home_yellow + home_red) as home_cards,
                   (away_yellow + away_red) as away_cards
            FROM matches
            WHERE season = ? AND home_yellow IS NOT NULL
              AND (home_yellow + home_red + away_yellow + away_red) <= 16
        """, (season,)).fetchall()
        strengths = _fit_strengths(rows, "home_cards", "away_cards", shrinkage_lambda)
    else:
        raise ValueError(f"stat inconnu : {stat} (attendu 'corners' ou 'cards')")

    if not rows:
        raise ValueError(f"Aucun match trouve pour la saison {season} ({stat})")

    _STRENGTHS_CACHE[cache_key] = strengths
    return strengths


def predict_stat(home_team: str, away_team: str, season: str, stat: str, shrinkage_lambda: float = None) -> dict:
    strengths = compute_stat_strengths(season, stat, shrinkage_lambda)
    attack, defense, home_adv = strengths["attack"], strengths["defense"], strengths["home_advantage"]

    if home_team not in attack or away_team not in attack:
        raise ValueError("Equipe inconnue pour cette saison")

    exp_home = np.exp(attack[home_team] + defense[away_team] + home_adv)
    exp_away = np.exp(attack[away_team] + defense[home_team])
    exp_total = exp_home + exp_away

    threshold = CORNERS_THRESHOLD if stat == "corners" else CARDS_THRESHOLD
    floor_threshold = int(threshold)
    p_under = float(poisson.cdf(floor_threshold, exp_total))
    p_over = 1 - p_under

    return {
        "stat": stat,
        "expected_home": round(float(exp_home), 2),
        "expected_away": round(float(exp_away), 2),
        "expected_total": round(float(exp_total), 2),
        "threshold": threshold,
        "over": round(p_over, 4),
        "under": round(p_under, 4),
    }


if __name__ == "__main__":
    for stat in ["corners", "cards"]:
        result = predict_stat("Real Madrid", "Barcelona", season="2425", stat=stat)
        print(f"{stat} (shrinkage par defaut) : {result}")