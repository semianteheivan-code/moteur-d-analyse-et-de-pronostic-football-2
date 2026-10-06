import json
from datetime import datetime, date
from db.database import get_connection
from engine import analyze_matches
from combo_builder import build_combo


def run_daily_batch(fixtures: list, train_season: str, combo_definitions: list, batch_date: str = None) -> dict:
    """
    fixtures : liste de dicts {home_team, away_team, odds}, les matchs du jour.
    train_season : saison utilisee pour calculer les forces du modele.
    combo_definitions : liste de dicts {name, min_odds, max_odds} -
        chaque entree demande un combine dans cette fourchette, sous ce nom.
        Ce nom et cette fourchette sont decides par l'appelant (le bot, un autre
        recepteur...), jamais codes en dur ici.
    batch_date : date du batch (par defaut aujourd'hui), utilisee pour les features.
    """
    batch_date = batch_date or date.today().isoformat()

    requests = [
        {**f, "match_date": batch_date, "train_season": train_season}
        for f in fixtures
    ]
    analyzed = analyze_matches(requests)

    combos = {
        c["name"]: build_combo(analyzed, c["min_odds"], c["max_odds"])
        for c in combo_definitions
    }

    conn = get_connection()
    created_at = datetime.now().isoformat()

    for m in analyzed:
        if m["status"] != "ok":
            continue
        for market_label, market_data in m["markets"].items():
            if market_data.get("probability") is None:
                continue
            conn.execute(
                """
                INSERT INTO predictions (
                    created_at, match_date, home_team, away_team,
                    market, outcome, probability, bookmaker_odds, confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at, batch_date, m["home_team"], m["away_team"],
                    market_label, market_label, market_data["probability"],
                    market_data.get("market_odds"), m["confidence"],
                ),
            )
    conn.commit()

    return {
        "batch_date": batch_date,
        "matches_analyzed": len(analyzed),
        "matches_ok": sum(1 for m in analyzed if m["status"] == "ok"),
        "combos": combos,
        "details": analyzed,
    }


if __name__ == "__main__":
    example_fixtures = [
        {"home_team": "Real Madrid", "away_team": "Barcelona",
         "odds": {"1": 1.90, "X": 3.60, "2": 4.20, "over_2.5": 1.85, "under_2.5": 1.95}},
        {"home_team": "Betis", "away_team": "Ath Bilbao",
         "odds": {"1": 2.20, "X": 3.30, "2": 3.40, "over_2.5": 1.90, "under_2.5": 1.90}},
        {"home_team": "Sevilla", "away_team": "Villarreal",
         "odds": {"1": 2.60, "X": 3.20, "2": 2.70, "over_2.5": 2.00, "under_2.5": 1.75}},
    ]

    # Ici, c'est NOUS qui decidons ces noms et fourchettes pour le test -
    # exactement comme le bot Telegram le ferait de son cote, mais ce n'est
    # pas une connaissance du moteur, juste un choix de l'appelant.
    combo_definitions = [
        {"name": "SAFE", "min_odds": 2.0, "max_odds": 3.0},
        {"name": "MEDIUM", "min_odds": 3.0, "max_odds": 5.0},
    ]

    result = run_daily_batch(example_fixtures, train_season="2425",
                              combo_definitions=combo_definitions, batch_date="2026-01-01")

    print(f"Matchs analyses : {result['matches_analyzed']} (dont {result['matches_ok']} reussis)")
    for name, combo in result["combos"].items():
        print(f"\n=== Combine {name} ===")
        print(json.dumps(combo, indent=2, ensure_ascii=False))
