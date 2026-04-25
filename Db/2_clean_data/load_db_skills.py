"""
Load all skills from PostgreSQL database
"""

import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

def get_db_connection():
    """Create PostgreSQL connection from .env config"""
    try:
        conn = psycopg2.connect(
            host=os.getenv('PG_HOST', 'localhost'),
            port=os.getenv('PG_PORT', '5432'),
            database=os.getenv('PG_DB', 'postgres'),
            user=os.getenv('PG_USER', 'postgres'),
            password=os.getenv('PG_PASSWORD', '123456')
        )
        return conn
    except Exception as e:
        print(f"❌ DB connection error: {e}")
        return None

def load_all_skills():
    """Fetch all skills from skills table"""
    conn = get_db_connection()
    if not conn:
        print("⚠️  Could not connect to DB, using fallback")
        return []
    
    try:
        cursor = conn.cursor()
        
        # Try to get skills from table (find the right column)
        # Assume structure: skills(id, skill_name) or skills(id, name) or similar
        query = "SELECT * FROM skills LIMIT 1"
        cursor.execute(query)
        columns = [desc[0] for desc in cursor.description]
        print(f"[*] Skills table columns: {columns}")
        
        # Determine which column has the skill name (usually skill_name, name, title, etc)
        skill_col = None
        for col in ['skill_name', 'name', 'title', 'skill']:
            if col in columns:
                skill_col = col
                break
        
        if not skill_col:
            print(f"⚠️  Could not find skill column. Columns: {columns}")
            return[]
        
        # Fetch all skills
        query = f"SELECT {skill_col} FROM skills"
        cursor.execute(query)
        skills = [row[0] for row in cursor.fetchall()]
        
        cursor.close()
        conn.close()
        
        print(f"✅ Loaded {len(skills)} skills from DB")
        return skills
        
    except Exception as e:
        print(f"❌ Error fetching skills: {e}")
        return []

def load_all_benefits():
    """Fetch all benefits from benefits table"""
    conn = get_db_connection()
    if not conn:
        print("⚠️  Could not connect to DB for benefits, using fallback")
        return []
    
    try:
        cursor = conn.cursor()
        
        # Fetch all benefits from benefits table
        query = "SELECT benefit_name FROM benefits ORDER BY benefit_name"
        cursor.execute(query)
        benefits = [row[0] for row in cursor.fetchall()]
        
        cursor.close()
        conn.close()
        
        print(f"✅ Loaded {len(benefits)} benefits from DB")
        return benefits
        
    except Exception as e:
        print(f"❌ Error fetching benefits: {e}")
        return []

if __name__ == "__main__":
    skills = load_all_skills()
    if skills:
        print(f"\nFirst 10 skills: {skills[:10]}")
        print(f"Total: {len(skills)} skills")
    else:
        print("No skills loaded")
    
    benefits = load_all_benefits()
    if benefits:
        print(f"\nFirst 10 benefits: {benefits[:10]}")
        print(f"Total: {len(benefits)} benefits")
    else:
        print("No benefits loaded")
