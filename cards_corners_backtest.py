from collections import defaultdict
from db.database import get_connection
from models.cards_corners import compute_stat_strengths, predict_stat

SEASON_PAIRS = [
    ("2122", "2223"),
    ("2223", "2324"),
    ("2324", "2425"),
    ("2425", "2526"),
]


def calibration_error(stat: str, shrinkage_lambda: float) -> dict:
    buckets = defaultdict(lambda: {"count": 0, "hits": 0})
    conn = get_connection()

    for train_season, test_season in SEASON_PAIRS:
        try:
            compute_stat_strengths(train_season, stat, shrinkage_lambda)
        except ValueError:
            continue

        if stat == "corners":
            rows = conn.execute("""
                SELECT home_team, away_team, home_corners, away_corners FROM matches
                WHERE season = ? AND home_corners IS NOT NULL
                  AND (home_corners + away_corners) <= 24 AND ABS(home_corners - away_corners) <= 15
            """, (test_season,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT home_team, away_team,
                       (home_yellow + home_red) as home_cards,
                       (away_yellow + away_red) as away_cards
                FROM matches WHERE season = ? AND home_yellow IS NOT NULL
                  AND (home_yellow + home_red + away_yellow + away_red) <= 16
            """, (test_season,)).fetchall()

        for r in rows:
            try:
                pred = predict_stat(r["home_team"], r["away_team"], train_season, stat, shrinkage_lambda)
            except ValueError:
                continue
            actual_total = (r["home_corners"] + r["away_corners"]) if stat == "corners" else (r["home_cards"] + r["away_cards"])
            actual_over = actual_total > pred["threshold"]

            bucket = round(pred["over"], 1)
            buckets[bucket]["count"] += 1
            if actual_over:
                buckets[bucket]["hits"] += 1

    total = sum(b["count"] for b in buckets.values())
    error = sum(abs(b["hits"] / b["count"] - bucket) * b["count"] for bucket, b in buckets.items() if b["count"] > 0)
    return {"buckets": dict(buckets), "mean_error_pct": round(error / total * 100, 2) if total else None}


if __name__ == "__main__":
    for stat in ["corners", "cards"]:
        print(f"\n=== {stat} ===")
        print(f"{'lambda':<10}{'erreur calib. moy.'}")
        for lam in [0.0, 0.01, 0.03, 0.05, 0.1, 0.2]:
            result = calibration_error(stat, lam)
            print(f"{lam:<10}{result['mean_error_pct']:.2f} points")
