from collections import defaultdict
from models.poisson import compute_team_strengths, predict_match_from_strengths
from db.database import get_connection

VALUE_THRESHOLD = 0.05  # marge minimale entre proba modèle et proba implicite pour parier


def run_backtest_pair(train_season: str, test_season: str, buckets, stats):
    strengths_data = compute_team_strengths(train_season)
    conn = get_connection()
    matches = conn.execute(
        "SELECT home_team, away_team, home_goals, away_goals, result FROM matches "
        "WHERE season = ? AND home_goals IS NOT NULL",
        (test_season,),
    ).fetchall()

    for m in matches:
        try:
            probs = predict_match_from_strengths(strengths_data, m["home_team"], m["away_team"])
        except ValueError:
            continue

        predicted = max(("1", "X", "2"), key=lambda k: probs[k])
        actual_key = {"H": "1", "D": "X", "A": "2"}[m["result"]]

        if predicted == actual_key:
            stats["correct"] += 1
        stats["total"] += 1

        bucket = round(probs["1"], 1)
        buckets[bucket]["count"] += 1
        if actual_key == "1":
            buckets[bucket]["hits"] += 1


def run_full_backtest():
    season_pairs = [
        ("2122", "2223"),
        ("2223", "2324"),
        ("2324", "2425"),
        ("2425", "2526"),
    ]

    buckets = defaultdict(lambda: {"count": 0, "hits": 0})
    stats = {"correct": 0, "total": 0}

    for train, test in season_pairs:
        run_backtest_pair(train, test, buckets, stats)
        print(f"  {train} -> {test} traité (cumul : {stats['total']} matchs)")

    print(f"\n=== Backtest cumulé sur {len(season_pairs)} couples de saisons ===")
    print(f"Taux de réussite (issue la plus probable) : {stats['correct']}/{stats['total']} = {stats['correct']/stats['total']:.1%}\n")

    print("Calibration (probabilité annoncée de victoire domicile vs réalité) :")
    for bucket in sorted(buckets.keys()):
        data = buckets[bucket]
        actual_rate = data["hits"] / data["count"] if data["count"] else 0
        print(f"  ~{bucket:.0%} annoncé -> {actual_rate:.1%} réalisé (sur {data['count']} matchs)")


def implied_prob(odds):
    return 1 / odds if odds else None


def run_value_bet_backtest(train_season: str, test_season: str, bankroll_state):
    # Forces (et rho) calculées UNE FOIS pour la saison d'entraînement, pas à chaque match.
    strengths_data = compute_team_strengths(train_season)

    conn = get_connection()
    matches = conn.execute(
        "SELECT home_team, away_team, home_goals, away_goals, result, "
        "odds_home, odds_draw, odds_away, odds_over25, odds_under25 "
        "FROM matches WHERE season = ? AND home_goals IS NOT NULL",
        (test_season,),
    ).fetchall()

    for m in matches:
        try:
            probs = predict_match_from_strengths(strengths_data, m["home_team"], m["away_team"])
        except ValueError:
            continue

        actual_1n2 = {"H": "1", "D": "X", "A": "2"}[m["result"]]
        actual_ou = "over" if (m["home_goals"] + m["away_goals"]) > 2.5 else "under"

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
                bankroll_state["bets"] += 1
                bankroll_state["staked"] += 1
                bankroll_state[label + "_staked"] = bankroll_state.get(label + "_staked", 0) + 1
                if won:
                    bankroll_state["returned"] += odds
                    bankroll_state[label + "_returned"] = bankroll_state.get(label + "_returned", 0) + odds
                    bankroll_state[label + "_wins"] = bankroll_state.get(label + "_wins", 0) + 1
                bankroll_state[label + "_bets"] = bankroll_state.get(label + "_bets", 0) + 1


def run_full_value_backtest():
    season_pairs = [
        ("2122", "2223"),
        ("2223", "2324"),
        ("2324", "2425"),
        ("2425", "2526"),
    ]

    bankroll_state = {"bets": 0, "staked": 0.0, "returned": 0.0}

    for train, test in season_pairs:
        run_value_bet_backtest(train, test, bankroll_state)

    print(f"\n=== Test de rentabilité (value bets détectés, seuil {VALUE_THRESHOLD:.0%}) ===")
    print(f"Nombre de paris simulés : {bankroll_state['bets']}")
    print(f"Total misé : {bankroll_state['staked']:.1f} unités")
    print(f"Total retourné : {bankroll_state['returned']:.1f} unités")
    profit = bankroll_state["returned"] - bankroll_state["staked"]
    roi = (profit / bankroll_state["staked"] * 100) if bankroll_state["staked"] else 0
    print(f"Profit/perte : {profit:+.1f} unités (ROI : {roi:+.1f}%)")

    print("\nDétail par marché :")
    for label in ["1", "X", "2", "over_2.5", "under_2.5"]:
        bets = bankroll_state.get(label + "_bets", 0)
        wins = bankroll_state.get(label + "_wins", 0)
        staked = bankroll_state.get(label + "_staked", 0)
        returned = bankroll_state.get(label + "_returned", 0.0)
        market_profit = returned - staked
        market_roi = (market_profit / staked * 100) if staked else 0

        if bets == 0:
            print(f"  {label:10s} : aucun value bet détecté")
            continue

        win_rate = wins / bets
        print(
            f"  {label:10s} : {bets:4d} paris | "
            f"réussite {win_rate:5.1%} | "
            f"misé {staked:5.1f} | rendu {returned:6.1f} | "
            f"profit {market_profit:+6.1f} (ROI {market_roi:+5.1f}%)"
        )


if __name__ == "__main__":
    print(">>> Backtest de calibration\n")
    run_full_backtest()

    print("\n" + "=" * 60)
    print(">>> Backtest de rentabilité (value bets vs cotes réelles)")
    run_full_value_backtest()