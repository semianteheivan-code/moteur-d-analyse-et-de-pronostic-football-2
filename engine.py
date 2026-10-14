from db.database import get_connection
from models.poisson import compute_team_strengths, predict_match_from_strengths
from models.cards_corners import predict_stat
from features.form import compute_match_features
from sources.team_names import normalize

MISSING_DATA_REFUSAL_THRESHOLD = 0.40  # section 7 du cahier des charges
SUSPICIOUS_EDGE_THRESHOLD = 0.20  # M4 : au-dela, edge suspect (cote obsolete/erreur probable), pas une vraie opportunite
MIN_MATCHES_FOR_STRENGTH = 5  # D1 (13/10/2026) : nombre minimum de matchs joues cette saison
# avant qu'une equipe soit autorisee a entrer dans le calcul de force (compute_team_strengths).
# Avant cette etape, une equipe avec 0 match etait deja refusee (insufficient_history), mais
# une equipe avec 1 a 4 matchs passait sans protection, avec un risque reel d'estimation
# instable (trop peu de donnees pour l'optimisation conjointe attaque/defense/avantage
# domicile). Aligne sur FORM_WINDOW (features/form.py) pour rester coherent.

SIMPLE_MARKETS = ["1", "X", "2", "over_2.5", "under_2.5"]
DOUBLE_CHANCE_MARKETS = ["1X", "X2", "12"]
STAT_MARKETS = ["corners_over_9.5", "corners_under_9.5", "cards_over_4.5", "cards_under_4.5"]
# Marches eligibles pour le calcul de "marche le plus sur" : tout sauf le Double
# Chance (probabilite mecaniquement gonflee, somme de deux issues simples).
SAFEST_ELIGIBLE_MARKETS = SIMPLE_MARKETS + STAT_MARKETS

_KNOWN_TEAMS_CACHE = {}
_SEASON_MATCH_COUNTS_CACHE = {}


def _known_teams(league: str) -> set:
    """
    Equipes connues du moteur, desormais PAR CHAMPIONNAT (13/10/2026,
    chantier Premier League) : avant la colonne league, un nom d'equipe
    connu dans n'importe quel championnat etait accepte partout - sans
    consequence tant qu'un seul championnat existait, mais incorrect des
    qu'un deuxieme est onboarde (un nom d'equipe valide en Premier League
    n'a aucune raison d'etre reconnu quand league="la_liga", et inversement).
    """
    if league not in _KNOWN_TEAMS_CACHE:
        conn = get_connection()
        rows = conn.execute(
            "SELECT DISTINCT home_team FROM matches WHERE league = ? "
            "UNION SELECT DISTINCT away_team FROM matches WHERE league = ?",
            (league, league),
        ).fetchall()
        _KNOWN_TEAMS_CACHE[league] = {r[0] for r in rows}
    return _KNOWN_TEAMS_CACHE[league]


def resolve_team_names(home_team: str, away_team: str, league: str):
    """
    Normalise les deux noms d'equipe et renvoie (home, away, unknown), ou
    unknown est la liste des noms (normalises) non reconnus par le moteur
    POUR CE CHAMPIONNAT, dans l'ordre donne. A appeler avant toute recherche
    de match (A11) : permet de distinguer un nom mal ecrit d'un match
    reellement absent, sans lancer toute l'analyse.
    """
    home = normalize(home_team)
    away = normalize(away_team)
    known = _known_teams(league)
    unknown = [t for t in (home, away) if t not in known]
    return home, away, unknown


def _team_match_counts_in_season(season: str, league: str) -> dict:
    """
    Nombre de matchs joues par chaque equipe dans la saison et le
    championnat donnes (D1, 13/10/2026 ; filtre league ajoute le meme jour
    pour le chantier Premier League). Remplace l'ancienne _teams_in_season()
    qui ne verifiait que la presence (0 match -> refuse), pas le volume reel
    de donnees disponibles pour estimer la force de l'equipe.
    """
    cache_key = (season, league)
    if cache_key not in _SEASON_MATCH_COUNTS_CACHE:
        conn = get_connection()
        rows = conn.execute(
            """
            SELECT team, COUNT(*) AS cnt FROM (
                SELECT home_team AS team FROM matches WHERE season = ? AND league = ? AND home_goals IS NOT NULL
                UNION ALL
                SELECT away_team AS team FROM matches WHERE season = ? AND league = ? AND home_goals IS NOT NULL
            )
            GROUP BY team
            """,
            (season, league, season, league),
        ).fetchall()
        _SEASON_MATCH_COUNTS_CACHE[cache_key] = {r["team"]: r["cnt"] for r in rows}
    return _SEASON_MATCH_COUNTS_CACHE[cache_key]


def _compute_confidence(feats: dict) -> float:
    checks = [
        feats.get("home_form_matches", 0) >= 3,
        feats.get("away_form_matches", 0) >= 3,
        feats.get("home_xg_for") is not None,
        feats.get("away_xg_for") is not None,
        feats.get("h2h_matches", 0) >= 1,
    ]
    return sum(checks) / len(checks)


