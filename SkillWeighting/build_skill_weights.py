#!/usr/bin/env python3
"""Build skill weights per job search_group and upsert into PostgreSQL.

Usage examples:
  python SkillWeighting/build_skill_weights.py
  python SkillWeighting/build_skill_weights.py --limit 5
  python SkillWeighting/build_skill_weights.py --search-group "backend developer"
  python SkillWeighting/build_skill_weights.py --dry-run
  python SkillWeighting/build_skill_weights.py --replace
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from dotenv import load_dotenv
except Exception:
    def load_dotenv(path=None):
        return False

try:
    import psycopg2
    from psycopg2.extras import execute_values
except Exception:
    psycopg2 = None

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from Db.llm.debug_llm_adapter import call_llm as db_call_llm
from Db.llm.llm_config import LLM_CALL_TIMEOUT_SECONDS



def find_db_env() -> Optional[Path]:
    p = Path(__file__).resolve()
    # walk up until root
    for parent in [p] + list(p.parents):
        candidate = Path(parent) / "Db" / ".env"
        if candidate.exists():
            return candidate
    return None


def load_db_env():
    env_path = find_db_env()
    if not env_path:
        print("Could not find Db/.env by walking parents.")
        return False
    load_dotenv(env_path)
    print(f"Loaded env from: {env_path}")
    return True


def get_db_conn():
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is required. Install psycopg2-binary.")
    host = os.getenv("PG_HOST")
    port = os.getenv("PG_PORT")
    db = os.getenv("PG_DB")
    user = os.getenv("PG_USER")
    password = os.getenv("PG_PASSWORD")
    if not all([host, port, db, user, password]):
        raise RuntimeError("PG_HOST/PG_PORT/PG_DB/PG_USER/PG_PASSWORD must be set in Db/.env")
    conn = psycopg2.connect(host=host, port=port, dbname=db, user=user, password=password)
    return conn


def fetch_search_groups(conn, limit: Optional[int] = None, specific: Optional[str] = None) -> List[str]:
    cur = conn.cursor()
    params: Tuple = ()
    sql = "SELECT DISTINCT search_group FROM public.jobs WHERE search_group IS NOT NULL"
    if specific:
        sql += " AND search_group = %s"
        params = (specific,)
    sql += " ORDER BY search_group"
    if limit:
        sql += " LIMIT %s"
        params = params + (limit,)
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    return [r[0] for r in rows]


def fetch_skills_for_group(conn, search_group: str):
    cur = conn.cursor()
    sql = (
        "SELECT s.skill_id, s.skill_name, s.type, COUNT(DISTINCT j.job_id) AS job_count "
        "FROM public.jobs j "
        "JOIN public.job_skills js ON j.job_id = js.job_id "
        "JOIN public.skills s ON js.skill_id = s.skill_id "
        "WHERE j.search_group = %s "
        "GROUP BY s.skill_id, s.skill_name, s.type "
        "ORDER BY job_count DESC, s.skill_name"
    )
    cur.execute(sql, (search_group,))
    rows = cur.fetchall()
    cur.close()
    return [(int(r[0]), r[1], r[2], int(r[3])) for r in rows]

# def call_llm(search_group: str, skills: List[str], prompt_template: Optional[str] = None):
#     # Try using OpenAI if available, otherwise fallback to uniform weights
#     skills_list_text = "\n".join(f"- {s}" for s in skills)
#     if prompt_template:
#         prompt = prompt_template.replace("{{skills}}", skills_list_text).replace("{{search_group}}", search_group)
#     else:
#         prompt = (
#             "Given the following skills, assign a weight to each skill representing its importance "
#             "for the search group. Return a JSON array of objects {\"skill\":..., \"weight\":...} "
#             "whose weights sum to 1. Skills:\n" + skills_list_text
#         )

#     try:
#         import openai
#         api_key = os.getenv("OPENAI_API_KEY")
#         if api_key:
#             openai.api_key = api_key
#             resp = openai.ChatCompletion.create(
#                 model=os.getenv("OPENAI_MODEL", "gpt-3.5-turbo"),
#                 messages=[{"role": "user", "content": prompt}],
#                 temperature=0.0,
#                 max_tokens=500,
#             )
#             text = resp["choices"][0]["message"]["content"]
#             # try extract json
#             m = re.search(r"\{.*\}|\[.*\]", text, re.S)
#             if m:
#                 text = m.group(0)
#             data = json.loads(text)
#             result: Dict[str, float] = {}
#             if isinstance(data, list):
#                 for item in data:
#                     if isinstance(item, dict) and "skill" in item and "weight" in item:
#                         result[item["skill"]] = float(item["weight"])
#             return result
#     except Exception:
#         pass

#     # fallback: equal weights
#     if not skills:
#         return {}
#     w = 1.0 / len(skills)
#     return {s: w for s in skills}

def load_gemini_keys() -> List[str]:
    keys = []
    for name, value in os.environ.items():
        m = re.fullmatch(r"GEMINI_API_KEY_(\d+)", name)
        if m and value:
            keys.append((int(m.group(1)), value))
    keys.sort()
    return [v for _, v in keys]


# def call_llm(search_group: str, skills: List[str], prompt_template: Optional[str] = None):
#     import google.generativeai as genai

#     skills_list_text = "\n".join(f"- {s}" for s in skills)

#     if prompt_template:
#         prompt = (
#             prompt_template
#             .replace("{{skills}}", skills_list_text)
#             .replace("{{search_group}}", search_group)
#         )
#     else:
#         prompt = f"""
# Return only valid JSON. Assign weights to skills for search group: {search_group}.
# Weights must sum to 1.

