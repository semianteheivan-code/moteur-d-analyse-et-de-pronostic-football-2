from pathlib import Path

# --- Chemins ---
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "moteur.db"
DATA_DIR.mkdir(exist_ok=True)

# --- Championnat de la v1 ---
LEAGUE_NAME = "La Liga"
FOOTBALL_DATA_CODE = "SP1"      # code du championnat sur football-data.co.uk
UNDERSTAT_LEAGUE = "La_Liga"    # nom utilise par Understat

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

# --- Championnats supportes (etape 5a A7, etendue A13) ---
# Une entree par championnat : nom officiel (ce que le moteur renvoie partout
# ailleurs, champ "name"), pays (affichage cote client), surnoms (minuscules,
# matches sans tenir compte des majuscules ni des espaces en trop - A16).
# L'ordre de la liste est l'ordre d'affichage souhaite (A13). Ajouter un
# championnat ne demande qu'une entree ici cote contrat API - un seul est
# reellement couvert aujourd'hui (aucune colonne league en base, SP1/Understat
# "La Liga" codes en dur ci-dessus) : onboarder reellement un 2e championnat
# (historique, team_names.py, etc.) reste un chantier a part.
LEAGUES = [
    {
        "key": "la_liga",
        "name": "La Liga",
        "country": "Espagne",
        "aliases": ["la liga", "liga", "laliga", "espagne", "spain", "sp1"],
    },
]
DEFAULT_LEAGUE = "la_liga"

# Garde la forme simple (cle -> nom officiel) utilisee par le code existant
# (A7) - derivee de LEAGUES, une seule source de verite.
SUPPORTED_LEAGUES = {entry["key"]: entry["name"] for entry in LEAGUES}

# --- Protection de quota (etape 9) ---
# Le fournisseur (5DollarFootballAPI) annonce 60 requetes/heure. On se fixe une
# limite configurable plus basse par securite (marge pour eviter de taper pile
# la limite reelle du fournisseur).
API_QUOTA_LIMIT_PER_HOUR = 50
API_QUOTA_WINDOW_MINUTES = 60
