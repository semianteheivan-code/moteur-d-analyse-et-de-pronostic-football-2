from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional, List, Dict, Union
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from engine import analyze_match, resolve_team_names
from daily_batch import run_daily_batch, kickoff_has_passed
from db.database import get_connection
from config import (
    DEFAULT_TRAIN_SEASON, DEFAULT_FIXTURES_DAYS, REFERENCE_TIMEZONE,
    SUPPORTED_LEAGUES, DEFAULT_LEAGUE, LEAGUES,
)
from sources.five_dollar_football import (
    get_la_liga_fixtures_cached,
    get_fixture_odds_cached,
    find_fixtures,
    find_fixture_by_id,
    QuotaExceededError,
)

app = FastAPI(title="Moteur de pronostic football - API locale")


# --- Resolution du championnat demande (etape A16) --------------------------
def _normalize_league_key(text: str) -> str:
    return " ".join(text.strip().lower().split())


_LEAGUE_ALIAS_TO_KEY = {}
for _entry in LEAGUES:
    _LEAGUE_ALIAS_TO_KEY[_normalize_league_key(_entry["key"])] = _entry["key"]
    _LEAGUE_ALIAS_TO_KEY[_normalize_league_key(_entry["name"])] = _entry["key"]
    for _alias in _entry["aliases"]:
        _LEAGUE_ALIAS_TO_KEY[_normalize_league_key(_alias)] = _entry["key"]


def resolve_league_key(user_input: Optional[str]) -> Optional[str]:
    """
    Resout un league fourni par le client (nom officiel, cle interne, ou
    n'importe quel surnom declare dans LEAGUES) vers la cle interne
    canonique, sans tenir compte des majuscules ni des espaces en trop
    (A16). Renvoie DEFAULT_LEAGUE si rien n'est fourni, None si la valeur
    fournie ne correspond a rien de connu.
    """
    if user_input is None:
        return DEFAULT_LEAGUE
    return _LEAGUE_ALIAS_TO_KEY.get(_normalize_league_key(user_input))


# --- Championnats dont les matchs/cotes en direct fonctionnent reellement
# (etape multi-championnats, 13/10/2026) -------------------------------------
# LEAGUES/SUPPORTED_LEAGUES disent quels championnats le moteur CALCULE
# (historique + forces d'equipe) - c'est deja vrai pour La Liga et Premier
# League. Mais sources/five_dollar_football.py reste code en dur sur La
# Liga (generalisation deliberement reportee a la fin du chantier) : sans
# ce garde-fou, /fixtures, /analyze et /daily-batch demandes avec
# league="premier_league" recevraient silencieusement les matchs de LA
# LIGA, reetiquetes avec le nom du championnat demande - bug reellement
# trouve par test_api.py le 13/10/2026, pas juste theorique.
LIVE_FIXTURES_SUPPORTED_LEAGUES = {"la_liga"}


def _live_fixtures_unavailable_response(league_key: str) -> dict:
    return {
        "status": "league_not_available",
        "league": SUPPORTED_LEAGUES[league_key],
        "reason": (
            "championnat couvert par le moteur (historique et calcul), mais les matchs "
            "en direct et les cotes ne sont pas encore disponibles pour ce championnat"
        ),
        "available": [SUPPORTED_LEAGUES[k] for k in LIVE_FIXTURES_SUPPORTED_LEAGUES],
    }


# --- Modeles de reponse (etape 5b, A6+A8) -----------------------------------
class HealthResponse(BaseModel):
    status: str
    last_match_date_in_db: Optional[str] = None


class LeagueEntry(BaseModel):
    name: str
    country: str
    aliases: List[str]


class LeaguesResponse(BaseModel):
    default_league: str
    leagues: List[LeagueEntry]


class FixtureItem(BaseModel):
    fixture_id: Union[str, int]  # etape A17
    home_team: str
    away_team: str
    league: str  # etape A14 : championnat de ce match precis
    kickoff_utc: str
    started: bool  # etape A10
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
    available: List[str]  # etape A16


