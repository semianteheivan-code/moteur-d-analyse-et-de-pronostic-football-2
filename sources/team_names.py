# Traduit un nom d'equipe (Understat ou variante courante) vers le nom
# equivalent utilise par football-data.co.uk (notre reference).
UNDERSTAT_TO_FD = {
    "Athletic Club": "Ath Bilbao",
    "Athletic Bilbao": "Ath Bilbao",
    "Atletico Madrid": "Ath Madrid",
    "Atletico de Madrid": "Ath Madrid",
    "Real Betis": "Betis",
    "Celta Vigo": "Celta",
    "Espanyol": "Espanol",
    "Real Sociedad": "Sociedad",
    "Real Valladolid": "Valladolid",
    "Rayo Vallecano": "Vallecano",
    "Racing Santander": "Santander",
    "CD Alaves": "Alaves",
        "Deportivo A Coruna": "La Coruna",
}


def normalize(team_name: str) -> str:
    return UNDERSTAT_TO_FD.get(team_name, team_name)
