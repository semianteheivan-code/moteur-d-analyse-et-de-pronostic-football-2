from db.database import get_connection

FORM_WINDOW = 5  # nombre de derniers matchs pris en compte pour la forme recente


def _team_recent_matches(conn, team, league, before_date, limit=FORM_WINDOW):
    """Derniers matchs joues par team (domicile ou exterieur) dans ce championnat, strictement avant before_date."""
    return conn.execute(
        """
        SELECT date, home_team, away_team, home_goals, away_goals
        FROM matches
        WHERE (home_team = ? OR away_team = ?) AND league = ? AND date < ? AND home_goals IS NOT NULL
        ORDER BY date DESC
        LIMIT ?
        """,
        (team, team, league, before_date, limit),
    ).fetchall()


def _goals_for_against(rows, team):
    """A partir de matchs bruts, extrait (buts marques, buts encaisses) du point de vue de team."""
    scored, conceded = [], []
    for r in rows:
        if r["home_team"] == team:
            scored.append(r["home_goals"])
            conceded.append(r["away_goals"])
        else:
            scored.append(r["away_goals"])
            conceded.append(r["home_goals"])
    return scored, conceded


def _avg(values):
    return sum(values) / len(values) if values else None


def _team_recent_xg(conn, team, league, before_date, limit=FORM_WINDOW):
    rows = conn.execute(
        """
        SELECT date, home_team, away_team, home_xg, away_xg
        FROM match_xg
        WHERE (home_team = ? OR away_team = ?) AND league = ? AND date < ?
        ORDER BY date DESC
        LIMIT ?
        """,
        (team, team, league, before_date, limit),
    ).fetchall()
    scored, conceded = [], []
    for r in rows:
        if r["home_team"] == team:
            scored.append(r["home_xg"])
            conceded.append(r["away_xg"])
        else:
            scored.append(r["away_xg"])
            conceded.append(r["home_xg"])
    return _avg(scored), _avg(conceded)


def _head_to_head(conn, home_team, away_team, league, before_date, limit=5):
    rows = conn.execute(
        """
        SELECT home_team, away_team, home_goals, away_goals
        FROM matches
        WHERE ((home_team = ? AND away_team = ?) OR (home_team = ? AND away_team = ?))
        AND league = ? AND date < ? AND home_goals IS NOT NULL
        ORDER BY date DESC
        LIMIT ?
        """,
        (home_team, away_team, away_team, home_team, league, before_date, limit),
    ).fetchall()
    home_wins = draws = away_wins = 0
    for r in rows:
        if r["home_goals"] == r["away_goals"]:
            draws += 1
        elif (r["home_team"] == home_team) == (r["home_goals"] > r["away_goals"]):
            home_wins += 1
        else:
            away_wins += 1
    return {
        "h2h_matches": len(rows),
        "h2h_home_wins": home_wins,
        "h2h_draws": draws,
        "h2h_away_wins": away_wins,
    }


def compute_match_features(home_team: str, away_team: str, match_date: str, league: str) -> dict:
    """
    Calcule les features pre-match pour un match donne, dans un championnat
    donne (league ajoute le 13/10/2026 - sans ce filtre, la forme recente ou
    le head-to-head pourraient melanger des matchs de deux championnats
    differents). N'utilise que des donnees strictement anterieures a
    match_date, pour eviter toute fuite.
    """
    conn = get_connection()

    home_recent = _team_recent_matches(conn, home_team, league, match_date)
    away_recent = _team_recent_matches(conn, away_team, league, match_date)

    home_scored, home_conceded = _goals_for_against(home_recent, home_team)
    away_scored, away_conceded = _goals_for_against(away_recent, away_team)

    home_xg_for, home_xg_against = _team_recent_xg(conn, home_team, league, match_date)
    away_xg_for, away_xg_against = _team_recent_xg(conn, away_team, league, match_date)

    h2h = _head_to_head(conn, home_team, away_team, league, match_date)

    return {
        "home_form_goals_scored": _avg(home_scored),
        "home_form_goals_conceded": _avg(home_conceded),
        "away_form_goals_scored": _avg(away_scored),
        "away_form_goals_conceded": _avg(away_conceded),
        "home_form_matches": len(home_recent),
        "away_form_matches": len(away_recent),
        "home_xg_for": home_xg_for,
        "home_xg_against": home_xg_against,
        "away_xg_for": away_xg_for,
        "away_xg_against": away_xg_against,
        **h2h,
    }
