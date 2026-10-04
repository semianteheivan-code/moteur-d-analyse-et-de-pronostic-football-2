from models.poisson import compute_team_strengths, predict_match_from_strengths
from features.form import compute_match_features

MISSING_DATA_REFUSAL_THRESHOLD = 0.40  # section 7 du cahier des charges


def _compute_confidence(feats: dict) -> float:
    checks = [
        feats.get("home_form_matches", 0) >= 3,
        feats.get("away_form_matches", 0) >= 3,
        feats.get("home_xg_for") is not None,
        feats.get("away_xg_for") is not None,
        feats.get("h2h_matches", 0) >= 1,
    ]
    return sum(checks) / len(checks)


def analyze_match(home_team: str, away_team: str, match_date: str, train_season: str, odds: dict = None) -> dict:
    feats = compute_match_features(home_team, away_team, match_date)
    confidence = _compute_confidence(feats)

    if confidence < (1 - MISSING_DATA_REFUSAL_THRESHOLD):
        return {
            "status": "refused",
            "reason": "donnees insuffisantes (plus de 40% des facteurs cles manquants)",
            "confidence": round(confidence, 2),
        }

    strengths = compute_team_strengths(train_season)
    probs = predict_match_from_strengths(strengths, home_team, away_team)

    markets = {}
    for label in ["1", "X", "2", "over_2.5", "under_2.5"]:
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
            })
        markets[label] = entry

    opportunities = sorted(
        ({"market": label, **entry} for label, entry in markets.items() if entry.get("value_bet")),
        key=lambda x: x["edge"] * confidence,
        reverse=True,
    )

    safest_market = max(markets.items(), key=lambda kv: kv[1]["probability"])[0]

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


if __name__ == "__main__":
    import json
    example_odds = {"1": 1.90, "X": 3.60, "2": 4.20, "over_2.5": 1.85, "under_2.5": 1.95}
    result = analyze_match("Real Madrid", "Barcelona", "2026-01-01", train_season="2425", odds=example_odds)
    print(json.dumps(result, indent=2, ensure_ascii=False))
