from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional, List, Dict, Union
from datetime import datetime
from zoneinfo import ZoneInfo
from engine import analyze_match
from daily_batch import run_daily_batch
from db.database import get_connection
from config import DEFAULT_TRAIN_SEASON, DEFAULT_FIXTURES_DAYS, REFERENCE_TIMEZONE, SUPPORTED_LEAGUES, DEFAULT_LEAGUE
from sources.five_dollar_football import (
    get_la_liga_fixtures_cached,
    get_fixture_odds_cached,
    find_fixture,
)

app = FastAPI(title="Moteur de pronostic football - API locale")


# --- Modeles de reponse (etape 5b, A6+A8) -----------------------------------
# Declares a partir des JSON reellement observes pendant les tests de cette
# conversation, sauf mention contraire ci-dessous. Utilises uniquement via
# responses={...} (documentation dans /docs et openapi.json) - jamais via
# response_model, donc aucune validation n'est forcee a l'execution : une
# reponse reelle qui ne correspondrait pas exactement a ces schemas ne
# plantera pas l'appel.

class HealthResponse(BaseModel):
    status: str
    last_match_date_in_db: Optional[str] = None


class FixtureItem(BaseModel):
    home_team: str
    away_team: str
    kickoff_utc: str
    odds: Dict[str, float]


class FixturesOkResponse(BaseModel):
    league: str
    days: int
    reference_date: str
    fixtures: List[FixtureItem]


class LeagueNotAvailableResponse(BaseModel):
    status: str
    league: str
    reason: str


class MarketEntry(BaseModel):
    probability: Optional[float] = None
    market_odds: Optional[float] = None
    market_implied_probability: Optional[float] = None
    edge: Optional[float] = None
    value_bet: Optional[bool] = None
    expected_total: Optional[float] = None


class OpportunityEntry(MarketEntry):
    market: str


class AnalyzeOkResponse(BaseModel):
    status: str
    home_team: str
    away_team: str
    match_date: str
    confidence: float
    markets: Dict[str, MarketEntry]
    opportunities_sorted_by_edge: List[OpportunityEntry]
    safest_market: str


class MatchNotAvailableResponse(BaseModel):
    status: str
    home_team: str
    away_team: str
    reason: str


class UnknownTeamResponse(BaseModel):
    # Declenche en appelant directement engine.analyze_match (meme fonction
    # qu'utilise cet endpoint une fois le match trouve), pas via /analyze
    # lui-meme - voir le registre de decisions de la feuille de route.
    status: str
    home_team: str
    away_team: str
    reason: str


class InsufficientHistoryResponse(BaseModel):
    # Meme remarque que UnknownTeamResponse.
    status: str
    home_team: str
    away_team: str
    train_season: str
    reason: str


class RefusedResponse(BaseModel):
    # Meme remarque que UnknownTeamResponse.
    status: str
    home_team: str
    away_team: str
    reason: str
    confidence: float


class ComboResult(BaseModel):
    status: str
    selections: Optional[list] = None
    total_odds: Optional[float] = None
    combined_probability: Optional[float] = None
    reason: Optional[str] = None


class DailyBatchOkResponse(BaseModel):
    batch_date: str
    matches_analyzed: int
    matches_ok: int
    combos: Dict[str, ComboResult]
    details: List[dict]
    saved: bool


class NoMatchesAvailableResponse(BaseModel):
    status: str
    batch_date: str
    reason: str


def _unsupported_league_response(league: str) -> dict:
    return {
        "status": "league_not_available",
        "league": league,
        "reason": (
            f"championnat non disponible : '{league}'. "
            f"Championnats couverts actuellement : {', '.join(SUPPORTED_LEAGUES)}"
        ),
    }


class MatchRequest(BaseModel):
    home_team: str
    away_team: str
    train_season: Optional[str] = None
    league: Optional[str] = None


@app.get("/health", responses={200: {"model": HealthResponse}})
def health():
    conn = get_connection()
    row = conn.execute("SELECT MAX(date) as last_match_date FROM matches").fetchone()
    return {
        "status": "ok",
        "last_match_date_in_db": row["last_match_date"] if row else None,
    }


@app.get(
    "/fixtures",
    responses={200: {"model": Union[FixturesOkResponse, LeagueNotAvailableResponse]}},
)
def fixtures(days: Optional[int] = None, league: Optional[str] = None):
    league = (league or DEFAULT_LEAGUE).lower()
    if league not in SUPPORTED_LEAGUES:
        return _unsupported_league_response(league)

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
        "league": SUPPORTED_LEAGUES[league],
        "days": days,
        "reference_date": today.date().isoformat(),
        "fixtures": result,
    }


@app.post(
    "/analyze",
    responses={
        200: {
            "model": Union[
                AnalyzeOkResponse,
                MatchNotAvailableResponse,
                LeagueNotAvailableResponse,
                UnknownTeamResponse,
                InsufficientHistoryResponse,
                RefusedResponse,
            ]
        }
    },
)
def analyze(req: MatchRequest):
    """
    Le client choisit quel match il veut analyser (home_team/away_team),
    mais ne fournit jamais ni la date ni les cotes : le moteur retrouve le
    match lui-meme dans ce qu'il couvre (La Liga, fenetre de DEFAULT_FIXTURES_DAYS
    jours) et recupere ses cotes automatiquement. home_team doit etre
    l'equipe qui joue a domicile (l'avantage du terrain change le calcul) :
    si le sens est inverse, le match ne sera pas trouve.

    Statuts possibles : ok, match_not_available, league_not_available,
    unknown_team, insufficient_history, refused (ces trois derniers viennent
    de engine.analyze_match - voir sa docstring pour leurs conditions exactes).
    """
    league = (req.league or DEFAULT_LEAGUE).lower()
    if league not in SUPPORTED_LEAGUES:
        return _unsupported_league_response(league)

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
    league: Optional[str] = None


@app.post(
    "/daily-batch",
    responses={
        200: {
            "model": Union[
                DailyBatchOkResponse,
                NoMatchesAvailableResponse,
                LeagueNotAvailableResponse,
            ]
        }
    },
)
def daily_batch(req: DailyBatchRequest):
    """
    Le client ne fournit plus les matchs ni leurs cotes : le moteur recupere
    lui-meme les matchs La Liga du jour demande (ou aujourd'hui par defaut,
    en heure d'Abidjan) et leurs cotes. Le client garde la main sur les
    fourchettes de combines demandees (combo_definitions), la date a traiter
    (batch_date) et s'il veut enregistrer le resultat ou juste simuler (save).
    """
    league = (req.league or DEFAULT_LEAGUE).lower()
    if league not in SUPPORTED_LEAGUES:
        return _unsupported_league_response(league)

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
