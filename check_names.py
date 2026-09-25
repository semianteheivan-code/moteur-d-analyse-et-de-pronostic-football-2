from db.database import get_connection

conn = get_connection()
fd_teams = {r[0] for r in conn.execute("SELECT DISTINCT home_team FROM matches")}
us_teams = {r[0] for r in conn.execute("SELECT DISTINCT home_team FROM match_xg")}

print("Équipes football-data.co.uk :", sorted(fd_teams))
print()
print("Équipes Understat :", sorted(us_teams))
print()
print("Présentes uniquement chez football-data :", sorted(fd_teams - us_teams))
print("Présentes uniquement chez Understat :", sorted(us_teams - fd_teams))