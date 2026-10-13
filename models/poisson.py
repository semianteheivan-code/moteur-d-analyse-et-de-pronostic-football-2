import numpy as np
from scipy.stats import poisson
from scipy.optimize import minimize, minimize_scalar
from db.database import get_connection

MAX_GOALS = 8
RHO_BOUNDS = (-0.2, 0.2)


def _dixon_coles_tau_vec(hg: np.ndarray, ag: np.ndarray, lam_h: np.ndarray, lam_a: np.ndarray, rho: float) -> np.ndarray:
    """Version vectorisee de la correction Dixon-Coles (tableaux numpy au lieu d'un seul match)."""
    tau = np.ones_like(lam_h)
    m00 = (hg == 0) & (ag == 0)
    m01 = (hg == 0) & (ag == 1)
    m10 = (hg == 1) & (ag == 0)
    m11 = (hg == 1) & (ag == 1)
    tau[m00] = 1 - lam_h[m00] * lam_a[m00] * rho
    tau[m01] = 1 + lam_h[m01] * rho
    tau[m10] = 1 + lam_a[m10] * rho
    tau[m11] = 1 - rho
    return tau


def _prepare_match_arrays(rows, team_to_idx: dict) -> dict:
    """Convertit les lignes SQL en tableaux numpy (indices d'equipe, buts) pour un calcul vectorise."""
    home_idx = np.array([team_to_idx[r["home_team"]] for r in rows])
    away_idx = np.array([team_to_idx[r["away_team"]] for r in rows])
    home_goals = np.array([r["home_goals"] for r in rows], dtype=float)
    away_goals = np.array([r["away_goals"] for r in rows], dtype=float)
    return {"home_idx": home_idx, "away_idx": away_idx, "home_goals": home_goals, "away_goals": away_goals}


def _neg_log_likelihood_no_rho(params, n_teams, arrays):
    """Vraisemblance negative vectorisee (Poisson pur, rho=0), pour estimer attack/defense/home_adv."""
    attack = params[:n_teams]
    defense = params[n_teams:2 * n_teams]
    home_adv = params[2 * n_teams]

    lam_h = np.exp(attack[arrays["home_idx"]] + defense[arrays["away_idx"]] + home_adv)
    lam_a = np.exp(attack[arrays["away_idx"]] + defense[arrays["home_idx"]])

    ll = np.sum(poisson.logpmf(arrays["home_goals"], lam_h)) + np.sum(poisson.logpmf(arrays["away_goals"], lam_a))
    return -ll


def _fit_team_strengths_mle(rows) -> dict:
    """
    Estime attack[team], defense[team] et l'avantage domicile par maximum de
    vraisemblance conjointe (vectorise numpy, rho=0 a cette etape).
    """
    teams = sorted({r["home_team"] for r in rows} | {r["away_team"] for r in rows})
    n = len(teams)
    if n < 2:
        raise ValueError("Pas assez d'equipes distinctes pour entrainer le modele.")

    team_to_idx = {t: i for i, t in enumerate(teams)}
    arrays = _prepare_match_arrays(rows, team_to_idx)

    x0 = np.concatenate([np.zeros(n), np.zeros(n), [0.2]])
    constraints = [{"type": "eq", "fun": lambda p, n=n: np.sum(p[:n])}]

    result = minimize(
        _neg_log_likelihood_no_rho, x0, args=(n, arrays),
        constraints=constraints, method="SLSQP",
        options={"maxiter": 300, "ftol": 1e-7},
    )

    if not result.success:
        print(f"Attention : l'optimisation des forces d'equipe n'a pas pleinement converge ({result.message})")

    params = result.x
    attack = dict(zip(teams, params[:n]))
    defense = dict(zip(teams, params[n:2 * n]))
    home_adv = float(params[2 * n])

    return {"attack": attack, "defense": defense, "home_advantage": home_adv}


_SEASON_STRENGTHS_CACHE = {}
_RHO_CACHE = {}  # cle = tuple(sorted(seasons)) de saisons utilisees, ou None pour "toutes les saisons disponibles"


def _get_season_strengths(season: str) -> dict:
    """Calcule (ou reutilise depuis le cache) les forces attack/defense/home_advantage d'une saison."""
    if season in _SEASON_STRENGTHS_CACHE:
        return _SEASON_STRENGTHS_CACHE[season]

    conn = get_connection()
    rows = conn.execute(
        "SELECT home_team, away_team, home_goals, away_goals FROM matches "
        "WHERE season = ? AND home_goals IS NOT NULL",
        (season,),
    ).fetchall()
    if not rows:
        raise ValueError(f"Aucun match trouve pour la saison {season}")

    strengths = _fit_team_strengths_mle(rows)
    _SEASON_STRENGTHS_CACHE[season] = strengths
    return strengths


