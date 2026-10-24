"""Private Supabase Postgres storage. The browser never connects to this database."""
import threading
from contextlib import contextmanager
from urllib.parse import unquote, urlsplit

from t2_bots.connect.directory import Directory


class PostgresQueries:
    """Adapt the directory's fixed, parameterized SQLite statements to Psycopg."""
    def __init__(self, connection):
        self.connection = connection

    def execute(self, query, parameters=()):
        if query == "BEGIN IMMEDIATE":
            # SET LOCAL already opened this transaction. Reservations use FOR
            # UPDATE, so exclusivity also holds across different API processes.
            return None
        return self.connection.execute(query.replace("?", "%s"), parameters)


class PostgresDirectory(Directory):
    reservation_query = "SELECT * FROM followers WHERE id=? FOR UPDATE"

    def __init__(self, database_url, project_ref=""):
        parts = urlsplit(database_url)
        if parts.scheme not in ("postgres", "postgresql") or not parts.hostname or not parts.username or not parts.password:
            raise ValueError("T2_DATABASE_URL must be a private Postgres connection URL with credentials.")
        if project_ref and parts.hostname != f"db.{project_ref}.supabase.co" and not unquote(parts.username).endswith("." + project_ref):
            raise ValueError("The database connection does not match T2_SUPABASE_PROJECT_REF.")
        if unquote(parts.username).split(".")[0] != "t2_directory_app":
            raise ValueError("Use the t2_directory_app database role, not a project administrator.")
        try:
            import psycopg
        except ImportError:
            raise RuntimeError("Install the directory extra to use Supabase Postgres.") from None
        self.psycopg = psycopg
        self.integrity_error = psycopg.IntegrityError
        self._database_url = database_url
        self.lock = threading.RLock()
        try:
            with self.db() as db:
                db.execute("SELECT id, username, token FROM devices LIMIT 0")
                db.execute("SELECT id, endpoint, holder, held_until FROM followers LIMIT 0")
        except Exception:
            raise RuntimeError("Cannot access the private directory schema. Apply its migration and check the Render database secret.") from None

    @contextmanager
    def db(self):
        from psycopg.rows import dict_row
        # Use Supabase's pooler. Disabling prepared statements supports its
        # transaction mode; SET LOCAL never persists on a pooled connection.
        with self.psycopg.connect(self._database_url, row_factory=dict_row,
                                  sslmode="require", connect_timeout=5,
                                  prepare_threshold=None) as connection:
            connection.execute("SET LOCAL search_path TO t2_directory, pg_catalog")
            connection.execute("SET LOCAL statement_timeout = '5s'")
            yield PostgresQueries(connection)
