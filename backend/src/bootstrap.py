from pathlib import Path
from .db import connection, wait_for_db
from .config import SEED_DEMO

def main():
    wait_for_db()
    sql = Path(__file__).with_name("schema.sql").read_text()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
    if SEED_DEMO:
        from .seed import seed
        seed()

if __name__ == "__main__":
    main()
