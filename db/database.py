import sqlite3
from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY,
    season TEXT,
    league TEXT,
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
    league TEXT,
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


def _migrate_league_column(conn, table: str):
    """
    Ajoute la colonne league a une table matches/match_xg deja existante
    (chantier Premier League, 13/10/2026), et remplit les lignes deja
    presentes avec 'la_liga' (seul championnat collecte jusqu'ici) - sans
    ce remplissage, ces lignes deviendraient invisibles a toute requete
    future filtree par league (WHERE league = ?).

    Cree aussi un nouvel index unique (league, date, home_team, away_team)
    en plus de l'ancien UNIQUE (date, home_team, away_team) : SQLite ne
    permet pas de modifier une contrainte UNIQUE existante par un simple
    ALTER TABLE (il faudrait reconstruire toute la table). L'ancienne
    contrainte reste donc active mais est sans consequence pratique : elle
    ne bloquerait que deux equipes de meme nom, jouant l'une contre l'autre,
    a la meme date, dans deux championnats differents - un cas qui ne se
    presente pas entre La Liga et Premier League.
    """
    existing_columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if "league" not in existing_columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN league TEXT")
    conn.execute(f"UPDATE {table} SET league = 'la_liga' WHERE league IS NULL")
    conn.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{table}_league_date_teams "
        f"ON {table}(league, date, home_team, away_team)"
    )


def init_db():
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        _migrate_predictions_table(conn)
        _migrate_league_column(conn, "matches")
        _migrate_league_column(conn, "match_xg")
        conn.commit()
