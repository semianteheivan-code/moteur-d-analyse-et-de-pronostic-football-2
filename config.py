from pathlib import Path

# --- Chemins ---
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "moteur.db"
DATA_DIR.mkdir(exist_ok=True)

# --- Championnat de la v1 ---
LEAGUE_NAME = "La Liga"
FOOTBALL_DATA_CODE = "SP1"      # code du championnat sur football-data.co.uk
UNDERSTAT_LEAGUE = "La_Liga"    # nom utilisé par Understat

# --- Saisons historiques (format football-data : "2526" = 2025-2026) ---
SEASONS = ["2122", "2223", "2324", "2425", "2526", "2627"]

# --- Règles du cahier des charges ---
CACHE_TTL_HOURS = 48       # expiration du cache brut
MAX_MISSING_RATIO = 0.40   # au-delà, le moteur refuse de prédire