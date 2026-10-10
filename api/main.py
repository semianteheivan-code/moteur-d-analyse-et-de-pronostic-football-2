from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from zoneinfo import ZoneInfo
from engine import analyze_match
from daily_batch import run_daily_batch
from db.database import get_connection
from config import DEFAULT_TRAIN_SEASON, DEFAULT_FIXTURES_DAYS, REFERENCE_TIMEZONE
from sources.five_dollar_football import (
    get_la_liga_fixtures_cached,
    get_fixture_odds_cached,
    find_fixture,
)

app = FastAPI(title="Moteur de pronostic football - API locale")


class MatchRequest(BaseModel):
    home_team: str
    away_team: str
    train_season: Optional[str] = None


@app.get("/health")
def health():
    conn = get_connection()
    row = conn.execute("SELECT MAX(date) as last_match_date FROM matches").fetchone()
    return {
        "status": "ok",
        "last_match_date_in_db": row["last_match_date"] if row else None,
    }


@app.get("/fixtures")
def fixtures(days: Optional[int] = None):
    days = min(days or DEFAULT_FIXTURES_DAYS, 14)  # garde-fou simple contre un usage abusif du quota
    today = datetime.now(ZoneInfo(REFERENCE_TIMEZONE)).replace(hour=0, minute=0, second=0, microsecond=0)
    raw_fixtures = get_la_liga_fixtures_cached(today, days)
    result = [
        {
            "home_team": fx["teams"]["home"]["name"],
            "away_team": fx["teams"]["away"]["name"],
            "kickoff_utc": fx["kickoff_utc"],
            "odds": get_fixture_odds_cached(fx["id"]),
        }
        for fx in raw_fixtures
    ]
    return {
        "league": "La Liga",
        "days": days,
        "reference_date": today.date().isoformat(),
        "fixtures": result,
    }


@app.post("/analyze")
def analyze(req: MatchRequest):
    """
    Le client choisit quel match il veut analyser (home_team/away_team),
    mais ne fournit jamais ni la date ni les cotes : le moteur retrouve le
    match lui-meme dans ce qu'il couvre (La Liga, fenetre de DEFAULT_FIXTURES_DAYS
    jours) et recupere ses cotes automatiquement. home_team doit etre
    l'equipe qui joue a domicile (l'avantage du terrain change le calcul) :
    si le sens est inverse, le match ne sera pas trouve.
    """
    train_season = req.train_season or DEFAULT_TRAIN_SEASON
    fx = find_fixture(req.home_team, req.away_team, DEFAULT_FIXTURES_DAYS)
    if fx is None:
        return {
            "status": "match_not_available",
            "home_team": req.home_team,
            "away_team": req.away_team,
            "reason": (
                f"aucun match trouve entre ces deux equipes dans les "
                f"{DEFAULT_FIXTURES_DAYS} prochains jours couverts (La Liga) - "
                f"verifiez que home_team est bien l'equipe qui recoit"
            ),
        }
    match_date = fx["kickoff_utc"][:10]
    odds = get_fixture_odds_cached(fx["id"])
    return analyze_match(req.home_team, req.away_team, match_date, train_season, odds=odds)


class ComboDefinitionInput(BaseModel):
    name: str
    min_odds: float
    max_odds: float


class DailyBatchRequest(BaseModel):
    train_season: Optional[str] = None
    combo_definitions: List[ComboDefinitionInput]
    batch_date: Optional[str] = None  # format "YYYY-MM-DD", par defaut aujourd'hui (Africa/Abidjan)
    save: bool = True  # False = simulation, n'enregistre rien dans predictions


@app.post("/daily-batch")
def daily_batch(req: DailyBatchRequest):
    """
    Le client ne fournit plus les matchs ni leurs cotes : le moteur recupere
    lui-meme les matchs La Liga du jour demande (ou aujourd'hui par defaut,
    en heure d'Abidjan) et leurs cotes. Le client garde la main sur les
    fourchettes de combines demandees (combo_definitions), la date a traiter
    (batch_date) et s'il veut enregistrer le resultat ou juste simuler (save).
    """
    if req.batch_date:
        day = datetime.strptime(req.batch_date, "%Y-%m-%d")
    else:
        day = datetime.now(ZoneInfo(REFERENCE_TIMEZONE)).replace(hour=0, minute=0, second=0, microsecond=0)
    batch_date = day.date().isoformat()

    raw_fixtures = get_la_liga_fixtures_cached(day, 1)
    if not raw_fixtures:
        return {
            "status": "no_matches_available",
            "batch_date": batch_date,
            "reason": "aucun match La Liga ce jour-la",
        }

    fixtures = [
        {
            "home_team": fx["teams"]["home"]["name"],
            "away_team": fx["teams"]["away"]["name"],
            "odds": get_fixture_odds_cached(fx["id"]),
        }
        for fx in raw_fixtures
    ]
    combo_definitions = [c.model_dump() for c in req.combo_definitions]
    train_season = req.train_season or DEFAULT_TRAIN_SEASON
    return run_daily_batch(fixtures, train_season, combo_definitions, batch_date, save=req.save)
