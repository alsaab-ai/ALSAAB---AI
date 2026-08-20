# db.py
#
# ALSAAB AI — unified database connection layer.
#
# Replaces the raw `sqlite3.connect(DB_NAME)` in database.py with a pooled
# PostgreSQL connection, WITHOUT requiring any of the ~48 existing
# `cursor.execute(...)` call sites to change.
#
# It does that with a compatibility cursor that translates SQLite dialect to
# PostgreSQL on the fly:
#   ?                                      -> %s          (placeholders)
#   INTEGER PRIMARY KEY AUTOINCREMENT      -> BIGSERIAL PRIMARY KEY
#   TEXT DEFAULT CURRENT_TIMESTAMP         -> TIMESTAMPTZ DEFAULT NOW()
#   INSERT OR IGNORE INTO                  -> INSERT INTO ... ON CONFLICT DO NOTHING
#   PRAGMA table_info(x)                   -> information_schema.columns query
#   cursor.lastrowid                       -> lastval()
#
# Backend selection:
#   DATABASE_URL set  -> PostgreSQL  (production)
#   DATABASE_URL unset -> SQLite      (local dev, unchanged behaviour)
#
# Self-test:
#   python backend/db.py --check
#
# That check also resolves the database host's A/AAAA records, which is how we
# confirm whether Render (IPv4-only outbound) can reach the Supabase pooler.

import os
import re
import socket
import sqlite3
import sys
import time


def _load_dotenv():
    """
    Read a local .env file so DATABASE_URL does not have to be typed into a
    terminal (or pasted into a chat) on every run. Render injects its own
    environment variables, so this only ever matters on a dev machine.

    Real environment variables always win over the file, and .env is already
    listed in .gitignore so the password cannot be committed.
    """
    for candidate in (
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"),
        os.path.join(os.getcwd(), ".env"),
    ):
        if not os.path.isfile(candidate):
            continue

        try:
            with open(candidate, "r", encoding="utf-8-sig") as handle:
                for line in handle:
                    line = line.strip()

                    if not line or line.startswith("#") or "=" not in line:
                        continue

                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")

                    if key and key not in os.environ:
                        os.environ[key] = value
        except Exception as error:
            print(f"WARNING: could not read {candidate}: {error}", flush=True)

        break


def _normalize_database_url(url):
    """
    Percent-encode the password inside DATABASE_URL if it isn't already.

    Supabase generates passwords containing @ # ? / and similar. Pasted raw
    into a URL, the first @ is read as the host separator and a # starts a
    fragment, so the connection silently goes somewhere else. Encoding here
    means the password can be pasted verbatim into .env or into Render.
    """
    from urllib.parse import quote, unquote

    if not url or "://" not in url or "@" not in url:
        return url

    try:
        scheme, rest = url.split("://", 1)
        credentials, host_part = rest.rsplit("@", 1)

        if ":" not in credentials:
            return url

        user, password = credentials.split(":", 1)
        encoded = quote(unquote(password), safe="")

        return f"{scheme}://{user}:{encoded}@{host_part}"
    except Exception:
        return url


_load_dotenv()

DB_NAME = os.getenv("SQLITE_DB_PATH", "alsaab_ai.db")
DATABASE_URL = _normalize_database_url(os.getenv("DATABASE_URL", "").strip())

# Explicit override wins; otherwise presence of DATABASE_URL decides.
DATA_BACKEND = os.getenv(
    "DATA_BACKEND",
    "postgres" if DATABASE_URL else "sqlite",
).lower().strip()

USING_POSTGRES = DATA_BACKEND == "postgres"


# =====================================================================
# SQL dialect translation
# =====================================================================

