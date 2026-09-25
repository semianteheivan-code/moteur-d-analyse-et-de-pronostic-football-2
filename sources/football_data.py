import pandas as pd
from datetime import datetime
from db.database import get_connection
from config import FOOTBALL_DATA_CODE

BASE_URL = "https://www.football-data.co.uk/mmz4281/{season}/{code}.csv"


def fetch_season(season: str) -> pd.DataFrame:
    """Télécharge le CSV d'une saison (ex: '2425') pour le championnat configuré."""
    url = BASE_URL.format(season=season, code=FOOTBALL_DATA_CODE)
    df = pd.read_csv(url)
    return df


def _parse_date(raw_date: str) -> str:
    """football-data utilise dd/mm/yy ou dd/mm/yyyy selon les saisons."""
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(raw_date, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"Format de date inconnu : {raw_date}")


def _get(row, col):
    """Récupère une colonne si elle existe, sinon None (certaines cotes manquent selon les saisons)."""
    return row[col] if col in row and pd.notna(row[col]) else None


def store_season(season: str):
    df = fetch_season(season)
    conn = get_connection()
    inserted = 0
    for _, row in df.iterrows():
        if pd.isna(row.get("HomeTeam")) or pd.isna(row.get("Date")):
            continue
        conn.execute(
            """
            INSERT OR IGNORE INTO matches (
                season, date, home_team, away_team,
                home_goals, away_goals, result,
                home_shots, away_shots, home_shots_target, away_shots_target,
                home_corners, away_corners, home_yellow, away_yellow,
                home_red, away_red,
                odds_home, odds_draw, odds_away, odds_over25, odds_under25
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                season, _parse_date(row["Date"]), row["HomeTeam"], row["AwayTeam"],
                _get(row, "FTHG"), _get(row, "FTAG"), _get(row, "FTR"),
                _get(row, "HS"), _get(row, "AS"), _get(row, "HST"), _get(row, "AST"),
                _get(row, "HC"), _get(row, "AC"), _get(row, "HY"), _get(row, "AY"),
                _get(row, "HR"), _get(row, "AR"),
                _get(row, "B365H"), _get(row, "B365D"), _get(row, "B365A"),
                _get(row, "B365>2.5"), _get(row, "B365<2.5"),
            ),
        )
        inserted += 1
    conn.commit()
    print(f"Saison {season} : {inserted} lignes traitées.")


if __name__ == "__main__":
    from config import SEASONS
    for season in SEASONS:
        try:
            store_season(season)
        except Exception as e:
            print(f"Saison {season} ignorée : {e}")