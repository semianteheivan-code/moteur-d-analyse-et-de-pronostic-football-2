from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
from engine import analyze_match

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
    train_season: str
    odds: Optional[OddsInput] = None


@app.post("/analyze")
def analyze(req: MatchRequest):
    odds_dict = None
    if req.odds:
        odds_dict = {
            "1": req.odds.home, "X": req.odds.draw, "2": req.odds.away,
            "over_2.5": req.odds.over_25, "under_2.5": req.odds.under_25,
        }
    return analyze_match(req.home_team, req.away_team, req.match_date, req.train_season, odds=odds_dict)
