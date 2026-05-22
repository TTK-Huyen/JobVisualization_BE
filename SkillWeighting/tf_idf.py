"""
TF-IDF calculation and database upserting for the Skill Weighting problem in the JobVisualization Project.

Formula:
  TF(s, t) = 1 + ln(n(s, t))    where n(s, t) is the number of jobs of search group t requiring skill s.
  IDF(s) = ln(|T| / m)          where |T| is total search groups, and m is search groups requiring skill s.
  TF-IDF(s, t) = TF(s, t) * IDF(s)
"""

import math
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# Dynamically locate project root and insert into sys.path to ensure module resolution
def find_project_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".env").exists() or (parent / "requirements.txt").exists():
            return parent
    return current.parents[1]

PROJECT_ROOT = find_project_root()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Import database connection dynamically to avoid python keyword and path format constraints
import importlib.util

def load_db_connection_func():
    module_dir = PROJECT_ROOT / "Db" / "pipeline" / "import" / "3_import"
    module_path = module_dir / "import.py"
    if not module_path.exists():
        raise FileNotFoundError(f"Database import module not found at: {module_path}")
    
    if str(module_dir) not in sys.path:
        sys.path.insert(0, str(module_dir))
        
    spec = importlib.util.spec_from_file_location("db_import_module", str(module_path))
    db_import = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(db_import)
    return db_import.get_db_connection

get_db_connection = load_db_connection_func()

import psycopg2
from psycopg2.extras import execute_values


def fetch_raw_skill_occurrences(min_occurrence_ratio: float = 0.0) -> List[Tuple[str, int, str, int]]:
    """
    Fetches raw count n(s, t) of jobs containing skill s in search group t.
    
    Returns:
        List[Tuple[str, int, str, int]]: A list of tuples of 
        (search_group, skill_id, skill_name, job_count_with_skill).
    """
    query = """
        WITH group_job_counts AS (
            SELECT 
                search_group,
                COUNT(DISTINCT job_id) AS total_jobs
            FROM 
                public.jobs
            WHERE 
                search_group IS NOT NULL
            GROUP BY 
                search_group
        ),
        skill_occurrences AS (
            SELECT 
                j.search_group,
                s.skill_id,
                s.skill_name,
                COUNT(DISTINCT j.job_id) AS job_count_with_skill
            FROM 
                public.jobs j
            INNER JOIN 
                public.job_skills js ON j.job_id = js.job_id
            INNER JOIN 
                public.skills s ON js.skill_id = s.skill_id
            WHERE 
                j.search_group IS NOT NULL
            GROUP BY 
                j.search_group, 
                s.skill_id,
                s.skill_name
        )
        SELECT 
            so.search_group,
            so.skill_id,
            so.skill_name,
            so.job_count_with_skill
        FROM 
            skill_occurrences so
        INNER JOIN 
            group_job_counts gc ON so.search_group = gc.search_group
        WHERE 
            (so.job_count_with_skill::float / gc.total_jobs::float) >= %s
        ORDER BY 
            so.search_group ASC, so.job_count_with_skill DESC;
    """

    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(query, (min_occurrence_ratio,))
            results = cursor.fetchall()
            return [(r[0], int(r[1]), r[2], int(r[3])) for r in results]
    except Exception as exc:
        print(f"[ERROR] Failed fetching skill occurrences from DB: {exc}")
        raise exc
    finally:
        if conn is not None and not conn.closed:
            conn.close()


def calculate_tf_idf(corpus: List[Tuple[str, int, str, int]]) -> Dict[str, Dict[int, float]]:
    """
    Calculates the TF-IDF weights for skills within each search group based on skill_id.
    
    Formulas:
      TF(s, t) = 1 + ln(n(s, t))   (where n(s, t) > 0)
      IDF(s) = ln(|T| / m)         (where |T| is total search groups, m is groups containing skill s)
      
    Args:
        corpus: List of (search_group, skill_id, skill_name, job_count_with_skill).
        
    Returns:
        Dict[str, Dict[int, float]]: Mapping of search_group -> { skill_id: tf_idf_score }
    """
    search_groups = set()
    skill_group_map: Dict[int, set] = {}
    skill_occurrences: Dict[Tuple[str, int], int] = {}
    
    # 1. Group records and count active titles/groups
    for group, skill_id, skill_name, count in corpus:
        if count <= 0:
            continue
        search_groups.add(group)
        skill_occurrences[(group, skill_id)] = count
        
        if skill_id not in skill_group_map:
            skill_group_map[skill_id] = set()
        skill_group_map[skill_id].add(group)
        
    total_groups = len(search_groups)  # |T|
    
    # 2. Calculate IDF scores
    idf_scores: Dict[int, float] = {}
    for skill_id, groups_with_skill in skill_group_map.items():
        m = len(groups_with_skill)
        
        # Exception handling / Safety guard for division by zero (m = 0)
        if m == 0 or total_groups == 0:
            idf_scores[skill_id] = 0.0
        else:
            idf_scores[skill_id] = math.log(total_groups / m)
            
    # 3. Calculate TF-IDF scores
    tf_idf_results: Dict[str, Dict[int, float]] = {}
    for (group, skill_id), count in skill_occurrences.items():
        # TF = 1 + ln(n(s, t))
        tf = 1.0 + math.log(count)
        
        # TF-IDF = TF * IDF
        idf = idf_scores.get(skill_id, 0.0)
        score = tf * idf
        
        if group not in tf_idf_results:
            tf_idf_results[group] = {}
        tf_idf_results[group][skill_id] = score
        
    return tf_idf_results


