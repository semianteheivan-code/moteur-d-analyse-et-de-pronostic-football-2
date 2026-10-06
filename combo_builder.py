from itertools import combinations

MAX_SELECTIONS = 4  # nombre max de paris dans un combine, pour limiter la combinatoire


def _candidate_bets(analyzed_matches: list) -> list:
    """
    Extrait, de chaque match analyse avec succes, le marche le plus sur
    (highest probability), comme candidat pour un combine.
    """
    candidates = []
    for m in analyzed_matches:
        if m["status"] != "ok":
            continue
        label = m["safest_market"]
        market = m["markets"][label]
        if market.get("market_odds") is None:
            continue
        candidates.append({
            "home_team": m["home_team"],
            "away_team": m["away_team"],
            "market": label,
            "probability": market["probability"],
            "odds": market["market_odds"],
        })
    return candidates


def build_combo(analyzed_matches: list, min_total_odds: float, max_total_odds: float) -> dict:
    """
    Construit un combine dont la cote totale tombe dans [min_total_odds, max_total_odds].
    Cherche la combinaison avec la plus haute probabilite combinee (le combine le
    plus "sur" possible dans la fourchette demandee), pas la cote la plus elevee.
    """
    candidates = _candidate_bets(analyzed_matches)
    candidates.sort(key=lambda c: c["probability"], reverse=True)

    best = None
    for n in range(1, min(MAX_SELECTIONS, len(candidates)) + 1):
        for combo in combinations(candidates, n):
            total_odds = 1.0
            total_prob = 1.0
            for c in combo:
                total_odds *= c["odds"]
                total_prob *= c["probability"]

            if min_total_odds <= total_odds <= max_total_odds:
                if best is None or total_prob > best["combined_probability"]:
                    best = {
                        "selections": list(combo),
                        "total_odds": round(total_odds, 2),
                        "combined_probability": round(total_prob, 4),
                    }

    if best is None:
        return {
            "status": "no_combo_found",
            "reason": f"aucune combinaison trouvee dans la fourchette {min_total_odds}-{max_total_odds}",
        }

    return {"status": "ok", **best}


if __name__ == "__main__":
    import json
    from engine import analyze_matches

    example_requests = [
        {"home_team": "Real Madrid", "away_team": "Barcelona", "match_date": "2026-01-01", "train_season": "2425",
         "odds": {"1": 1.90, "X": 3.60, "2": 4.20, "over_2.5": 1.85, "under_2.5": 1.95}},
        {"home_team": "Betis", "away_team": "Ath Bilbao", "match_date": "2026-01-01", "train_season": "2425",
         "odds": {"1": 2.20, "X": 3.30, "2": 3.40, "over_2.5": 1.90, "under_2.5": 1.90}},
        {"home_team": "Sevilla", "away_team": "Villarreal", "match_date": "2026-01-01", "train_season": "2425",
         "odds": {"1": 2.60, "X": 3.20, "2": 2.70, "over_2.5": 2.00, "under_2.5": 1.75}},
    ]
    analyzed = analyze_matches(example_requests)

    print("=== Combine SAFE (cote totale 2-3) ===")
    print(json.dumps(build_combo(analyzed, 2.0, 3.0), indent=2, ensure_ascii=False))

    print("\n=== Combine MEDIUM (cote totale 3-5) ===")
    print(json.dumps(build_combo(analyzed, 3.0, 5.0), indent=2, ensure_ascii=False))
