"""
Data Fetching Layer for Task 1.2 in the JobVisualization Project.
Aggregates skills by job title directly at the Database Layer using PostgreSQL's array_agg.
"""

import sys
from pathlib import Path
from typing import List, Tuple

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

# Import the database connection utility from the existing pipeline structure dynamically

import importlib.util

def load_db_connection_func():
    module_dir = PROJECT_ROOT / "Db" / "pipeline" / "import"
    module_path = module_dir / "import.py"
    if not module_path.exists():
        raise FileNotFoundError(f"Database import module not found at: {module_path}")
    
    # Add directory to sys.path to resolve internal sibling imports like location_normalization
    if str(module_dir) not in sys.path:
        sys.path.insert(0, str(module_dir))
        
    spec = importlib.util.spec_from_file_location("db_import_module", str(module_path))
    db_import = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(db_import)
    return db_import.get_db_connection

get_db_connection = load_db_connection_func()

import psycopg2


def fetch_aggregated_job_skills(min_occurrence_ratio: float = 0.0) -> List[Tuple[str, List[str]]]:
    """
    Fetches job search groups and their aggregated skills in a single, memory-efficient pass,
    filtering skills by their percentage of occurrence within the group's total jobs.
    
    The row aggregation and threshold filtering are performed entirely at the Database Layer
    using PostgreSQL to avoid high I/O latency and heavy Python-level looping.
    
    Args:
        min_occurrence_ratio (float): The minimum ratio of jobs in a search group that a skill 
                                      must appear in (e.g., 0.50 for 50%).
                                      
    Returns:
        List[Tuple[str, List[str]]]: A list of tuples containing:
            - search_group (str): The classification group of the jobs.
            - skill_list (List[str]): List of distinct skill names meeting the threshold.
    """
    # Optimized SQL query calculating the occurrence ratio of each skill and filtering it
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
                s.skill_name
        )
        SELECT 
            so.search_group,
            COALESCE(array_agg(so.skill_name ORDER BY so.job_count_with_skill DESC), ARRAY[]::text[]) AS skill_list
        FROM 
            skill_occurrences so
        INNER JOIN 
            group_job_counts gc ON so.search_group = gc.search_group
        WHERE 
            (so.job_count_with_skill::float / gc.total_jobs::float) >= %s
        GROUP BY 
            so.search_group
        ORDER BY 
            so.search_group ASC;
    """

    conn = None
    try:
        # Establish PostgreSQL connection using the existing project utility
        conn = get_db_connection()
        
        # Using a context manager for the cursor to ensure automatic cleanup of database cursors
        with conn.cursor() as cursor:
            cursor.execute(query, (min_occurrence_ratio,))
            # Retrieve the complete aggregated dataset in a single round-trip
            results: List[Tuple[str, List[str]]] = cursor.fetchall()
            return results

    except psycopg2.DatabaseError as db_err:
        print(f"[DATABASE ERROR] Failed to fetch aggregated job skills: {db_err}")
        raise db_err
    except Exception as exc:
        print(f"[ERROR] An unexpected error occurred in data fetching layer: {exc}")
        raise exc
    finally:
        # Guarantee connection closure regardless of whether the operation succeeded or failed
        if conn is not None and not conn.closed:
            conn.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Fetch and aggregate job skills by search group.")
    parser.add_argument("--threshold", type=float, default=0.0, help="Minimum occurrence ratio (0.0 to 1.0)")
    args = parser.parse_args()

    try:
        aggregated_corpus = fetch_aggregated_job_skills(args.threshold)
        print("Data Fetching Layer executed successfully.")
        print(f"Fetched {len(aggregated_corpus)} unique search groups with aggregated skills (threshold >= {args.threshold * 100:.1f}%).")
        
        print("\n[Preview of first 10 search groups]:")
        for group, skills in aggregated_corpus[:]:
            # Print the group, total skills count, and the top 5 skills
            skills_preview = ", ".join(skills[:5]) + ("..." if len(skills) > 5 else "")
            print(f" - {group}: {len(skills)} skills ({skills_preview})")
    except Exception as e:
        print(f"Execution failed: {e}")
