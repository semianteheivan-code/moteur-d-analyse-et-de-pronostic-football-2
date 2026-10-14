from understatapi import UnderstatClient
from db.database import get_connection
from config import LEAGUE_BY_KEY, DEFAULT_LEAGUE
from sources.team_names import normalize

# Understat designe une saison par son annee de debut ("2024" = saison 2024-2025).
# football-data.co.uk utilise "2425". On convertit entre les deux formats.
def _to_understat_season(fd_season: str) -> str:
    return "20" + fd_season[:2]


def store_season(fd_season: str, league_key: str = DEFAULT_LEAGUE):
    understat_season = _to_understat_season(fd_season)
    understat_league = LEAGUE_BY_KEY[league_key]["understat_league"]
    conn = get_connection()
    inserted = 0
    skipped = 0

    with UnderstatClient() as understat:
        matches = understat.league(league=understat_league).get_match_data(season=understat_season)

    for m in matches:
        # Un match pas encore joue n'a pas de xG utilisable.
        if not m.get("isResult"):
            continue
        try:
            home_team = normalize(m["h"]["title"])
            away_team = normalize(m["a"]["title"])
            date = m["datetime"][:10]  # "YYYY-MM-DD HH:MM:SS" -> "YYYY-MM-DD"
            home_xg = float(m["xG"]["h"])
            away_xg = float(m["xG"]["a"])
        except (KeyError, TypeError, ValueError):
            skipped += 1
            continue

        conn.execute(
            """
            INSERT OR IGNORE INTO match_xg (league, date, home_team, away_team, home_xg, away_xg)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (league_key, date, home_team, away_team, home_xg, away_xg),
        )
        inserted += 1

    conn.commit()
    print(f"[{league_key}] Saison {fd_season} (Understat {understat_season}) : {inserted} lignes traitees, {skipped} ignorees.")


if __name__ == "__main__":
    from config import SEASONS
    for season in SEASONS:
        try:
            store_season(season, DEFAULT_LEAGUE)
        except Exception as e:
            print(f"Saison {season} ignoree : {e}")