def normalize_weights(tf_idf_scores: Dict[str, Dict[int, float]]) -> Dict[str, Dict[int, float]]:
    """
    Normalizes TF-IDF scores for each search group so that the sum of skill weights for
    each search group equals 1.0.
    
    If a search group has all zero weights, it distributes them uniformly.
    """
    normalized: Dict[str, Dict[int, float]] = {}
    for group, skill_map in tf_idf_scores.items():
        total = sum(skill_map.values())
        if total <= 0:
            num_skills = len(skill_map)
            val = 1.0 / num_skills if num_skills > 0 else 0.0
            normalized[group] = {sid: val for sid in skill_map}
        else:
            normalized[group] = {sid: score / total for sid, score in skill_map.items()}
    return normalized


def upsert_tf_idf_weights(conn, tf_idf_weights: Dict[str, Dict[int, float]], replace: bool = False):
    """
    Inserts or updates the calculated TF-IDF weights in public.job_group_skill_weights.
    """
    rows = []
    for group, skill_map in tf_idf_weights.items():
        for skill_id, weight in skill_map.items():
            rows.append((group, skill_id, weight))
            
    if not rows:
        print("No weights computed to upsert.")
        return

    cur = conn.cursor()
    try:
        if replace:
            print("Clearing existing entries in public.job_group_skill_weights...")
            cur.execute("DELETE FROM public.job_group_skill_weights;")
            
        sql = """
            INSERT INTO public.job_group_skill_weights (search_group, skill_id, weight_wi)
            VALUES %s
            ON CONFLICT (search_group, skill_id) 
            DO UPDATE SET weight_wi = EXCLUDED.weight_wi;
        """
        
        print(f"Upserting {len(rows)} records into public.job_group_skill_weights...")
        execute_values(cur, sql, rows)
        conn.commit()
        print("Database transaction committed successfully.")
    except Exception as e:
        conn.rollback()
        print(f"[ERROR] Database upsert transaction failed: {e}")
        raise e
    finally:
        cur.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Calculate TF-IDF and update DB weights.")
    parser.add_argument("--threshold", type=float, default=0.0, help="Minimum job occurrence ratio (0.0 to 1.0)")
    parser.add_argument("--normalize", action="store_true", default=True, help="Normalize weights to sum to 1.0 per group")
    parser.add_argument("--no-normalize", action="store_false", dest="normalize", help="Do not normalize weights")
    parser.add_argument("--replace", action="store_true", help="Clear target weights table before inserting")
    parser.add_argument("--dry-run", action="store_true", help="Run calculations without writing to the database")
    args = parser.parse_args()
    
    try:
        # 1. Fetch data
        print(f"Fetching skill occurrences from database (occurrence ratio >= {args.threshold * 100:.1f}%)...")
        raw_data = fetch_raw_skill_occurrences(args.threshold)
        
        # Build mapping of skill_id -> skill_name for readable dry-runs
        skill_id_to_name = {r[1]: r[2] for r in raw_data}
        
        # 2. Compute TF-IDF
        print("Computing TF-IDF scores...")
        weights = calculate_tf_idf(raw_data)
        
        # 3. Normalize if requested
        if args.normalize:
            print("Normalizing skill weights per search group...")
            weights = normalize_weights(weights)
            
        print("\nTF-IDF Weighting Calculation completed successfully.")
        print(f"Processed {len(weights)} search groups.")
        
        # 4. Preview top results
        print("\n[Preview of top 3 skills by weight for sample groups]:")
        sample_groups = list(weights.keys())[:3]
        for g in sample_groups:
            print(f"\nGroup: {g}")
            sorted_skills = sorted(weights[g].items(), key=lambda x: x[1], reverse=True)
            for skill_id, weight in sorted_skills[:3]:
                name = skill_id_to_name.get(skill_id, f"ID {skill_id}")
                print(f"  - {name} (ID: {skill_id}): {weight:.6f}")
                
        # 5. Database update
        if args.dry_run:
            print("\n[DRY RUN] Skipping database upsert.")
        else:
            print("\nConnecting to database for update...")
            conn = get_db_connection()
            try:
                upsert_tf_idf_weights(conn, weights, replace=args.replace)
            finally:
                conn.close()
                
    except Exception as e:
        print(f"\n[CRITICAL ERROR] Execution failed: {e}")
        sys.exit(1)
