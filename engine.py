from db.database import get_connection
from models.poisson import compute_team_strengths, predict_match_from_strengths
from models.cards_corners import predict_stat
from features.form import compute_match_features
from sources.team_names import normalize

MISSING_DATA_REFUSAL_THRESHOLD = 0.40  # section 7 du cahier des charges
SUSPICIOUS_EDGE_THRESHOLD = 0.20  # M4 : au-dela, edge suspect (cote obsolete/erreur probable), pas une vraie opportunite

SIMPLE_MARKETS = ["1", "X", "2", "over_2.5", "under_2.5"]
DOUBLE_CHANCE_MARKETS = ["1X", "X2", "12"]
STAT_MARKETS = ["corners_over_9.5", "corners_under_9.5", "cards_over_4.5", "cards_under_4.5"]
# Marches eligibles pour le calcul de "marche le plus sur" : tout sauf le Double
# Chance (probabilite mecaniquement gonflee, somme de deux issues simples).
SAFEST_ELIGIBLE_MARKETS = SIMPLE_MARKETS + STAT_MARKETS

_KNOWN_TEAMS_CACHE = None
_SEASON_TEAMS_CACHE = {}


def _known_teams() -> set:
    global _KNOWN_TEAMS_CACHE
    if _KNOWN_TEAMS_CACHE is None:
        conn = get_connection()
        rows = conn.execute("SELECT DISTINCT home_team FROM matches UNION SELECT DISTINCT away_team FROM matches").fetchall()
        _KNOWN_TEAMS_CACHE = {r[0] for r in rows}
    return _KNOWN_TEAMS_CACHE


def _teams_in_season(season: str) -> set:
    if season not in _SEASON_TEAMS_CACHE:
        conn = get_connection()
        rows = conn.execute(
            "SELECT DISTINCT home_team FROM matches WHERE season = ? "
            "UNION SELECT DISTINCT away_team FROM matches WHERE season = ?",
            (season, season),
        ).fetchall()
        _SEASON_TEAMS_CACHE[season] = {r[0] for r in rows}
    return _SEASON_TEAMS_CACHE[season]


def _compute_confidence(feats: dict) -> float:
    checks = [
        feats.get("home_form_matches", 0) >= 3,
        feats.get("away_form_matches", 0) >= 3,
        feats.get("home_xg_for") is not None,
        feats.get("away_xg_for") is not None,
        feats.get("h2h_matches", 0) >= 1,
    ]
    return sum(checks) / len(checks)


def _stat_markets(home_team: str, away_team: str, train_season: str) -> dict:
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
            pred = predict_stat(home_team, away_team, train_season, stat)
        except ValueError:
            continue
        entries[over_key] = {"probability": pred["over"], "expected_total": pred["expected_total"]}
        entries[under_key] = {"probability": pred["under"], "expected_total": pred["expected_total"]}
    return entries


def analyze_match(home_team: str, away_team: str, match_date: str, train_season: str, odds: dict = None) -> dict:
    home_team = normalize(home_team)
    away_team = normalize(away_team)

    known = _known_teams()
    unknown = [t for t in (home_team, away_team) if t not in known]
    if unknown:
        return {
            "status": "unknown_team",
            "home_team": home_team,
            "away_team": away_team,
            "reason": f"equipe(s) non reconnue(s) : {', '.join(unknown)}",
        }

    season_teams = _teams_in_season(train_season)
    missing_from_season = [t for t in (home_team, away_team) if t not in season_teams]
    if missing_from_season:
        return {
            "status": "insufficient_history",
            "home_team": home_team,
            "away_team": away_team,
            "train_season": train_season,
            "reason": (
                f"equipe(s) sans historique pour la saison {train_season} : "
                f"{', '.join(missing_from_season)} (probablement promue ou reversee)"
            ),
        }

    feats = compute_match_features(home_team, away_team, match_date)
    confidence = _compute_confidence(feats)

    if confidence < (1 - MISSING_DATA_REFUSAL_THRESHOLD):
        return {
            "status": "refused",
            "home_team": home_team,
            "away_team": away_team,
            "reason": "donnees insuffisantes (plus de 40% des facteurs cles manquants)",
            "confidence": round(confidence, 2),
        }

    strengths = compute_team_strengths(train_season)
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
    markets.update(_stat_markets(home_team, away_team, train_season))

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
            r["home_team"], r["away_team"], r["match_date"], r["train_season"],
            odds=r.get("odds"),
        )
        for r in requests
    ]


if __name__ == "__main__":
    import json
    example_requests = [
        {
            "home_team": "Real Madrid", "away_team": "Barcelona",
            "match_date": "2026-01-01", "train_season": "2425",
            "odds": {"1": 1.90, "X": 3.60, "2": 4.20, "over_2.5": 1.85, "under_2.5": 1.95},
        },
    ]
    results = analyze_matches(example_requests)
    print(json.dumps(results, indent=2, ensure_ascii=False))
