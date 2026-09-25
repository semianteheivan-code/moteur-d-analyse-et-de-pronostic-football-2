# Traduit un nom d'équipe Understat vers le nom équivalent utilisé par football-data.co.uk.
# football-data.co.uk sert de référence, car il couvre plus de saisons et d'équipes.
UNDERSTAT_TO_FD = {
    "Athletic Club": "Ath Bilbao",
    "Atletico Madrid": "Ath Madrid",
    "Real Betis": "Betis",
    "Celta Vigo": "Celta",
    "Espanyol": "Espanol",
    "Real Sociedad": "Sociedad",
    "Real Valladolid": "Valladolid",
    "Rayo Vallecano": "Vallecano",
}


def normalize(team_name: str) -> str:
    return UNDERSTAT_TO_FD.get(team_name, team_name)