_AUTOINC_RE = re.compile(
    r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b",
    re.IGNORECASE,
)
_TEXT_TS_RE = re.compile(
    r"\bTEXT\s+DEFAULT\s+CURRENT_TIMESTAMP\b",
    re.IGNORECASE,
)
_INSERT_IGNORE_RE = re.compile(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", re.IGNORECASE)
_PRAGMA_RE = re.compile(r"^\s*PRAGMA\s+table_info\s*\(\s*([\"'`\[]?)(\w+)\1\s*\)\s*;?\s*$", re.IGNORECASE)

_PRAGMA_REPLACEMENT = """
SELECT (ordinal_position - 1)::INT AS cid,
       column_name                 AS name,
       data_type                   AS type,
       CASE WHEN is_nullable = 'NO' THEN 1 ELSE 0 END AS notnull,
       column_default              AS dflt_value,
       0                           AS pk
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = %s
ORDER BY ordinal_position
"""


def _rewrite_placeholders(sql):
    """
    Turn SQLite's `?` placeholders into psycopg's `%s`, and escape any literal
    `%` so psycopg does not mistake it for a placeholder.

    Characters inside single/double-quoted string literals are left alone.
    """
    out = []
    quote = None
    i = 0
    length = len(sql)

    while i < length:
        ch = sql[i]

        if quote:
            out.append(ch)
            if ch == quote:
                # Doubled quote ('') is an escaped quote, not a terminator.
                if i + 1 < length and sql[i + 1] == quote:
                    out.append(sql[i + 1])
                    i += 2
                    continue
                quote = None
            i += 1
            continue

        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
        elif ch == "?":
            out.append("%s")
        elif ch == "%":
            out.append("%%")
        else:
            out.append(ch)

        i += 1

    return "".join(out)


def translate_sql(sql):
    """Translate one SQLite statement into its PostgreSQL equivalent."""
    pragma = _PRAGMA_RE.match(sql or "")
    if pragma:
        return _PRAGMA_REPLACEMENT, pragma.group(2)

    translated = _AUTOINC_RE.sub("BIGSERIAL PRIMARY KEY", sql or "")
    translated = _TEXT_TS_RE.sub("TIMESTAMPTZ DEFAULT NOW()", translated)

    if _INSERT_IGNORE_RE.search(translated):
        translated = _INSERT_IGNORE_RE.sub("INSERT INTO", translated)
        translated = translated.rstrip().rstrip(";")
        translated += " ON CONFLICT DO NOTHING"

    return _rewrite_placeholders(translated), None


# =====================================================================
# PostgreSQL backend
# =====================================================================

_pool = None


def _get_pool():
    global _pool

    if _pool is None:
        from psycopg_pool import ConnectionPool

        _pool = ConnectionPool(
            conninfo=DATABASE_URL,
            min_size=int(os.getenv("DB_POOL_MIN", "1")),
            max_size=int(os.getenv("DB_POOL_MAX", "8")),
            timeout=int(os.getenv("DB_POOL_TIMEOUT", "20")),
            max_idle=300,
            # Supabase's transaction pooler closes idle server-side sessions;
            # recycling keeps us from handing out a dead connection.
            max_lifetime=1800,
            open=True,
            kwargs={
                "autocommit": False,
                # Supabase's transaction pooler (port 6543) hands each
                # transaction to whichever server session is free, so psycopg's
                # server-side prepared statements collide across sessions:
                #     DuplicatePreparedStatement: prepared statement
                #     "_pg3_0" already exists
                # None disables them. Costs a little planning time per query,
                # which at same-region latency is irrelevant.
                "prepare_threshold": None,
            },
        )

    return _pool


class _CompatCursor:
    """
    Wraps a psycopg cursor so it accepts the SQLite-flavoured SQL that
    database.py already contains.
    """

    def __init__(self, cursor):
        self._cursor = cursor
        self._did_insert = False

    def execute(self, sql, params=None):
        translated, pragma_table = translate_sql(sql)

        if pragma_table is not None:
            params = (pragma_table,)
        elif not params:
            # psycopg only parses placeholders when params is not None. Passing
            # an empty tuple makes it parse anyway, so a query with a literal %
            # and no parameters — LIKE 'cancel%', date_trunc formats — fails
            # with "only '%s', '%b', '%t' are allowed as placeholders".
            params = None

        self._did_insert = translated.lstrip()[:6].upper() == "INSERT"
        self._cursor.execute(translated, params)
        return self

    def executemany(self, sql, seq_of_params):
        translated, _ = translate_sql(sql)
        self._cursor.executemany(translated, seq_of_params)
        return self

    @property
    def lastrowid(self):
        """
        SQLite exposes the auto-generated rowid here (used by save_lead()).
        PostgreSQL has no equivalent, but lastval() returns the value most
        recently produced by a sequence in THIS session, which is exactly the
        identity value of the row we just inserted.
        """
        if not self._did_insert:
            return None

        try:
            self._cursor.execute("SELECT lastval()")
            row = self._cursor.fetchone()
            return row[0] if row else None
        except Exception:
            # No sequence used yet in this session, or the table has no
            # identity column. Neither is an error worth propagating.
            return None

    def __getattr__(self, name):
        return getattr(self._cursor, name)

    def __iter__(self):
        return iter(self._cursor)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class _PooledConnection:
    """
    Looks and behaves like a sqlite3.Connection to the calling code, but
    `close()` returns the connection to the pool instead of destroying it.

    Roughly ninety call sites in database.py follow the sqlite habit of

        conn = get_connection()
        ...
        conn.close()

    with no try/finally. Under SQLite a raised exception in between cost
    nothing — the connection object was garbage and the file handle went with
    it. Against a pool it is a leak: that connection is checked out forever,
    and after max_size failures the pool is empty and every later request dies
    with "couldn't get a connection after 20.00 sec", including requests that
    would have succeeded.

    The weakref finalizer below hands the connection back as soon as Python
    collects the wrapper, so an un-closed connection self-heals instead of
    permanently draining the pool. Explicit close() is still the fast path.
    """

    def __init__(self, conn, pool):
        self._conn = conn
        self._pool = pool
        self._closed = False

        import weakref

        self._finalizer = weakref.finalize(self, self._reclaim, conn, pool)

    @staticmethod
    def _reclaim(conn, pool):
        """Runs on garbage collection when close() was never reached."""
        try:
            conn.rollback()
        except Exception:
            pass

        try:
            pool.putconn(conn)
        except Exception:
            pass

    def cursor(self):
        return _CompatCursor(self._conn.cursor())

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def execute(self, sql, params=None):
        cur = self.cursor()
        cur.execute(sql, params)
        return cur

    def close(self):
        if self._closed:
            return

        self._closed = True

        # Detach the finalizer first so the connection is not handed back a
        # second time when this wrapper is later collected.
        self._finalizer.detach()

        try:
            # A connection handed back mid-transaction would leak that
            # transaction to the next borrower.
            self._conn.rollback()
        except Exception:
            pass

        try:
            self._pool.putconn(self._conn)
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *exc):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        self.close()
        return False


