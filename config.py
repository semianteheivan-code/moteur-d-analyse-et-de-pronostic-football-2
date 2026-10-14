from pathlib import Path

# --- Chemins ---
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "moteur.db"
DATA_DIR.mkdir(exist_ok=True)

# --- Saisons historiques (format football-data : "2526" = 2025-2026) ---
SEASONS = ["2122", "2223", "2324", "2425", "2526", "2627"]

# --- Regles du cahier des charges ---
CACHE_TTL_HOURS = 48       # expiration du cache brut
MAX_MISSING_RATIO = 0.40   # au-dela, le moteur refuse de predire

# --- Valeur par defaut pour train_season (A5, bilan du 10/10) ---
DEFAULT_TRAIN_SEASON = "2526"  # saison la plus proche de 2627 en cours

# --- Fuseau de reference : public actuel et vise par le bot (Cote d'Ivoire) ---
REFERENCE_TIMEZONE = "Africa/Abidjan"

# --- Parametres pour /fixtures (etape 2, A1 + D2) ---
DEFAULT_FIXTURES_DAYS = 3
FIXTURES_CACHE_TTL_HOURS = 12   # cache du calendrier (change rarement)
ODDS_CACHE_TTL_HOURS = 2        # cache des cotes (bouge plus vite)

# --- Championnats supportes (etape 5a A7, etendue A13, onboarding Premier
# League le 13/10/2026) --------------------------------------------------
# Une entree par championnat : nom officiel (champ "name"), pays (affichage
# cote client), surnoms (minuscules, matches sans tenir compte des
# majuscules ni des espaces en trop - A16), et les 3 identifiants source
# necessaires pour collecter son historique/ses matchs en direct :
#   - football_data_code : code du championnat sur football-data.co.uk
#   - understat_league   : nom utilise par Understat (xG)
#   - five_dollar_api_id : identifiant numerique du championnat cote
#     5DollarFootballAPI (calendrier/cotes en direct, pas encore utilise
#     pour Premier League - sources/five_dollar_football.py reste pour
#     l'instant code en dur sur La Liga, generalisation prevue plus tard)
# L'ordre de la liste est l'ordre d'affichage souhaite (A13).
LEAGUES = [
    {
        "key": "la_liga",
        "name": "La Liga",
        "country": "Espagne",
        "aliases": ["la liga", "liga", "laliga", "espagne", "spain", "sp1"],
        "football_data_code": "SP1",
        "understat_league": "La_Liga",
        "five_dollar_api_id": 4212821298,
    },
    {
        "key": "premier_league",
        "name": "Premier League",
        "country": "Angleterre",
        "aliases": ["premier league", "epl", "angleterre", "england", "england premier league", "e0"],
        "football_data_code": "E0",
        "understat_league": "EPL",
        "five_dollar_api_id": 4160026622,
    },
]
DEFAULT_LEAGUE = "la_liga"

# Garde la forme simple (cle -> nom officiel) utilisee par le code existant
# (A7) - derivee de LEAGUES, une seule source de verite.
SUPPORTED_LEAGUES = {entry["key"]: entry["name"] for entry in LEAGUES}

# Acces direct a l'entree complete d'un championnat par sa cle (nouveau,
# 13/10/2026) - utilise par sources/football_data.py et sources/understat.py
# pour retrouver football_data_code/understat_league sans dependre de
# constantes globales figees sur un seul championnat.
LEAGUE_BY_KEY = {entry["key"]: entry for entry in LEAGUES}

# --- Protection de quota (etape 9, corrigee le 14/10/2026 - abonnement Pro) ---
# Le palier gratuit annoncait 60 requetes/heure (fenetre horaire). Le palier
# Pro fonctionne differemment : confirme via GET /v1/status le 13/10/2026,
# c'est un vrai plafond PAR MINUTE (rate_limit=10, rate_window_seconds=60),
# pas un total horaire. Une fenetre glissante d'une heure ne protegeait pas
# contre une rafale de plusieurs appels en quelques secondes qui depasserait
# quand meme la vraie limite du fournisseur - la fenetre doit donc suivre la
# meme granularite (secondes), pas une approximation horaire.
API_QUOTA_LIMIT_PER_WINDOW = 8     # marge de securite sous les 10/min reels
API_QUOTA_WINDOW_SECONDS = 60