def fit_global_rho(seasons: list = None, force_refresh: bool = False) -> float:
    """
    Ajuste rho en regroupant les matchs des saisons indiquees.

    seasons=None (par defaut) : utilise TOUTES les saisons disponibles en
    base - c'est le comportement du moteur en production (engine.py, via
    predict_match), ou ceci est correct et sans risque : au moment d'une
    vraie prediction, aucune saison "future" n'existe encore dans la base.

    seasons=[...] explicite : restreint le calcul a ces saisons uniquement.
    OBLIGATOIRE pour un backtest (etape M5, fuite corrigee le 13/10/2026) -
    l'appelant doit alors ne passer QUE les saisons anterieures ou egales a
    la saison d'entrainement, jamais la saison de test. Avant cette
    correction, fit_global_rho() regroupait systematiquement toutes les
    saisons de la base (y compris celle utilisee comme test), donnant au
    modele une partie de la reponse avant l'evaluation - les chiffres de
    ROI/calibration mesures avant cette date doivent etre consideres comme
    optimistes, a re-mesurer.
    """
    cache_key = tuple(sorted(seasons)) if seasons is not None else None
    if cache_key in _RHO_CACHE and not force_refresh:
        return _RHO_CACHE[cache_key]

    conn = get_connection()
    if seasons is None:
        seasons = [r["season"] for r in conn.execute("SELECT DISTINCT season FROM matches").fetchall()]

    pooled_lam_h, pooled_lam_a, pooled_hg, pooled_ag = [], [], [], []

    for season in seasons:
        rows = conn.execute(
            "SELECT home_team, away_team, home_goals, away_goals FROM matches "
            "WHERE season = ? AND home_goals IS NOT NULL",
            (season,),
        ).fetchall()
        if not rows:
            continue
        s = _get_season_strengths(season)

        for r in rows:
            home, away = r["home_team"], r["away_team"]
            if home not in s["attack"] or away not in s["attack"]:
                continue
            lam_h = np.exp(s["attack"][home] + s["defense"][away] + s["home_advantage"])
            lam_a = np.exp(s["attack"][away] + s["defense"][home])
            pooled_lam_h.append(lam_h)
            pooled_lam_a.append(lam_a)
            pooled_hg.append(r["home_goals"])
            pooled_ag.append(r["away_goals"])

    lam_h = np.array(pooled_lam_h)
    lam_a = np.array(pooled_lam_a)
    hg = np.array(pooled_hg, dtype=float)
    ag = np.array(pooled_ag, dtype=float)

    def neg_log_likelihood(rho):
        tau = np.clip(_dixon_coles_tau_vec(hg, ag, lam_h, lam_a, rho), 1e-10, None)
        ll = np.sum(poisson.logpmf(hg, lam_h)) + np.sum(poisson.logpmf(ag, lam_a)) + np.sum(np.log(tau))
        return -ll

    result = minimize_scalar(neg_log_likelihood, bounds=RHO_BOUNDS, method="bounded")
    _RHO_CACHE[cache_key] = float(result.x)
    return _RHO_CACHE[cache_key]


def compute_team_strengths(season: str, rho_seasons: list = None) -> dict:
    """Calcule les forces d'equipe (attack, defense, home_advantage) par MLE
    conjointe pour une saison (mise en cache), + rho (mis en cache separement,
    voir fit_global_rho pour le role de rho_seasons - etape M5)."""
    strengths = dict(_get_season_strengths(season))
    strengths["rho"] = fit_global_rho(rho_seasons)
    return strengths


def predict_match_from_strengths(strengths_data: dict, home_team: str, away_team: str) -> dict:
    attack = strengths_data["attack"]
    defense = strengths_data["defense"]
    home_adv = strengths_data["home_advantage"]
    rho = strengths_data["rho"]

    if home_team not in attack or away_team not in attack:
        raise ValueError("Equipe inconnue pour cette saison")

    exp_home_goals = np.exp(attack[home_team] + defense[away_team] + home_adv)
    exp_away_goals = np.exp(attack[away_team] + defense[home_team])

    matrix = np.zeros((MAX_GOALS + 1, MAX_GOALS + 1))
    for i in range(MAX_GOALS + 1):
        for j in range(MAX_GOALS + 1):
            p = poisson.pmf(i, exp_home_goals) * poisson.pmf(j, exp_away_goals)
            p *= _dixon_coles_tau_vec(np.array([i]), np.array([j]), np.array([exp_home_goals]), np.array([exp_away_goals]), rho)[0]
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
        "expected_home_goals": round(float(exp_home_goals), 2),
        "expected_away_goals": round(float(exp_away_goals), 2),
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
