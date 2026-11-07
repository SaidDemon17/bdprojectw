"""Conexiones PostgreSQL por proceso y transacciones con devolución segura al pool."""
import os
from contextlib import contextmanager
from threading import Lock

from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

_pool = None
_pid = None
_lock = Lock()


def get_pool():
    """Crear el pool de forma diferida, después del fork de gunicorn."""
    global _pool, _pid
    with _lock:
        if _pool is None or _pid != os.getpid():
            url = os.environ.get("DATABASE_URL")
            if not url:
                raise RuntimeError("Falta configurar DATABASE_URL.")
            _pool = ThreadedConnectionPool(
                1, int(os.getenv("DB_POOL_MAX", "5")), dsn=url,
                connect_timeout=10, application_name="fitness_planet",
            )
            _pid = os.getpid()
        return _pool


@contextmanager
def transaction():
    """Confirmar todo el bloque o revertirlo completo ante cualquier excepción."""
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                # SET LOCAL funciona también con el pooler en modo transacción.
                cursor.execute("SET LOCAL TIME ZONE 'America/Lima'")
                cursor.execute("SET LOCAL statement_timeout = '15s'")
                cursor.execute("SET LOCAL lock_timeout = '5s'")
                yield cursor
    finally:
        pool.putconn(conn, close=bool(conn.closed))


def fetch_all(sql, params=()):
    """Ejecutar SQL fijo y parámetros separados; devolver filas con nombres."""
    with transaction() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


def fetch_one(sql, params=()):
    """Consultar una fila en una transacción breve."""
    with transaction() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchone()


def execute(sql, params=()):
    """Ejecutar una modificación con confirmación automática."""
    with transaction() as cursor:
        cursor.execute(sql, params)
