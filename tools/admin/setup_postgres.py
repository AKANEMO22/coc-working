
# Manual tool bootstrap: no imports or network runs from the production app.
import sys
from pathlib import Path
_WORKSPACE = next(parent for parent in Path(__file__).resolve().parents if (parent / "backend" / "app" / "main.py").is_file())
sys.path[:0] = [str(_WORKSPACE), str(_WORKSPACE / "backend")]
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import os

DB_HOST = "127.0.0.1"
DB_PORT = 5432
DB_USER = "postgres"
DB_PASS = "Syrex@X2606"
DB_NAME = "coc_di_lam"

def setup():
    # 1. Connect to postgres default DB to create coc_di_lam DB
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASS,
        dbname="postgres"
    )
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()

    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,))
    if not cur.fetchone():
        cur.execute(f'CREATE DATABASE "{DB_NAME}"')
        print(f"✅ Created database: {DB_NAME}")
    else:
        print(f"ℹ️ Database {DB_NAME} already exists.")

    cur.close()
    conn.close()

    # 2. Connect to coc_di_lam and execute init_db.sql
    conn2 = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASS,
        dbname=DB_NAME
    )
    cur2 = conn2.cursor()

    sql_path = str(_WORKSPACE / "backend" / "init_db.sql")
    with open(sql_path, "r", encoding="utf-8") as f:
        sql = f.read()

    cur2.execute(sql)
    conn2.commit()
    print("✅ Executed init_db.sql successfully on database coc_di_lam!")

    # 3. List tables created
    cur2.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name")
    tables = [row[0] for row in cur2.fetchall()]
    print(f"✅ Total tables verified ({len(tables)}):")
    for t in tables:
        print(f"   - {t}")

    cur2.close()
    conn2.close()

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

if __name__ == "__main__":
    setup()
