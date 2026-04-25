"""
PREFETCH SKILL TYPES FROM DATABASE
Fetch skill metadata (skill_name, type: Specialized/Common) once and cache
Used by: 13_aggregate_calculate_weights.py
"""

import json
import os
from pathlib import Path
from datetime import datetime

# PostgreSQL connection
try:
    import psycopg2
    from psycopg2 import sql
    PG_AVAILABLE = True
except ImportError:
    PG_AVAILABLE = False
    print("[!] psycopg2 not installed. Install: pip install psycopg2-binary")

# Get output directory
OUTPUT_DIR = os.getenv('PIPELINE_OUTPUT_DIR')
if OUTPUT_DIR:
    OUTPUT_DIR = Path(OUTPUT_DIR)
else:
    OUTPUT_DIR = Path(__file__).parent

CACHE_FILE = OUTPUT_DIR / "skill_types_cache.json"

# PostgreSQL config
PG_CONFIG = {
    'host': os.getenv('PG_HOST', 'localhost'),
    'port': int(os.getenv('PG_PORT', '5432')),
    'database': os.getenv('PG_DB', 'postgres'),
    'user': os.getenv('PG_USER', 'postgres'),
    'password': os.getenv('PG_PASSWORD', ''),
}


def fetch_skill_types(table_name: str = "skills", type_column: str = "type") -> dict:
    """
    Fetch skill metadata from database.
    
    Returns: {skill_name_lower: {id, name, type}}
    """
    if not PG_AVAILABLE:
        print("[!] Error: psycopg2 not available")
        return {}
    
    print(f"🔗 Connecting to PostgreSQL: {PG_CONFIG['host']}:{PG_CONFIG['port']}")
    
    try:
        conn = psycopg2.connect(**PG_CONFIG)
        cursor = conn.cursor()
        
        print(f"📊 Fetching skill types from table: {table_name}")
        
        # Query: SELECT id, name, type FROM skills
        query = f"""
            SELECT 
                id, 
                name, 
                {type_column}
            FROM {table_name}
            WHERE {type_column} IS NOT NULL
            ORDER BY id
        """
        
        cursor.execute(query)
        rows = cursor.fetchall()
        
        print(f"✓ Fetched {len(rows)} skills")
        
        # Build mapping: {skill_name_lower: {id, name, type}}
        skill_types = {}
        for row in rows:
            skill_id, skill_name, skill_type = row
            skill_name_lower = skill_name.lower()
            skill_types[skill_name_lower] = {
                'id': skill_id,
                'name': skill_name,
                'type': skill_type  # 'Specialized Skill' or 'Common skill'
            }
        
        cursor.close()
        conn.close()
        
        # Count by type
        specialized_count = sum(1 for v in skill_types.values() if 'Specialized' in v['type'])
        common_count = sum(1 for v in skill_types.values() if 'Common' in v['type'])
        
        print(f"  • Specialized: {specialized_count}")
        print(f"  • Common:      {common_count}")
        
        return skill_types
        
    except Exception as e:
        print(f"[!] Database error: {e}")
        return {}


def save_cache(skill_types: dict):
    """Save skill types to cache file."""
    cache_data = {
        'timestamp': datetime.now().isoformat(),
        'total_skills': len(skill_types),
        'skill_types': skill_types
    }
    
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache_data, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Cache saved: {CACHE_FILE}")
    return skill_types


def load_cache() -> dict:
    """Load cached skill types."""
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                cached_time = data.get('timestamp', 'unknown')
                print(f"✓ Loaded cache ({len(data.get('skill_types', {}))} skills, {cached_time})")
                return data.get('skill_types', {})
        except Exception as e:
            print(f"[!] Cache load error: {e}")
    
    return {}


def get_skill_types(use_cache: bool = True) -> dict:
    """
    Get skill types - from cache or fetch fresh from DB.
    
    Args:
        use_cache: If True, load from cache if exists
        
    Returns:
        {skill_name_lower: {id, name, type}}
    """
    if use_cache:
        cached = load_cache()
        if cached:
            return cached
    
    print("🔄 Fetching fresh from database...")
    skill_types = fetch_skill_types()
    
    if skill_types:
        save_cache(skill_types)
    
    return skill_types


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Prefetch skill types from database')
    parser.add_argument('--no-cache', action='store_true', help='Force refresh (bypass cache)')
    parser.add_argument('--table', default='skills', help='Table name (default: skills)')
    parser.add_argument('--type-column', default='type', help='Type column name (default: type)')
    
    args = parser.parse_args()
    
    skill_types = get_skill_types(use_cache=not args.no_cache)
    
    if skill_types:
        print(f"\n✅ SUCCESS: {len(skill_types)} skills loaded")
    else:
        print("[!] FAILED: No skills loaded")