# Skills:
# {skills_list_text}
# """

#     api_keys = load_gemini_keys()
#     if not api_keys:
#         raise RuntimeError("No GEMINI_API_KEY_1, GEMINI_API_KEY_2... found in Db/.env")

#     last_error = None

#     for api_key in api_keys:
#         try:
#             genai.configure(api_key=api_key)

#             model = genai.GenerativeModel(
#                 os.getenv("GEMINI_WEIGHT_MODEL", "gemini-2.5-flash")
#             )

#             resp = model.generate_content(
#                 prompt,
#                 generation_config={
#                     "temperature": 0.0,
#                     "max_output_tokens": 2048,
#                     "response_mime_type": "application/json",
#                 },
#                 request_options={
#                     "timeout": int(os.getenv("WEIGHT_LLM_TIMEOUT_SECONDS", "60"))
#                 },
#             )

#             text = resp.text.strip()

#             m = re.search(r"\[.*\]", text, re.S)
#             if m:
#                 text = m.group(0)

#             data = json.loads(text)

#             result: Dict[str, float] = {}
#             if isinstance(data, list):
#                 for item in data:
#                     if isinstance(item, dict) and "skill" in item and "weight" in item:
#                         result[str(item["skill"])] = float(item["weight"])

#             if result:
#                 return result

#             raise RuntimeError("Gemini returned empty or invalid weight JSON")

#         except Exception as e:
#             last_error = e
#             err = str(e).lower()

#             if "429" in err or "quota" in err or "resourceexhausted" in err:
#                 print("Gemini key quota exceeded, trying next key...")
#                 continue

#             print(f"Gemini call failed: {e}")
#             continue

#     raise RuntimeError(f"All Gemini keys failed. Last error: {last_error}")


