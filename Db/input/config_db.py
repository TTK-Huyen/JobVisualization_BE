"""
🗄️ Database Configuration
===========================
PostgreSQL connection - cố định hiện tại, cập nhật khi có thay đổi

Load từ .env file
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env
ENV_FILE = Path(__file__).parent.parent / ".env"
load_dotenv(ENV_FILE)

# ============================================================================
# 🗄️ DATABASE CONNECTION - CỐ ĐỊNH HIỆN TẠI
# ============================================================================
# Cập nhật khi có thay đổi DB
POSTGRES_CONFIG = {
    "host": os.getenv("POSTGRES_HOST", "localhost"),
    "port": int(os.getenv("POSTGRES_PORT", "5432")),
    "database": os.getenv("POSTGRES_DB", "job_db"),
    "user": os.getenv("POSTGRES_USER", "postgres"),
    "password": os.getenv("POSTGRES_PASSWORD", ""),
}

# ============================================================================
# 🔧 CONNECTION UTILITIES
# ============================================================================

def get_connection_string():
    """Build PostgreSQL connection string"""
    cfg = POSTGRES_CONFIG
    password_part = f":{cfg['password']}" if cfg['password'] else ""
    return (
        f"postgresql://{cfg['user']}{password_part}"
        f"@{cfg['host']}:{cfg['port']}/{cfg['database']}"
    )


def get_psycopg2_params():
    """Get params cho psycopg2.connect()"""
    return {
        "host": POSTGRES_CONFIG["host"],
        "port": POSTGRES_CONFIG["port"],
        "database": POSTGRES_CONFIG["database"],
        "user": POSTGRES_CONFIG["user"],
        "password": POSTGRES_CONFIG["password"],
    }


def test_connection():
    """Test DB connection"""
    try:
        import psycopg2
        conn = psycopg2.connect(**get_psycopg2_params())
        print("✓ Database connection OK")
        conn.close()
        return True
    except ImportError:
        print("⚠️  psycopg2 not installed")
        return None
    except Exception as e:
        print(f"✗ Database connection FAILED: {e}")
        return False


def print_db_config():
    """In DB config"""
    print("\n" + "="*60)
    print("🗄️  DATABASE CONFIGURATION")
    print("="*60)
    
    cfg = POSTGRES_CONFIG
    print(f"\n🔗 Connection Info:")
    print(f"  Host: {cfg['host']}")
    print(f"  Port: {cfg['port']}")
    print(f"  Database: {cfg['database']}")
    print(f"  User: {cfg['user']}")
    print(f"  Password: {'*****' if cfg['password'] else '(none)'}")
    
    print("\n" + "="*60)


if __name__ == "__main__":
    print_db_config()
    test_connection()