# =====================================================================
# Public API — this is what database.py calls
# =====================================================================

def get_connection():
    """
    Drop-in replacement for `sqlite3.connect(DB_NAME)`.

    Callers keep using cursor()/execute()/commit()/close() exactly as before.
    """
    if not USING_POSTGRES:
        return sqlite3.connect(DB_NAME)

    pool = _get_pool()
    return _PooledConnection(pool.getconn(), pool)


def backend_name():
    return "postgres" if USING_POSTGRES else "sqlite"


def close_pool():
    global _pool

    if _pool is not None:
        try:
            _pool.close()
        finally:
            _pool = None


# =====================================================================
# Diagnostics — python backend/db.py --check
# =====================================================================

def _mask_url(url):
    """Never print the password, even into a local terminal or a log file."""
    return re.sub(r"://([^:/@]+):([^@]+)@", r"://\1:****@", url or "")


def _resolve_host(host, port):
    """
    Report the A (IPv4) and AAAA (IPv6) records for the database host.

    Render's outbound network is IPv4-only, so a host that resolves to AAAA
    records only is the difference between "works" and "connection timed out".
    """
    families = {socket.AF_INET: [], socket.AF_INET6: []}

    for family in (socket.AF_INET, socket.AF_INET6):
        try:
            for info in socket.getaddrinfo(host, port, family, socket.SOCK_STREAM):
                addr = info[4][0]
                if addr not in families[family]:
                    families[family].append(addr)
        except socket.gaierror:
            pass

    return families[socket.AF_INET], families[socket.AF_INET6]