def call_llm(search_group: str, skills: List[str], prompt_template: Optional[str] = None):
    skills_list_text = "\n".join(f"- {s}" for s in skills)

    if prompt_template:
        prompt = (
            prompt_template
            .replace("{{skills}}", skills_list_text)
            .replace("{{search_group}}", search_group)
        )
    else:
        prompt = f"""
Return only valid JSON array.
Assign weights to skills for search group: {search_group}.
Each item must have: skill, weight.
Weights must sum to 1.

Skills:
{skills_list_text}
"""

    api_keys = load_gemini_keys()
    if not api_keys:
        raise RuntimeError("No GEMINI_API_KEY_1, GEMINI_API_KEY_2... found in Db/.env")

    last_error = None

    for idx, api_key in enumerate(api_keys, start=1):
        try:
            print(f"[LLM] Trying key {idx}/{len(api_keys)}")

            text = db_call_llm(
                prompt=prompt,
                api_key=api_key,
                timeout_seconds=int(os.getenv("WEIGHT_LLM_TIMEOUT_SECONDS", "90")),
            )
            
            text = text.strip()
            m = re.search(r"\[.*\]", text, re.S)
            if m:
                text = m.group(0)

            data = json.loads(text)

            result: Dict[str, float] = {}
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and "skill" in item and "weight" in item:
                        result[str(item["skill"])] = float(item["weight"])

            if result:
                return result

            raise RuntimeError("LLM returned empty or invalid weight JSON")

        except Exception as e:
            last_error = e
            err = str(e).lower()

            is_last_key = idx == len(api_keys)

            if "429" in err or "quota" in err or "resourceexhausted" in err:
                print("Gemini key quota exceeded.")
            elif "503" in err or "504" in err or "timeout" in err:
                print(f"LLM temporary error: {e}")
            else:
                print(f"LLM call failed: {e}")

            if not is_last_key:
                print("Waiting 15s before retrying next key...")
                time.sleep(15)

            continue

    raise RuntimeError(f"All Gemini keys failed. Last error: {last_error}")

def validate_and_normalize(weights: Dict[str, float]) -> Dict[str, float]:
    total = sum(weights.values())
    if total <= 0:
        return {k: 0.0 for k in weights}
    if abs(total - 1.0) > 1e-6:
        # normalize
        return {k: float(v) / total for k, v in weights.items()}
    return {k: float(v) for k, v in weights.items()}


