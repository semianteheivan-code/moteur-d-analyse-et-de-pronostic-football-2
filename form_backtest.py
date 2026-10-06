from collections import defaultdict
from db.database import get_connection
from models.form_adjustment import predict_match_blended

VALUE_THRESHOLD = 0.05
SEASON_PAIRS = [
    ("2122", "2223"),
    ("2223", "2324"),
    ("2324", "2425"),
    ("2425", "2526"),
]


def implied_prob(odds):
    return 1 / odds if odds else None


def evaluate_alpha(alpha: float) -> dict:
    buckets = defaultdict(lambda: {"count": 0, "hits": 0})
    bankroll = {"bets": 0, "staked": 0.0, "returned": 0.0}
    conn = get_connection()

    for train_season, test_season in SEASON_PAIRS:
        matches = conn.execute(
            "SELECT home_team, away_team, date, result, home_goals, away_goals, "
            "odds_home, odds_draw, odds_away, odds_over25, odds_under25 "
            "FROM matches WHERE season = ? AND home_goals IS NOT NULL",
            (test_season,),
        ).fetchall()

        for m in matches:
            try:
                probs = predict_match_blended(m["home_team"], m["away_team"], m["date"], train_season, alpha)
            except ValueError:
                continue

            actual_1n2 = {"H": "1", "D": "X", "A": "2"}[m["result"]]
            actual_ou = "over" if (m["home_goals"] + m["away_goals"]) > 2.5 else "under"

            bucket = round(probs["1"], 1)
            buckets[bucket]["count"] += 1
            if actual_1n2 == "1":
                buckets[bucket]["hits"] += 1

            markets = [
                ("1", probs["1"], m["odds_home"], actual_1n2 == "1"),
                ("X", probs["X"], m["odds_draw"], actual_1n2 == "X"),
                ("2", probs["2"], m["odds_away"], actual_1n2 == "2"),
                ("over_2.5", probs["over_2.5"], m["odds_over25"], actual_ou == "over"),
                ("under_2.5", probs["under_2.5"], m["odds_under25"], actual_ou == "under"),
            ]
            for label, model_prob, odds, won in markets:
                if odds is None:
                    continue
                market_prob = implied_prob(odds)
                if model_prob - market_prob >= VALUE_THRESHOLD:
                    bankroll["bets"] += 1
                    bankroll["staked"] += 1
                    if won:
                        bankroll["returned"] += odds

    profit = bankroll["returned"] - bankroll["staked"]
    roi = (profit / bankroll["staked"] * 100) if bankroll["staked"] else 0

    # Ecart moyen absolu de calibration, pondere par le nombre de matchs par tranche
    total_matches = sum(b["count"] for b in buckets.values())
    calib_error = sum(
        abs(b["hits"] / b["count"] - bucket) * b["count"]
        for bucket, b in buckets.items() if b["count"] > 0
    ) / total_matches if total_matches else None

    return {
        "alpha": alpha, "bets": bankroll["bets"], "roi": round(roi, 2),
        "calibration_error_pct": round(calib_error * 100, 2) if calib_error else None,
        "buckets": dict(buckets),
    }


if __name__ == "__main__":
    print(f"{'alpha':<8}{'paris':<8}{'ROI':<10}{'erreur calib. moy.'}")
    for alpha in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]:
        r = evaluate_alpha(alpha)
        print(f"{r['alpha']:<8}{r['bets']:<8}{r['roi']:>+.1f}%{'':<4}{r['calibration_error_pct']:.2f} points")
