import pandas as pd
from db.database import get_connection

BASE_URL = "http://api.clubelo.com/{team}"

# Nom du club sur clubelo.com -> nom utilisé dans nos tables (référence football-data.co.uk)
CLUBELO_TO_FD = {
    "Alaves": "Alaves",
    "AthBilbao": "Ath Bilbao",
    "AthMadrid": "Ath Madrid",
    "Barcelona": "Barcelona",
    "Betis": "Betis",
    "Celta": "Celta",
    "Espanyol": "Espanol",
    "Getafe": "Getafe",
    "Girona": "Girona",
    "LasPalmas": "Las Palmas",
    "Leganes": "Leganes",
    "Mallorca": "Mallorca",
    "Osasuna": "Osasuna",
    "RealMadrid": "Real Madrid",
    "Sevilla": "Sevilla",
    "Sociedad": "Sociedad",
    "Valencia": "Valencia",
    "Valladolid": "Valladolid",
    "Vallecano": "Vallecano",
    "Villarreal": "Villarreal",
}


def fetch_team_history(clubelo_name: str) -> pd.DataFrame:
    url = BASE_URL.format(team=clubelo_name)
    return pd.read_csv(url)


def store_team(clubelo_name: str, fd_name: str):
    df = fetch_team_history(clubelo_name)
    conn = get_connection()
    inserted = 0
    for _, row in df.iterrows():
        conn.execute(
            "INSERT OR IGNORE INTO team_elo (team, date, elo) VALUES (?, ?, ?)",
            (fd_name, row["From"], float(row["Elo"])),
        )
        inserted += 1
    conn.commit()
    print(f"{fd_name} : {inserted} lignes traitées.")


if __name__ == "__main__":
    for clubelo_name, fd_name in CLUBELO_TO_FD.items():
        try:
            store_team(clubelo_name, fd_name)
        except Exception as e:
            print(f"{fd_name} ignoré : {e}")