def upsert_weights(conn, search_group: str, skill_map: Dict[int, float], dry_run: bool = False, replace: bool = False):
    rows = [(search_group, skill_id, weight) for skill_id, weight in skill_map.items()]
    if dry_run:
        print(f"DRY RUN: would upsert {len(rows)} rows for '{search_group}'")
        return
    cur = conn.cursor()
    if replace:
        cur.execute("DELETE FROM public.job_group_skill_weights WHERE search_group = %s", (search_group,))
    sql = (
        "INSERT INTO public.job_group_skill_weights (search_group, skill_id, weight_wi) "
        "VALUES %s "
        "ON CONFLICT (search_group, skill_id) DO UPDATE SET weight_wi = EXCLUDED.weight_wi"
    )
    execute_values(cur, sql, rows)
    conn.commit()
    cur.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--search-group", type=str, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()

    if not load_db_env():
        sys.exit(1)

    prompt_path = Path(__file__).resolve().parent / "prompts" / "skill_weight_prompt.md"
    prompt_template = None
    if prompt_path.exists():
        prompt_template = prompt_path.read_text(encoding="utf8")

    conn = get_db_conn()
    try:
        groups = fetch_search_groups(conn, limit=args.limit, specific=args.search_group)
        print(f"Found {len(groups)} search_group(s)")
        out_dir = Path(__file__).resolve().parent / "outputs"
        out_dir.mkdir(parents=True, exist_ok=True)
        for i, g in enumerate(groups):
            print(f"Processing ({i+1}/{len(groups)}): {g}")
            skills = fetch_skills_for_group(conn, g)

            MIN_JOB_COUNT_FOR_LLM = int(os.getenv("MIN_JOB_COUNT_FOR_LLM", "5"))
            top_skills = [s for s in skills if s[3] >= MIN_JOB_COUNT_FOR_LLM]

            if not top_skills:
                print("[WARN] No skills meet threshold >=10, fallback to top 30 by frequency")
                top_skills = skills[:30]

            MAX_LLM_SKILLS = int(os.getenv("MAX_LLM_SKILLS", "120"))

            if len(top_skills) > MAX_LLM_SKILLS:
                print(f"[WARN] Too many skills ({len(top_skills)}), trimming to {MAX_LLM_SKILLS}")
                top_skills = top_skills[:MAX_LLM_SKILLS]

            skill_names = [name for sid, name, skill_type, count in top_skills]
            print(f"\n[LLM INPUT] Total skills sent to LLM: {len(skill_names)}")
            for sid, name, skill_type, count in top_skills:
                print(f" - {name} | job_count={count}")
                
            if not skills:
                print(f"No skills found for group '{g}', skipping.")
                continue
            llm_weights = call_llm(g, skill_names, prompt_template=prompt_template)
            print(f"\n[LLM OUTPUT] Total skills returned: {len(llm_weights)}")
            for skill, weight in sorted(llm_weights.items(), key=lambda x: x[1], reverse=True):
                print(f" - {skill}: {weight:.6f}")
            llm_by_name = {
                re.sub(r"\W+", "", k.lower()): v
                for k, v in llm_weights.items()
            }

            missing = []

            for sid, name, skill_type, count in top_skills:
                norm = re.sub(r"\W+", "", name.lower())
                if norm not in llm_by_name:
                    missing.append(name)

            if missing:
                print(f"[WARN] {len(missing)} skills not returned by LLM")
                for m in missing[:10]:
                    print(" -", m)
            max_count = max(count for sid, name, skill_type, count in skills)

            llm_by_name = {
                re.sub(r"\W+", "", k.lower()): v
                for k, v in llm_weights.items()
            }

            final_score = {}

            TYPE_WEIGHT = {
                "specialized skill": 1.0,
                "certification": 0.7,
                "common skill": 0.3,
            }

            for sid, name, skill_type, count in skills:
                type_weight = TYPE_WEIGHT.get(str(skill_type).lower(), 0.5)
                frequency_score = count / max_count
                norm_name = re.sub(r"\W+", "", name.lower())

                if count >= MIN_JOB_COUNT_FOR_LLM:
                    llm_score = llm_by_name.get(norm_name, 0.0)
                    base_score = 0.6 * frequency_score + 0.4 * llm_score
                else:
                    base_score = 0.6 * frequency_score

                type_weight = TYPE_WEIGHT.get(str(skill_type).lower(), 0.5)
                final_score[sid] = base_score * type_weight

            mapped = validate_and_normalize(final_score)
            print(f"\n[CHECK] Total final weight = {sum(mapped.values()):.6f}")
            # write output file
            out_file = out_dir / (re.sub(r"[^a-zA-Z0-9_-]", "_", g) + ".json")
            skill_info_by_id = {
                sid: {"name": name, "type": skill_type, "job_count": count}
                for sid, name, skill_type, count in skills
            }
            print("[FINAL WEIGHTS - TOP 20]")
            for sid, weight in sorted(mapped.items(), key=lambda x: x[1], reverse=True)[:20]:
                print(f" - {skill_info_by_id.get(sid, {}).get('name')}: {weight:.6f}")
            meta = {
                "search_group": g,
                "weights": [
                    {
                        "skill_id": sid,
                        "skill_name": skill_info_by_id[sid]["name"],
                        "skill_type": skill_info_by_id[sid]["type"],
                        "job_count": skill_info_by_id[sid]["job_count"],
                        "weight": w,
                    }
                    for sid, w in mapped.items()
                ],
            }
            out_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf8")
            print(f"Wrote output to {out_file}")

            # upsert
            upsert_weights(conn, g, mapped, dry_run=args.dry_run, replace=args.replace)

            # wait 15s between LLM requests
            if i < len(groups) - 1:
                print("Sleeping 15s before next request...")
                time.sleep(15)
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
