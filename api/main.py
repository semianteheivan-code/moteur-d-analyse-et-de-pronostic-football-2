from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional, List
from engine import analyze_match
from daily_batch import run_daily_batch
from db.database import get_connection
from config import DEFAULT_TRAIN_SEASON

app = FastAPI(title="Moteur de pronostic football - API locale")


class OddsInput(BaseModel):
    home: Optional[float] = None
    draw: Optional[float] = None
    away: Optional[float] = None
    over_25: Optional[float] = None
    under_25: Optional[float] = None


class MatchRequest(BaseModel):
    home_team: str
    away_team: str
    match_date: str
    train_season: Optional[str] = None
    odds: Optional[OddsInput] = None


def _odds_to_dict(odds: Optional[OddsInput]) -> Optional[dict]:
    if not odds:
        return None
    return {
        "1": odds.home, "X": odds.draw, "2": odds.away,
        "over_2.5": odds.over_25, "under_2.5": odds.under_25,
    }


@app.get("/health")
def health():
    conn = get_connection()
    row = conn.execute("SELECT MAX(date) as last_match_date FROM matches").fetchone()
    return {
        "status": "ok",
        "last_match_date_in_db": row["last_match_date"] if row else None,
    }


@app.post("/analyze")
def analyze(req: MatchRequest):
    train_season = req.train_season or DEFAULT_TRAIN_SEASON
    return analyze_match(req.home_team, req.away_team, req.match_date, train_season,
                          odds=_odds_to_dict(req.odds))


class FixtureInput(BaseModel):
    home_team: str
    away_team: str
    odds: Optional[OddsInput] = None


class ComboDefinitionInput(BaseModel):
    name: str
    min_odds: float
    max_odds: float


class DailyBatchRequest(BaseModel):
    fixtures: List[FixtureInput]
    train_season: Optional[str] = None
    combo_definitions: List[ComboDefinitionInput]
    batch_date: Optional[str] = None


@app.post("/daily-batch")
def daily_batch(req: DailyBatchRequest):
    fixtures = [
        {"home_team": f.home_team, "away_team": f.away_team, "odds": _odds_to_dict(f.odds)}
        for f in req.fixtures
    ]
    combo_definitions = [c.model_dump() for c in req.combo_definitions]
    train_season = req.train_season or DEFAULT_TRAIN_SEASON
    return run_daily_batch(fixtures, train_season, combo_definitions, req.batch_date)