def _stat_markets(home_team: str, away_team: str, train_season: str, league: str) -> dict:
    """
    Marches corners/cartons : jamais de cote disponible dans notre source actuelle,
    uniquement probabilite + total attendu, a titre informatif.
    """
    entries = {}
    for stat, threshold, over_key, under_key in [
        ("corners", 9.5, "corners_over_9.5", "corners_under_9.5"),
        ("cards", 4.5, "cards_over_4.5", "cards_under_4.5"),
    ]:
        try:
            pred = predict_stat(home_team, away_team, train_season, league, stat)
        except ValueError:
            continue
        entries[over_key] = {"probability": pred["over"], "expected_total": pred["expected_total"]}
        entries[under_key] = {"probability": pred["under"], "expected_total": pred["expected_total"]}
    return entries


def analyze_match(home_team: str, away_team: str, match_date: str, train_season: str, league: str, odds: dict = None) -> dict:
    home_team, away_team, unknown = resolve_team_names(home_team, away_team, league)
    if unknown:
        return {
            "status": "unknown_team",
            "home_team": home_team,
            "away_team": away_team,
            "unknown": unknown,
            "reason": f"equipe(s) non reconnue(s) : {', '.join(unknown)}",
        }

    match_counts = _team_match_counts_in_season(train_season, league)
    insufficient_teams = [
        t for t in (home_team, away_team)
        if match_counts.get(t, 0) < MIN_MATCHES_FOR_STRENGTH
    ]
    if insufficient_teams:
        details = ", ".join(
            f"{t} ({match_counts.get(t, 0)} match(s) joue(s))" for t in insufficient_teams
        )
        return {
            "status": "insufficient_history",
            "home_team": home_team,
            "away_team": away_team,
            "train_season": train_season,
            "reason": (
                f"historique trop court pour la saison {train_season} "
                f"(minimum {MIN_MATCHES_FOR_STRENGTH} matchs requis) : {details} "
                f"(probablement promue, recemment transferee ou saison a peine commencee)"
            ),
        }

    feats = compute_match_features(home_team, away_team, match_date, league)
    confidence = _compute_confidence(feats)

    if confidence < (1 - MISSING_DATA_REFUSAL_THRESHOLD):
        return {
            "status": "refused",
            "home_team": home_team,
            "away_team": away_team,
            "reason": "donnees insuffisantes (plus de 40% des facteurs cles manquants)",
            "confidence": round(confidence, 2),
        }

    strengths = compute_team_strengths(train_season, league)
    probs = predict_match_from_strengths(strengths, home_team, away_team)

    markets = {}
    for label in SIMPLE_MARKETS + DOUBLE_CHANCE_MARKETS:
        model_prob = probs.get(label)
        entry = {"probability": model_prob}
        if odds and odds.get(label):
            market_prob = 1 / odds[label]
            edge = model_prob - market_prob
            entry.update({
                "market_odds": odds[label],
                "market_implied_probability": round(market_prob, 4),
                "edge": round(edge, 4),
                "value_bet": edge >= 0.05,
                "suspicious": edge >= SUSPICIOUS_EDGE_THRESHOLD,
            })
        markets[label] = entry

    # Corners / cartons : jamais de cote disponible, probabilite seule.
    markets.update(_stat_markets(home_team, away_team, train_season, league))

    opportunities = sorted(
        (
            {"market": label, **entry}
            for label, entry in markets.items()
            if entry.get("value_bet") and not entry.get("suspicious")
        ),
        key=lambda x: x["edge"] * confidence,
        reverse=True,
    )

    safest_candidates = {
        k: v for k, v in markets.items()
        if k in SAFEST_ELIGIBLE_MARKETS and not v.get("suspicious")
    }
    safest_market = max(safest_candidates.items(), key=lambda kv: kv[1]["probability"])[0]

    return {
        "status": "ok",
        "home_team": home_team,
        "away_team": away_team,
        "match_date": match_date,
        "confidence": round(confidence, 2),
        "markets": markets,
        "opportunities_sorted_by_edge": opportunities,
        "safest_market": safest_market,
    }


def analyze_matches(requests: list) -> list:
    return [
        analyze_match(
            r["home_team"], r["away_team"], r["match_date"], r["train_season"], r["league"],
            odds=r.get("odds"),
        )
        for r in requests
    ]


if __name__ == "__main__":
    import json
    example_requests = [
        {
            "home_team": "Real Madrid", "away_team": "Barcelona",
            "match_date": "2026-01-01", "train_season": "2425", "league": "la_liga",
            "odds": {"1": 1.90, "X": 3.60, "2": 4.20, "over_2.5": 1.85, "under_2.5": 1.95},
        },
    ]
    results = analyze_matches(example_requests)
    print(json.dumps(results, indent=2, ensure_ascii=False))
