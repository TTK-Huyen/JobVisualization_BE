import psycopg2

conn = psycopg2.connect('postgresql://postgres:123456@localhost:5432/job_vis_clone')
cur = conn.cursor()
cur.execute("SELECT type, COUNT(*) FROM skills GROUP BY type ORDER BY type")
rows = cur.fetchall()
for t, c in rows:
    print(f"{t}: {c}")
cur.execute('SELECT COUNT(*) FROM benefits')
print('benefits:', cur.fetchone()[0])
conn.close()