class QuotaExceededResponse(BaseModel):
    status: str
    reason: str


class MarketEntry(BaseModel):
    probability: Optional[float] = None
    market_odds: Optional[float] = None
    market_implied_probability: Optional[float] = None
    edge: Optional[float] = None
    value_bet: Optional[bool] = None
    suspicious: Optional[bool] = None
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
    started: bool  # etape A10
    fixture_id: Union[str, int]  # etape A17
    league: str  # etape A14


class MatchNotAvailableResponse(BaseModel):
    status: str
    home_team: str
    away_team: str
    reason: str


class UnknownTeamResponse(BaseModel):
    status: str
    home_team: str
    away_team: str
    unknown: List[str]  # etape A11
    reason: str
    started: bool  # etape A10


class InsufficientHistoryResponse(BaseModel):
    status: str
    home_team: str
    away_team: str
    train_season: str
    reason: str
    started: bool  # etape A10
    fixture_id: Union[str, int]  # etape A17
    league: str  # etape A14


class RefusedResponse(BaseModel):
    status: str
    home_team: str
    away_team: str
    reason: str
    confidence: float
    started: bool  # etape A10
    fixture_id: Union[str, int]  # etape A17
    league: str  # etape A14


class AmbiguousMatchCandidate(BaseModel):
    fixture_id: Union[str, int]
    league: str
    kickoff_utc: str


class AmbiguousMatchResponse(BaseModel):
    status: str
    home_team: str
    away_team: str
    reason: str
    candidates: List[AmbiguousMatchCandidate]


class SelectionEntry(BaseModel):
    # etape A14 : fixture_id/league presents seulement si l'appelant de
    # run_daily_batch les a fournis dans "fixtures" (toujours le cas via
    # /daily-batch depuis cette etape) - absents (null) sinon, par exemple
    # pour un appel direct de combo_builder sans ces champs.
    home_team: str
    away_team: str
    market: str
    probability: float
    odds: float
    fixture_id: Optional[Union[str, int]] = None
    league: Optional[str] = None


class ComboResult(BaseModel):
    status: str
    selections: Optional[List[SelectionEntry]] = None
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
        "reason": "championnat non couvert par le moteur",
        "available": [entry["name"] for entry in LEAGUES],
    }


def _quota_exceeded_response(exc: QuotaExceededError) -> dict:
    return {
        "status": "quota_exceeded",
        "reason": str(exc),
    }


class MatchRequest(BaseModel):
    home_team: Optional[str] = None  # etape A17 : facultatif si fixture_id est fourni
    away_team: Optional[str] = None
    fixture_id: Optional[Union[str, int]] = None  # etape A17 : prioritaire sur les noms
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


@app.get("/leagues", responses={200: {"model": LeaguesResponse}})
def leagues():
    """
    Adresse en lecture seule (etape A13) : dit au client quels championnats
    le moteur couvre (historique + calcul), lequel est utilise par defaut,
    et sous quels noms on peut les demander (aliases). Ne dit rien sur la
    disponibilite des matchs en direct - voir LIVE_FIXTURES_SUPPORTED_LEAGUES.
    """
    return {
        "default_league": SUPPORTED_LEAGUES[DEFAULT_LEAGUE],
        "leagues": [
            {"name": entry["name"], "country": entry["country"], "aliases": entry["aliases"]}
            for entry in LEAGUES
        ],
    }