def check():
    print("=" * 62)
    print("ALSAAB AI - database connectivity check")
    print("=" * 62)
    print(f"backend        : {backend_name()}")

    if not USING_POSTGRES:
        print(f"sqlite file    : {os.path.abspath(DB_NAME)}")
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [r[0] for r in cur.fetchall()]
        conn.close()
        print(f"tables         : {len(tables)}")
        print(f"               : {', '.join(tables) or '(none)'}")
        print("\nDATABASE_URL is not set, so SQLite is in use.")
        return 0

    print(f"DATABASE_URL   : {_mask_url(DATABASE_URL)}")

    host_match = re.search(r"@([^/:?]+)(?::(\d+))?", DATABASE_URL)
    host = host_match.group(1) if host_match else ""
    port = int(host_match.group(2)) if host_match and host_match.group(2) else 5432

    print(f"host           : {host}")
    print(f"port           : {port}")

    ipv4, ipv6 = _resolve_host(host, port)
    print(f"IPv4 (A)       : {', '.join(ipv4) if ipv4 else '(none)'}")
    print(f"IPv6 (AAAA)    : {', '.join(ipv6) if ipv6 else '(none)'}")

    if not ipv4 and ipv6:
        print()
        print("  !! This host has IPv6 addresses ONLY.")
        print("  !! Render's outbound network is IPv4-only, so the app will")
        print("  !! NOT be able to reach it. Fixes, cheapest first:")
        print("  !!   1. Use the Session pooler string (port 5432) instead.")
        print("  !!   2. Buy Supabase's dedicated IPv4 add-on.")

    print("-" * 62)

    try:
        # Connect once WITHOUT the pool first. The pool reports every failure
        # as PoolTimeout, which makes a simply-wrong password look like a
        # network problem and sends you hunting for firewall or IPv6 issues.
        import psycopg

        started = time.time()
        probe = psycopg.connect(DATABASE_URL, connect_timeout=15, prepare_threshold=None)
        probe.close()
        connect_ms = (time.time() - started) * 1000

        conn = get_connection()

        cur = conn.cursor()

        started = time.time()
        cur.execute("SELECT 1")
        cur.fetchone()
        rtt_ms = (time.time() - started) * 1000

        cur.execute("SELECT version()")
        version = cur.fetchone()[0]

        cur.execute("SELECT current_database(), current_user")
        dbname, dbuser = cur.fetchone()

        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' ORDER BY table_name"
        )
        tables = [r[0] for r in cur.fetchall()]

        conn.close()

        print("connection     : OK")
        print(f"handshake      : {connect_ms:.0f} ms")
        print(f"query RTT      : {rtt_ms:.1f} ms")
        print(f"database/user  : {dbname} / {dbuser}")
        print(f"server         : {version.split(',')[0]}")
        print(f"tables         : {len(tables)}")

        if tables:
            for i in range(0, len(tables), 4):
                print("               : " + ", ".join(tables[i:i + 4]))
        else:
            print("               : (none — run db/schema.sql first)")

        print("-" * 62)

        on_render = bool(os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID"))

        if rtt_ms < 20:
            print("VERDICT: same-region latency. This is what production needs.")
        elif not on_render:
            # Run from a laptop, this number is the distance from HERE to
            # Oregon, which says nothing about the app's latency. Only the
            # reading taken on Render is the one that matters.
            print(f"VERDICT: {rtt_ms:.0f} ms — but this is running on a local machine,")
            print("         not on Render, so it is measuring your own distance to")
            print("         Oregon. Expect single-digit ms once the app connects")
            print("         from Render (same AWS region, us-west-2).")
            print("         Re-run this from Render Shell for the real number.")
        elif rtt_ms < 80:
            print("VERDICT: acceptable, but not same-region. Double-check regions.")
        else:
            print(f"VERDICT: {rtt_ms:.0f} ms is too slow — app and database are")
            print("         almost certainly in different regions.")

        return 0

    except Exception as error:
        print("connection     : FAILED")
        print(f"error          : {type(error).__name__}: {error}")
        print("-" * 62)

        text = str(error).lower()
        if "timeout" in text or "timed out" in text or "unreachable" in text:
            print("Most likely the IPv6 problem described above, or the")
            print("database is still provisioning.")
        elif "password" in text or "authentication" in text:
            print("Credentials rejected. Re-copy the connection string and")
            print("percent-encode any special characters in the password.")
        elif "does not exist" in text:
            print("Database or role name is wrong in the connection string.")

        return 1


if __name__ == "__main__":
    if "--check" in sys.argv:
        raise SystemExit(check())

    print("usage: python backend/db.py --check")
    raise SystemExit(2)
