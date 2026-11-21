import time
from contextlib import contextmanager
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from .config import DATABASE_URL

@contextmanager
def connection():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def query(sql, params=(), one=False):
    with connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            return (dict(rows[0]) if rows else None) if one else [dict(row) for row in rows]

def execute(sql, params=()):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.rowcount

@contextmanager
def transaction():
    """多语句事务：yield 一个 RealDictCursor，块内异常回滚，正常结束提交。"""
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def wait_for_db():
    for _ in range(40):
        try:
            with connection():
                return
        except psycopg2.OperationalError:
            time.sleep(1)
    raise RuntimeError("database did not become ready")