@app.get(
    "/fixtures",
    responses={200: {"model": Union[FixturesOkResponse, LeagueNotAvailableResponse, QuotaExceededResponse]}},
)
def fixtures(days: Optional[int] = None, league: Optional[str] = None):
    league_key = resolve_league_key(league)
    if league_key is None:
        return _unsupported_league_response(league or "")
    if league_key not in LIVE_FIXTURES_SUPPORTED_LEAGUES:
        return _live_fixtures_unavailable_response(league_key)

    days = min(days or DEFAULT_FIXTURES_DAYS, 14)
    today = datetime.now(ZoneInfo(REFERENCE_TIMEZONE)).replace(hour=0, minute=0, second=0, microsecond=0)
    now_utc = datetime.now(timezone.utc)
    try:
        raw_fixtures = get_la_liga_fixtures_cached(today, days)
        result = [
            {
                "fixture_id": fx["id"],  # etape A17
                "home_team": fx["teams"]["home"]["name"],
                "away_team": fx["teams"]["away"]["name"],
                "league": SUPPORTED_LEAGUES[league_key],  # etape A14
                "kickoff_utc": fx["kickoff_utc"],
                "started": kickoff_has_passed(fx["kickoff_utc"], 0, now_utc),  # etape A10
                "odds": get_fixture_odds_cached(fx["id"]),
            }
            for fx in raw_fixtures
        ]
    except QuotaExceededError as e:
        return _quota_exceeded_response(e)
    return {
        "league": SUPPORTED_LEAGUES[league_key],
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
                AmbiguousMatchResponse,
                QuotaExceededResponse,
            ]
        }
    },
)
def analyze(req: MatchRequest):
    """
    Deux facons de designer le match : fixture_id (prioritaire, ignore
    home_team/away_team s'il est fourni), ou home_team/away_team (home_team
    doit etre l'equipe qui recoit). league accepte le nom officiel, la cle
    interne, ou n'importe quel surnom declare par GET /leagues (etape A16).

    Ordre : championnat, puis (si pas de fixture_id) noms d'equipes
    (unknown_team - A11), puis recherche du match par noms - aucun resultat :
    match_not_available ; plusieurs resultats : ambiguous_match (A17) ; un
    seul resultat, ou fixture_id fourni directement : historique
    (insufficient_history, dans engine.analyze_match).

    Statuts possibles : ok, match_not_available, league_not_available,
    unknown_team, insufficient_history, refused, ambiguous_match,
    quota_exceeded. Tous les statuts lies a un match identifie (ok,
    insufficient_history, refused) incluent "started" (A10), "fixture_id"
    (A17) et "league" (A14).
    """
    league_key = resolve_league_key(req.league)
    if league_key is None:
        return _unsupported_league_response(req.league or "")
    if league_key not in LIVE_FIXTURES_SUPPORTED_LEAGUES:
        return _live_fixtures_unavailable_response(league_key)

    if req.fixture_id is not None:
        try:
            fx = find_fixture_by_id(req.fixture_id)
        except QuotaExceededError as e:
            # 14/10/2026 : seul appel oublie dans ce garde-fou - trouve en
            # conditions reelles (la protection de quota a declenche un 500
            # brut au lieu d'une reponse propre pendant test_api.py).
            return _quota_exceeded_response(e)
        if fx is None:
            return {
                "status": "match_not_available",
                "home_team": req.home_team or "",
                "away_team": req.away_team or "",
                "reason": f"aucun match trouve avec fixture_id={req.fixture_id!r}",
            }
        home_team = fx["teams"]["home"]["name"]
        away_team = fx["teams"]["away"]["name"]
    else:
        if not req.home_team or not req.away_team:
            return {
                "status": "match_not_available",
                "home_team": req.home_team or "",
                "away_team": req.away_team or "",
                "reason": "fournissez soit fixture_id, soit home_team et away_team",
            }

        home, away, unknown = resolve_team_names(req.home_team, req.away_team, league_key)
        if unknown:
            return {
                "status": "unknown_team",
                "home_team": home,
                "away_team": away,
                "unknown": unknown,
                "reason": f"equipe(s) non reconnue(s) : {', '.join(unknown)}",
                "started": False,
            }

        try:
            candidates = find_fixtures(req.home_team, req.away_team, DEFAULT_FIXTURES_DAYS)
        except QuotaExceededError as e:
            return _quota_exceeded_response(e)

        if not candidates:
            return {
                "status": "match_not_available",
                "home_team": home,
                "away_team": away,
                "reason": (
                    f"aucun match trouve entre ces deux equipes dans les "
                    f"{DEFAULT_FIXTURES_DAYS} prochains jours couverts (La Liga) - "
                    f"verifiez que home_team est bien l'equipe qui recoit"
                ),
            }
        if len(candidates) > 1:
            return {
                "status": "ambiguous_match",
                "home_team": home,
                "away_team": away,
                "reason": "plusieurs matchs correspondent, preciser league ou fixture_id",
                "candidates": [
                    {
                        "fixture_id": c["id"],
                        "league": SUPPORTED_LEAGUES[league_key],
                        "kickoff_utc": c["kickoff_utc"],
                    }
                    for c in candidates
                ],
            }
        fx = candidates[0]
        home_team = req.home_team
        away_team = req.away_team

    train_season = req.train_season or DEFAULT_TRAIN_SEASON
    match_date = fx["kickoff_utc"][:10]
    started = kickoff_has_passed(fx["kickoff_utc"])  # etape A10
    try:
        odds = get_fixture_odds_cached(fx["id"])
    except QuotaExceededError as e:
        return _quota_exceeded_response(e)
    result = analyze_match(home_team, away_team, match_date, train_season, league_key, odds=odds)
    result["started"] = started
    result["fixture_id"] = fx["id"]  # etape A17
    result["league"] = SUPPORTED_LEAGUES[league_key]  # etape A14
    return result


