# SkillWeighting

Small standalone module to compute skill weights per job `search_group` and upsert into PostgreSQL.

Requirements
- Python 3.8+
- Install dependencies: `pip install psycopg2-binary python-dotenv openai` (openai optional)

Usage
From repository root run examples:
```
python SkillWeighting/build_skill_weights.py
python SkillWeighting/build_skill_weights.py --limit 5
python SkillWeighting/build_skill_weights.py --search-group "backend developer"
python SkillWeighting/build_skill_weights.py --dry-run
python SkillWeighting/build_skill_weights.py --replace
```

Details
- The script locates `Db/.env` by walking parent directories from the script file and loads `PG_HOST`, `PG_PORT`, `PG_DB`, `PG_USER`, `PG_PASSWORD`.
- It queries `public.jobs` to get distinct `search_group` and joins `job_skills` and `skills` to collect skills.
- Skills are sent to an LLM (OpenAI if `OPENAI_API_KEY` set) using the prompt in `prompts/skill_weight_prompt.md`. If no API key, weights default to uniform distribution.
- Requests are spaced by 15 seconds to respect rate limits.
- Results are written to `SkillWeighting/outputs/<search_group>.json` and upserted to `public.job_group_skill_weights` (requires that table to exist). Use `--dry-run` to skip DB writes.
