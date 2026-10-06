from db.database import get_connection
conn = get_connection()
cols = [r[1] for r in conn.execute("PRAGMA table_info(matches)")]
print("Colonnes de la table matches :")
for c in cols:
    print(" -", c)
