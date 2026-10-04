import numpy as np
from collections import defaultdict
from db.database import get_connection
from features.form import compute_match_features
from models.poisson import compute_team_strengths, predict_match_from_strengths
from models.ml import FEATURE_KEYS, ALL_SEASONS, make_model, _result_to_label, build_dataset

VALUE_THRESHOLD = 0.05


def build_dataset_with_odds(season_pairs):
    conn = get_connection()
    rows_X, rows_y, rows_odds = [], [], []
    for train_season, test_season in season_pairs:
        strengths = compute_team_strengths(train_season)
        matches = conn.execute(
            "SELECT home_team, away_team, date, result, odds_home, odds_draw, odds_away "
            "FROM matches WHERE season = ? AND home_goals IS NOT NULL",
            (test_season,),
        ).fetchall()
        for m in matches:
            try:
                poisson_probs = predict_match_from_strengths(strengths, m["home_team"], m["away_team"])
            except ValueError:
                continue
            feats = compute_match_features(m["home_team"], m["away_team"], m["date"])
            row = [feats.get(k) for k in FEATURE_KEYS]
            row += [poisson_probs["1"], poisson_probs["X"], poisson_probs["2"]]
            rows_X.append(row)
            rows_y.append(_result_to_label(m["result"]))
            rows_odds.append({"1": m["odds_home"], "X": m["odds_draw"], "2": m["odds_away"]})
    return np.array(rows_X, dtype=float), np.array(rows_y), rows_odds


def implied_prob(odds):
    return 1 / odds if odds else None


def evaluate_ml_calibration_and_roi():
    buckets = defaultdict(lambda: {"count": 0, "hits": 0})
    bankroll = {"bets": 0, "staked": 0.0, "returned": 0.0}

    for i in range(2, len(ALL_SEASONS)):
        test_season = ALL_SEASONS[i]
        train_seasons = ALL_SEASONS[:i]
        train_pairs = [(train_seasons[j], train_seasons[j + 1]) for j in range(len(train_seasons) - 1)]

        X_train, y_train = build_dataset(train_pairs)
        X_test, y_test, odds_test = build_dataset_with_odds([(train_seasons[-1], test_season)])

        model = make_model()
        model.fit(X_train, y_train)
        class_order = list(model.classes_)

        probs = model.predict_proba(X_test)

        for i_match in range(len(y_test)):
            p = dict(zip(class_order, probs[i_match]))
            actual = y_test[i_match]
            odds = odds_test[i_match]

            bucket = round(p.get("1", 0), 1)
            buckets[bucket]["count"] += 1
            if actual == "1":
                buckets[bucket]["hits"] += 1

            for label in ["1", "X", "2"]:
                o = odds.get(label)
                if o is None:
                    continue
                market_prob = implied_prob(o)
                model_prob = p.get(label, 0)
                if model_prob - market_prob >= VALUE_THRESHOLD:
                    bankroll["bets"] += 1
                    bankroll["staked"] += 1
                    if actual == label:
                        bankroll["returned"] += o

    print("=== Calibration ML (victoire domicile) ===")
    for b in sorted(buckets.keys()):
        d = buckets[b]
        rate = d["hits"] / d["count"] if d["count"] else 0
        print(f"  ~{b:.0%} annonce -> {rate:.1%} realise (sur {d['count']} matchs)")

    print("\n=== Rentabilite ML (value bets 1N2, seuil 5%) ===")
    print(f"Paris : {bankroll['bets']}, mise : {bankroll['staked']:.1f}, rendu : {bankroll['returned']:.1f}")
    profit = bankroll["returned"] - bankroll["staked"]
    roi = (profit / bankroll["staked"] * 100) if bankroll["staked"] else 0
    print(f"Profit/perte : {profit:+.1f} unites (ROI {roi:+.1f}%)")


if __name__ == "__main__":
    evaluate_ml_calibration_and_roi()
