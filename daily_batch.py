import json
from datetime import datetime, date, timezone, timedelta
from db.database import get_connection
from engine import analyze_matches
from combo_builder import build_combo


def kickoff_has_passed(kickoff_utc: str, margin_minutes: float = 0, now: datetime = None) -> bool:
    """
    True si le coup d'envoi est deja passe, ou si - avec la marge demandee
    (margin_minutes) - il est trop proche pour etre encore parie dessus.
    Centralise ici (etape A10) pour que daily_batch et l'API appliquent
    exactement la meme regle, au lieu de la recoder chacun de leur cote.
    """
    now = now or datetime.now(timezone.utc)
    kickoff = datetime.fromisoformat(kickoff_utc.replace("Z", "+00:00"))
    return kickoff <= now + timedelta(minutes=margin_minutes)


def run_daily_batch(fixtures: list, train_season: str, combo_definitions: list,
                     batch_date: str = None, save: bool = True,
                     min_minutes_before_kickoff: float = 0, league_key: str = None) -> dict:
    """
    fixtures : liste de dicts {home_team, away_team, odds, kickoff_utc (optionnel),
        fixture_id (optionnel), league (optionnel)}, les matchs du jour.
        kickoff_utc (ISO 8601, ex. "2026-10-11T18:00:00Z") permet d'exclure des
        combines les matchs deja commences (etape A10) ; un fixture sans
        kickoff_utc reste eligible par defaut (compatibilite avec les appelants
        qui ne le fournissent pas encore). fixture_id et league (etape A14),
        s'ils sont fournis, sont propages tels quels dans "details", dans les
        selections de chaque combine, ET dans la table predictions (prerequis
        auto-calibration, 13/10/2026) - un fixture qui ne les fournit pas
        garde simplement ces champs a null, sans erreur (compatibilite). Ce
        champ "league" est un nom d'AFFICHAGE (ex. "Premier League"), jamais
        utilise pour filtrer la base - voir league_key ci-dessous.
    train_season : saison utilisee pour calculer les forces du modele.
    league_key : cle interne du championnat (ex. "la_liga", "premier_league",
        telle que stockee dans la colonne league de matches/match_xg) -
        ajoutee le 13/10/2026 (chantier Premier League). Un batch donne
        couvre toujours un seul championnat a la fois (un seul appel a la
        source de fixtures en direct), donc une seule valeur suffit pour
        tout le batch. A ne pas confondre avec le champ "league" (affichage)
        de chaque fixture ci-dessus.
    combo_definitions : liste de dicts {name, min_odds, max_odds} -
        chaque entree demande un combine dans cette fourchette, sous ce nom.
        Ce nom et cette fourchette sont decides par l'appelant (le bot, un autre
        recepteur...), jamais codes en dur ici.
    batch_date : date du batch (par defaut aujourd'hui), utilisee pour les features.
    save : si False, n'enregistre rien dans predictions (simulation) - l'analyse,
        les combines et le detail renvoye sont identiques dans les deux cas.
        Par defaut True, donc le comportement ne change pas pour un appelant
        qui ne precise pas ce parametre.
    min_minutes_before_kickoff : marge minimale (en minutes) avant le coup
        d'envoi pour qu'un match reste eligible a un combine (etape A10).
        0 par defaut (seuls les matchs deja commences sont exclus). Les
        matchs exclus des combines restent presents dans "details" (utile
        pour comparer pronostic et resultat une fois le match termine).
    """
    batch_date = batch_date or date.today().isoformat()

    # Associe chaque match (par home_team/away_team) a son fixture_id et son
    # league d'AFFICHAGE d'origine (etape A14), pour les reattacher apres
    # analyze_matches (qui ne connait pas ces champs et les renverrait tel
    # quel sinon absents).
    fixture_info_by_pair = {
        (f["home_team"], f["away_team"]): {
            "fixture_id": f.get("fixture_id"),
            "league": f.get("league"),
        }
        for f in fixtures
    }

    requests = [
        {**f, "match_date": batch_date, "train_season": train_season, "league": league_key}
        for f in fixtures
    ]
    # kickoff_utc et fixture_id ne sont pas des champs attendus par
    # engine.analyze_match - on les retire des requetes envoyees au moteur,
    # mais kickoff_utc sert ci-dessous a filtrer les candidats aux combines,
    # et fixture_id/league (affichage) sont reattaches apres coup via
    # fixture_info_by_pair. Le champ "league" de chaque requete a deja ete
    # remplace ci-dessus par league_key (la cle interne) : c'est celle que
    # engine.analyze_match attend pour filtrer la base, jamais le nom
    # d'affichage.
    for r in requests:
        r.pop("kickoff_utc", None)
        r.pop("fixture_id", None)

    analyzed = analyze_matches(requests)

    # Reattache fixture_id et league (affichage) a chaque match analyse (etape A14).
    for m in analyzed:
        info = fixture_info_by_pair.get((m["home_team"], m["away_team"]), {})
        m["fixture_id"] = info.get("fixture_id")
        m["league"] = info.get("league")

    now = datetime.now(timezone.utc)
    excluded_pairs = {
        (f["home_team"], f["away_team"])
        for f in fixtures
        if f.get("kickoff_utc") and kickoff_has_passed(f["kickoff_utc"], min_minutes_before_kickoff, now)
    }
    combo_eligible = [
        m for m in analyzed
        if (m["home_team"], m["away_team"]) not in excluded_pairs
    ]

    combos = {
        c["name"]: build_combo(combo_eligible, c["min_odds"], c["max_odds"])
        for c in combo_definitions
    }

    if save:
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
                        market, outcome, probability, bookmaker_odds, confidence,
                        fixture_id, league
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        created_at, batch_date, m["home_team"], m["away_team"],
                        market_label, market_label, market_data["probability"],
                        market_data.get("market_odds"), m["confidence"],
                        m.get("fixture_id"), m.get("league"),
                    ),
                )
        conn.commit()

    return {
        "batch_date": batch_date,
        "matches_analyzed": len(analyzed),
        "matches_ok": sum(1 for m in analyzed if m["status"] == "ok"),
        "combos": combos,
        "details": analyzed,
        "saved": save,
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
                              combo_definitions=combo_definitions, batch_date="2026-01-01",
                              league_key="la_liga")

    print(f"Matchs analyses : {result['matches_analyzed']} (dont {result['matches_ok']} reussis)")
    for name, combo in result["combos"].items():
        print(f"\n=== Combine {name} ===")
        print(json.dumps(combo, indent=2, ensure_ascii=False))