class ComboDefinitionInput(BaseModel):
    name: str
    min_odds: float
    max_odds: float


class DailyBatchRequest(BaseModel):
    train_season: Optional[str] = None
    combo_definitions: List[ComboDefinitionInput]
    batch_date: Optional[str] = None
    save: bool = True
    league: Optional[str] = None
    min_minutes_before_kickoff: float = 0


@app.post(
    "/daily-batch",
    responses={
        200: {
            "model": Union[
                DailyBatchOkResponse,
                NoMatchesAvailableResponse,
                LeagueNotAvailableResponse,
                QuotaExceededResponse,
            ]
        }
    },
)
def daily_batch(req: DailyBatchRequest):
    """
    Le client ne fournit plus les matchs ni leurs cotes : le moteur recupere
    lui-meme les matchs du championnat demande pour le jour voulu (ou
    aujourd'hui par defaut, en heure d'Abidjan) et leurs cotes. league
    accepte nom officiel, cle interne ou surnom (A16). Chaque match transmis
    au moteur porte son fixture_id et son league (A14), qui se retrouvent
    ensuite dans "details" et dans les selections de chaque combine.
    """
    league_key = resolve_league_key(req.league)
    if league_key is None:
        return _unsupported_league_response(req.league or "")
    if league_key not in LIVE_FIXTURES_SUPPORTED_LEAGUES:
        return _live_fixtures_unavailable_response(league_key)

    if req.batch_date:
        day = datetime.strptime(req.batch_date, "%Y-%m-%d")
    else:
        day = datetime.now(ZoneInfo(REFERENCE_TIMEZONE)).replace(hour=0, minute=0, second=0, microsecond=0)
    batch_date = day.date().isoformat()

    try:
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
                "kickoff_utc": fx["kickoff_utc"],
                "fixture_id": fx["id"],  # etape A14
                "league": SUPPORTED_LEAGUES[league_key],  # etape A14
                "odds": get_fixture_odds_cached(fx["id"]),
            }
            for fx in raw_fixtures
        ]
    except QuotaExceededError as e:
        return _quota_exceeded_response(e)
    combo_definitions = [c.model_dump() for c in req.combo_definitions]
    train_season = req.train_season or DEFAULT_TRAIN_SEASON
    return run_daily_batch(fixtures, train_season, combo_definitions, batch_date,
                            save=req.save, min_minutes_before_kickoff=req.min_minutes_before_kickoff,
                            league_key=league_key)
