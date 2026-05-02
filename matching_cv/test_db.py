import json
from matching_cv.match_cv import load_db_env, get_db_conn, fetch_all_skills

load_db_env()

conn = get_db_conn()
skills = fetch_all_skills(conn)

with open("skills_dump.json", "w", encoding="utf-8") as f:
    json.dump(skills, f, ensure_ascii=False, indent=2)

conn.close()