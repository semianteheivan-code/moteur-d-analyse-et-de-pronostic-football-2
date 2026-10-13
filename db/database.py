import sqlite3
from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY,
    season TEXT,
    date TEXT NOT NULL,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    home_goals INTEGER,
    away_goals INTEGER,
    result TEXT,
    home_shots INTEGER, away_shots INTEGER,
    home_shots_target INTEGER, away_shots_target INTEGER,
    home_corners INTEGER, away_corners INTEGER,
    home_yellow INTEGER, away_yellow INTEGER,
    home_red INTEGER, away_red INTEGER,
    odds_home REAL, odds_draw REAL, odds_away REAL,
    odds_over25 REAL, odds_under25 REAL,
    UNIQUE (date, home_team, away_team)
);

CREATE TABLE IF NOT EXISTS match_xg (
    date TEXT NOT NULL,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    home_xg REAL,
    away_xg REAL,
    UNIQUE (date, home_team, away_team)
);

CREATE TABLE IF NOT EXISTS team_elo (
    team TEXT NOT NULL,
    date TEXT NOT NULL,
    elo REAL,
    UNIQUE (team, date)
);

CREATE TABLE IF NOT EXISTS raw_cache (
    key TEXT PRIMARY KEY,
    payload TEXT,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    match_date TEXT NOT NULL,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    market TEXT NOT NULL,
    outcome TEXT NOT NULL,
    probability REAL NOT NULL,
    bookmaker_odds REAL,
    confidence REAL,
    actual_result TEXT,
    fixture_id TEXT,
    league TEXT
);

-- Etape 9 : compteur de requetes reseau reelles vers l'API live, une ligne par appel,
-- pour calculer une fenetre glissante (COUNT(*) WHERE requested_at > maintenant - fenetre).
CREATE TABLE IF NOT EXISTS api_requests (
    id INTEGER PRIMARY KEY,
    requested_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_api_requests_requested_at ON api_requests(requested_at);
"""


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _migrate_predictions_table(conn):
    """
    Ajoute fixture_id/league a une base deja existante (prerequis pour une
    future boucle d'auto-calibration, 13/10/2026). CREATE TABLE IF NOT
    EXISTS ne modifie jamais une table deja creee - une vraie migration est
    donc necessaire pour les bases qui existaient avant cet ajout. Verifie
    d'abord les colonnes presentes (PRAGMA table_info) pour pouvoir etre
    relancee sans risque (idempotente) : SQLite ne supporte pas
    "ADD COLUMN IF NOT EXISTS" directement.
    """
    existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(predictions)").fetchall()}
    if "fixture_id" not in existing_columns:
        conn.execute("ALTER TABLE predictions ADD COLUMN fixture_id TEXT")
    if "league" not in existing_columns:
        conn.execute("ALTER TABLE predictions ADD COLUMN league TEXT")


def init_db():
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        _migrate_predictions_table(conn)
        conn.commit()
