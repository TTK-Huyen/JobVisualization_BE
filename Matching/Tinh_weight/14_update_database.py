"""
SCRIPT 14: UPDATE DATABASE WITH CALCULATED WEIGHTS
====================================================

This script reads the final job_group_skill_weights.json and inserts/updates
the PostgreSQL database table: job_group_skill_weights

Usage:
    python 14_update_database.py                # Uses root folder JSON
    python 14_update_database.py --output-dir Test/   # Uses custom directory

Database Schema:
    CREATE TABLE job_group_skill_weights (
        search_group VARCHAR(100),
        skill_id INT,
        weight_wi DECIMAL(8,4),
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

Environment Variables (PostgreSQL):
    PG_HOST, PG_PORT, PG_DB, PG_USER, PG_PASSWORD

Example:
    export PG_HOST=localhost PG_PORT=5432 PG_DB=postgres PG_USER=postgres PG_PASSWORD=123456
    python 14_update_database.py
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime
import psycopg2
from psycopg2.extras import execute_batch

def get_db_connection():
    """Create PostgreSQL database connection from environment variables."""
    try:
        conn = psycopg2.connect(
            host=os.getenv('PG_HOST', 'localhost'),
            port=int(os.getenv('PG_PORT', 5432)),
            database=os.getenv('PG_DB', 'postgres'),
            user=os.getenv('PG_USER', 'postgres'),
            password=os.getenv('PG_PASSWORD', '123456')
        )
        return conn
    except psycopg2.Error as e:
        print(f"[!] Database connection failed:")
        print(f"    {e}")
        print(f"\n[*] Check environment variables:")
        print(f"    PG_HOST={os.getenv('PG_HOST', 'localhost')}")
        print(f"    PG_PORT={os.getenv('PG_PORT', 5432)}")
        print(f"    PG_DB={os.getenv('PG_DB', 'postgres')}")
        print(f"    PG_USER={os.getenv('PG_USER', 'postgres')}")
        return None

def load_weights_json(json_file):
    """Load job_group_skill_weights.json."""
    if not json_file.exists():
        print(f"[!] JSON file not found: {json_file}")
        return None
    
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data
    except json.JSONDecodeError as e:
        print(f"[!] JSON parsing error: {e}")
        return None

def prepare_insert_data(weights_data):
    """Convert JSON to list of tuples for database insertion."""
    records = []
    
    if 'job_group_skill_weights' not in weights_data:
        print("[!] Invalid JSON structure: missing 'job_group_skill_weights' key")
        return []
    
    items = weights_data.get('job_group_skill_weights', [])
    
    for item in items:
        search_group = item.get('search_group')
        if not search_group:
            continue
        
        skills = item.get('skill_weights', [])
        for skill in skills:
            record = (
                search_group,
                int(skill.get('skill_id', 0)),
                float(skill.get('weight_wi', 0.0))
            )
            records.append(record)
    
    return records

def clear_old_data(conn):
    """Clear old data from job_group_skill_weights table before insert."""
    try:
        with conn.cursor() as cur:
            # Check if table exists
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'job_group_skill_weights'
                )
            """)
            exists = cur.fetchone()[0]
            
            if not exists:
                print("[*] Creating table job_group_skill_weights...")
                cur.execute("""
                    CREATE TABLE job_group_skill_weights (
                        search_group VARCHAR(100),
                        skill_id INT,
                        weight_wi DECIMAL(8,4),
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                print("[OK] Table created")
            else:
                print("[*] Clearing old data from job_group_skill_weights...")
                cur.execute("DELETE FROM job_group_skill_weights")
                print(f"[OK] Deleted old records")
        
        conn.commit()
        return True
    except psycopg2.Error as e:
        print(f"[!] Error clearing data: {e}")
        conn.rollback()
        return False

def insert_weights(conn, records):
    """Insert weight records into database."""
    if not records:
        print("[!] No records to insert")
        return 0
    
    try:
        with conn.cursor() as cur:
            # Use batch insert for efficiency
            sql = """
                INSERT INTO job_group_skill_weights 
                (search_group, skill_id, weight_wi)
                VALUES (%s, %s, %s)
            """
            
            execute_batch(cur, sql, records, page_size=100)
            conn.commit()
            
            print(f"[OK] Inserted {len(records)} records")
            return len(records)
    except psycopg2.Error as e:
        print(f"[!] Insert error: {e}")
        conn.rollback()
        return 0

def show_summary(conn):
    """Show summary of inserted data."""
    try:
        with conn.cursor() as cur:
            # Count by search_group
            cur.execute("""
                SELECT search_group, COUNT(*) as skill_count
                FROM job_group_skill_weights
                GROUP BY search_group
                ORDER BY search_group
            """)
            groups = cur.fetchone()
            
            print("\n[*] Database Summary:")
            print("=" * 80)
            
            cur.execute("""
                SELECT search_group, COUNT(*) as skill_count
                FROM job_group_skill_weights
                GROUP BY search_group
                ORDER BY search_group
            """)
            
            for group_name, count in cur.fetchall():
                print(f"  {group_name:20} : {count:3} skills")
            
            # Total count
            cur.execute("SELECT COUNT(*) FROM job_group_skill_weights")
            total = cur.fetchone()[0]
            print("-" * 80)
            print(f"  {'TOTAL':20} : {total:3} records")
            print("=" * 80)
    except psycopg2.Error as e:
        print(f"[!] Error showing summary: {e}")

def update_database():
    """Main function: Update database with calculated weights."""
    
    print("\n" + "="*80)
    print("[*] DATABASE UPDATE PROCESS")
    print("="*80)
    
    # Get output directory (run_pipeline sets this as env var)
    output_dir = os.getenv('PIPELINE_OUTPUT_DIR')
    if output_dir:
        output_dir = Path(output_dir)
    else:
        # Check command line arguments
        if len(sys.argv) > 1 and sys.argv[1] == '--output-dir':
            output_dir = Path(sys.argv[2])
        else:
            output_dir = Path(__file__).parent
    
    json_file = output_dir / "job_group_skill_weights.json"
    
    print(f"\n[>] Loading weights from: {json_file}")
    weights_data = load_weights_json(json_file)
    if not weights_data:
        return False
    
    # Prepare records
    records = prepare_insert_data(weights_data)
    print(f"[OK] Loaded {len(records)} skill weights")
    
    # Connect to database
    print(f"\n[>] Connecting to PostgreSQL...")
    print(f"    Host: {os.getenv('PG_HOST', 'localhost')}")
    print(f"    DB: {os.getenv('PG_DB', 'postgres')}")
    
    conn = get_db_connection()
    if not conn:
        return False
    
    print("[OK] Connected to database")
    
    # Clear old data
    print(f"\n[>] Clearing old data...")
    if not clear_old_data(conn):
        conn.close()
        return False
    
    # Insert new data
    print(f"\n[>] Inserting new weights...")
    inserted = insert_weights(conn, records)
    
    if inserted > 0:
        print(f"\n[OK] Successfully inserted {inserted} records")
        show_summary(conn)
        conn.close()
        print("\n[OK] DATABASE UPDATE SUCCESSFUL!")
        print("="*80 + "\n")
        return True
    else:
        print("\n[!] No records inserted")
        conn.close()
        return False

if __name__ == "__main__":
    success = update_database()
    sys.exit(0 if success else 1)
