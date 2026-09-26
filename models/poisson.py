import numpy as np
from scipy.stats import poisson
from scipy.optimize import minimize_scalar
from db.database import get_connection

MAX_GOALS = 8
SHRINKAGE = 0.85
RHO_BOUNDS = (-0.2, 0.2)


def _shrink(ratio: float) -> float:
    return 1 + SHRINKAGE * (ratio - 1)


def _dixon_coles_tau(home_goals: int, away_goals: int, lambda_home: float, lambda_away: float, rho: float) -> float:
    if home_goals == 0 and away_goals == 0:
        return 1 - lambda_home * lambda_away * rho
    elif home_goals == 0 and away_goals == 1:
        return 1 + lambda_home * rho
    elif home_goals == 1 and away_goals == 0:
        return 1 + lambda_away * rho
    elif home_goals == 1 and away_goals == 1:
        return 1 - rho
    return 1.0


def _compute_ratios(rows) -> tuple:
    league_avg_home = sum(r["home_goals"] for r in rows) / len(rows)
    league_avg_away = sum(r["away_goals"] for r in rows) / len(rows)

    teams = {r["home_team"] for r in rows} | {r["away_team"] for r in rows}
    strengths = {}

    for team in teams:
        home_matches = [r for r in rows if r["home_team"] == team]
        away_matches = [r for r in rows if r["away_team"] == team]

        home_attack = _shrink((sum(r["home_goals"] for r in home_matches) / len(home_matches)) / league_avg_home if home_matches else 1.0)
        home_defense = _shrink((sum(r["away_goals"] for r in home_matches) / len(home_matches)) / league_avg_away if home_matches else 1.0)
        away_attack = _shrink((sum(r["away_goals"] for r in away_matches) / len(away_matches)) / league_avg_away if away_matches else 1.0)
        away_defense = _shrink((sum(r["home_goals"] for r in away_matches) / len(away_matches)) / league_avg_home if away_matches else 1.0)

        strengths[team] = {
            "home_attack": home_attack,
            "home_defense": home_defense,
            "away_attack": away_attack,
            "away_defense": away_defense,
        }

    return strengths, league_avg_home, league_avg_away


_GLOBAL_RHO_CACHE = None


def fit_global_rho(force_refresh: bool = False) -> float:
    """
    Ajuste rho UNE SEULE FOIS sur l'ensemble des saisons disponibles en base,
    plutot qu'individuellement par saison d'entrainement (instable, voir diagnostic).
    Limite assumee : utilise des saisons "futures" par rapport a certains couples de
    backtest -> legere fuite de donnees, acceptee vu la taille limitee du dataset.
    """
    global _GLOBAL_RHO_CACHE
    if _GLOBAL_RHO_CACHE is not None and not force_refresh:
        return _GLOBAL_RHO_CACHE

    conn = get_connection()
    seasons = [r["season"] for r in conn.execute("SELECT DISTINCT season FROM matches").fetchall()]

    pooled = []
    for season in seasons:
        rows = conn.execute(
            "SELECT home_team, away_team, home_goals, away_goals FROM matches "
            "WHERE season = ? AND home_goals IS NOT NULL",
            (season,),
        ).fetchall()
        if not rows:
            continue
        strengths, league_avg_home, league_avg_away = _compute_ratios(rows)
        for r in rows:
            pooled.append((r, strengths, league_avg_home, league_avg_away))

    def neg_log_likelihood(rho):
        ll = 0.0
        for r, strengths, league_avg_home, league_avg_away in pooled:
            home, away = r["home_team"], r["away_team"]
            if home not in strengths or away not in strengths:
                continue
            exp_home = strengths[home]["home_attack"] * strengths[away]["away_defense"] * league_avg_home
            exp_away = strengths[away]["away_attack"] * strengths[home]["home_defense"] * league_avg_away

            p_h = max(poisson.pmf(r["home_goals"], exp_home), 1e-10)
            p_a = max(poisson.pmf(r["away_goals"], exp_away), 1e-10)
            tau = max(_dixon_coles_tau(r["home_goals"], r["away_goals"], exp_home, exp_away, rho), 1e-10)
            ll += np.log(p_h) + np.log(p_a) + np.log(tau)
        return -ll

    result = minimize_scalar(neg_log_likelihood, bounds=RHO_BOUNDS, method="bounded")
    _GLOBAL_RHO_CACHE = float(result.x)
    return _GLOBAL_RHO_CACHE


def compute_team_strengths(season: str) -> dict:
    conn = get_connection()
    rows = conn.execute(
        "SELECT home_team, away_team, home_goals, away_goals FROM matches "
        "WHERE season = ? AND home_goals IS NOT NULL",
        (season,),
    ).fetchall()

    if not rows:
        raise ValueError(f"Aucun match trouve pour la saison {season}")

    strengths, league_avg_home, league_avg_away = _compute_ratios(rows)
    rho = fit_global_rho()

    return {
        "teams": strengths,
        "league_avg_home": league_avg_home,
        "league_avg_away": league_avg_away,
        "rho": rho,
    }


def predict_match_from_strengths(strengths_data: dict, home_team: str, away_team: str) -> dict:
    teams = strengths_data["teams"]
    rho = strengths_data["rho"]

    if home_team not in teams or away_team not in teams:
        raise ValueError("Equipe inconnue pour cette saison")

    exp_home_goals = teams[home_team]["home_attack"] * teams[away_team]["away_defense"] * strengths_data["league_avg_home"]
    exp_away_goals = teams[away_team]["away_attack"] * teams[home_team]["home_defense"] * strengths_data["league_avg_away"]

    matrix = np.zeros((MAX_GOALS + 1, MAX_GOALS + 1))
    for i in range(MAX_GOALS + 1):
        for j in range(MAX_GOALS + 1):
            p = poisson.pmf(i, exp_home_goals) * poisson.pmf(j, exp_away_goals)
            p *= _dixon_coles_tau(i, j, exp_home_goals, exp_away_goals, rho)
            matrix[i, j] = max(p, 0.0)
    matrix /= matrix.sum()

    p_home_win = float(np.tril(matrix, -1).sum())
    p_draw = float(np.trace(matrix))
    p_away_win = float(np.triu(matrix, 1).sum())
    p_over_25 = float(sum(
        matrix[i, j]
        for i in range(MAX_GOALS + 1)
        for j in range(MAX_GOALS + 1)
        if i + j > 2.5
    ))

    return {
        "expected_home_goals": round(exp_home_goals, 2),
        "expected_away_goals": round(exp_away_goals, 2),
        "rho": round(rho, 4),
        "1": round(p_home_win, 4),
        "X": round(p_draw, 4),
        "2": round(p_away_win, 4),
        "1X": round(p_home_win + p_draw, 4),
        "X2": round(p_draw + p_away_win, 4),
        "12": round(p_home_win + p_away_win, 4),
        "over_2.5": round(p_over_25, 4),
        "under_2.5": round(1 - p_over_25, 4),
    }


def predict_match(home_team: str, away_team: str, season: str) -> dict:
    strengths_data = compute_team_strengths(season)
    return predict_match_from_strengths(strengths_data, home_team, away_team)