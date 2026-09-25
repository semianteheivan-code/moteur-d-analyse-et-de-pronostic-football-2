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
    actual_result TEXT
);
"""


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_connection() as conn:
        conn.executescript(SCHEMA)