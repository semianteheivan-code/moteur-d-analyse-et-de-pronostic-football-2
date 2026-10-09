from db.database import get_connection

conn = get_connection()
rows = conn.execute(
    "SELECT DISTINCT home_team FROM matches "
    "UNION SELECT DISTINCT away_team FROM matches"
).fetchall()
noms_base = sorted(r[0] for r in rows)

a_verifier = ["Malaga", "Espanyol", "Rayo Vallecano", "Athletic Club", "CD Alaves",
              "Atletico Madrid", "Barcelona", "Getafe", "Real Madrid", "Villarreal",
              "Elche", "Celta Vigo", "Real Sociedad", "Deportivo A Coruna",
              "Real Betis", "Osasuna", "Racing Santander", "Valencia", "Levante", "Sevilla"]

for nom_api in a_verifier:
    proches = [n for n in noms_base if n.split()[0].lower() in nom_api.lower() or nom_api.split()[0].lower() in n.lower()]
    print(f"API: {nom_api!r:25} -> candidats dans la base: {proches}")