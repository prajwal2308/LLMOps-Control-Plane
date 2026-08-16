"""
telemetry.py
------------
This is the HEART of an LLMOps platform: recording what happened on every
single LLM request. Latency, tokens, cost, which provider, success/failure.

Stage 2: Persistent Storage with SQLite.
Stage 7: Statelessness & Pluggable Backend (SQLite vs. PostgreSQL).

To scale horizontally across multiple Kubernetes replicas, the control plane must be
STATELESS. This module supports two backends:
  1. SQLite: Local file storage (`telemetry.db`). Default for single-node local docker-compose.
  2. PostgreSQL: Shared network database for horizontal scaling across multiple k8s replicas.

Backend selection is controlled via environment variables:
  - TELEMETRY_BACKEND = "postgres" | "sqlite" (default: "sqlite")
  - DATABASE_URL = "postgresql://user:pass@host:5432/dbname" (or DB_PATH for SQLite)

Note on Shared Counters / Rate Limiting:
When distributed rate limiting or real-time sliding window counters are added, Redis serves as
the shared in-memory state store, maintaining true horizontal statelessness.
"""

import os
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import uuid

# Optional PostgreSQL driver support
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False


@dataclass
class RequestTelemetry:
    """One row of telemetry: everything we observed about a single request."""
    provider: str                 # which backend served it, e.g. "mock" or "anthropic"
    model: str                    # which model was asked for
    latency_ms: float             # how long the call took, in milliseconds
    prompt_tokens: int            # tokens in the input
    completion_tokens: int        # tokens in the output
    total_tokens: int             # prompt + completion
    cost_usd: float               # estimated dollar cost of this call
    status: str                   # "ok" or "error"
    error: str | None = None      # error message if status == "error"

    # These are filled in automatically -- you don't pass them by hand.
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return asdict(self)


class SQLiteTelemetryStore:
    """SQLite implementation of telemetry storage for single-node / local usage."""

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or os.environ.get("DB_PATH", "telemetry.db")
        self._init_db()

    def _init_db(self) -> None:
        """Create the telemetry table if it doesn't already exist."""
        dirname = os.path.dirname(self.db_path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS telemetry (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    latency_ms REAL NOT NULL,
                    prompt_tokens INTEGER NOT NULL,
                    completion_tokens INTEGER NOT NULL,
                    total_tokens INTEGER NOT NULL,
                    cost_usd REAL NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT
                )
            """)
            conn.commit()

    def record(self, entry: RequestTelemetry) -> None:
        """Save one telemetry row to SQLite."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO telemetry (
                    id, timestamp, provider, model, latency_ms,
                    prompt_tokens, completion_tokens, total_tokens,
                    cost_usd, status, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entry.id, entry.timestamp, entry.provider, entry.model, entry.latency_ms,
                entry.prompt_tokens, entry.completion_tokens, entry.total_tokens,
                entry.cost_usd, entry.status, entry.error
            ))
            conn.commit()

    def _build_where(self, status: str | None, provider: str | None) -> tuple[str, list]:
        conditions = ["1=1"]
        params = []
        if status and status != "all":
            conditions.append("status = ?")
            params.append(status)
        if provider and provider != "all":
            conditions.append("provider = ?")
            params.append(provider)
        return " WHERE " + " AND ".join(conditions), params

    def all(
        self,
        limit: int | None = None,
        status: str | None = None,
        provider: str | None = None,
    ) -> list[dict]:
        """Return records (newest first) as plain dicts, filtered by status and provider."""
        where_sql, params = self._build_where(status, provider)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            query = f"""
                SELECT id, timestamp, provider, model, latency_ms,
                       prompt_tokens, completion_tokens, total_tokens,
                       cost_usd, status, error
                FROM telemetry
                {where_sql}
                ORDER BY rowid DESC
            """
            if limit is not None:
                query += " LIMIT ?"
                params.append(limit)

            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in reversed(rows)]

    def summary(self, status: str | None = None, provider: str | None = None) -> dict:
        """Aggregate view computed via SQL with status and provider filters."""
        where_sql, params = self._build_where(status, provider)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT
                    COUNT(*),
                    COALESCE(SUM(cost_usd), 0.0),
                    COALESCE(AVG(latency_ms), 0.0),
                    COALESCE(SUM(total_tokens), 0),
                    COALESCE(SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END), 0)
                FROM telemetry
                {where_sql}
            """, params)
            row = cursor.fetchone()
            count, total_cost, avg_lat, total_tok, error_cnt = row

            if count == 0:
                return {
                    "total_requests": 0,
                    "total_cost_usd": 0.0,
                    "avg_latency_ms": 0.0,
                    "total_tokens": 0,
                    "error_count": 0,
                }

            return {
                "total_requests": count,
                "total_cost_usd": round(total_cost, 6),
                "avg_latency_ms": round(avg_lat, 2),
                "total_tokens": total_tok,
                "error_count": error_cnt,
            }


class PostgresTelemetryStore:
    """PostgreSQL implementation of telemetry storage for shared horizontal multi-replica deployment."""

    def __init__(self, db_url: str) -> None:
        if not POSTGRES_AVAILABLE:
            raise ImportError("psycopg2 is required for PostgreSQL telemetry backend. Install via `pip install psycopg2-binary`.")
        self.db_url = db_url
        self._init_db()

    def _get_connection(self):
        return psycopg2.connect(self.db_url)

    def _init_db(self) -> None:
        """Create the telemetry table if it doesn't already exist in PostgreSQL."""
        with self._get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS telemetry (
                        id VARCHAR(64) PRIMARY KEY,
                        timestamp VARCHAR(64) NOT NULL,
                        provider VARCHAR(64) NOT NULL,
                        model VARCHAR(128) NOT NULL,
                        latency_ms DOUBLE PRECISION NOT NULL,
                        prompt_tokens INTEGER NOT NULL,
                        completion_tokens INTEGER NOT NULL,
                        total_tokens INTEGER NOT NULL,
                        cost_usd DOUBLE PRECISION NOT NULL,
                        status VARCHAR(32) NOT NULL,
                        error TEXT
                    );
                """)
            conn.commit()

    def record(self, entry: RequestTelemetry) -> None:
        """Save one telemetry row to PostgreSQL."""
        with self._get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO telemetry (
                        id, timestamp, provider, model, latency_ms,
                        prompt_tokens, completion_tokens, total_tokens,
                        cost_usd, status, error
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    entry.id, entry.timestamp, entry.provider, entry.model, entry.latency_ms,
                    entry.prompt_tokens, entry.completion_tokens, entry.total_tokens,
                    entry.cost_usd, entry.status, entry.error
                ))
            conn.commit()

    def _build_where(self, status: str | None, provider: str | None) -> tuple[str, list]:
        conditions = ["1=1"]
        params = []
        if status and status != "all":
            conditions.append("status = %s")
            params.append(status)
        if provider and provider != "all":
            conditions.append("provider = %s")
            params.append(provider)
        return " WHERE " + " AND ".join(conditions), params

    def all(
        self,
        limit: int | None = None,
        status: str | None = None,
        provider: str | None = None,
    ) -> list[dict]:
        """Return records (oldest first) as plain dicts, filtered by status and provider."""
        where_sql, params = self._build_where(status, provider)
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                query = f"""
                    SELECT id, timestamp, provider, model, latency_ms,
                           prompt_tokens, completion_tokens, total_tokens,
                           cost_usd, status, error
                    FROM telemetry
                    {where_sql}
                    ORDER BY timestamp DESC
                """
                if limit is not None:
                    query += " LIMIT %s"
                    params.append(limit)

                cursor.execute(query, params)
                rows = cursor.fetchall()
                return [dict(row) for row in reversed(rows)]

    def summary(self, status: str | None = None, provider: str | None = None) -> dict:
        """Aggregate view computed via SQL with status and provider filters."""
        where_sql, params = self._build_where(status, provider)
        with self._get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(f"""
                    SELECT
                        COUNT(*),
                        COALESCE(SUM(cost_usd), 0.0),
                        COALESCE(AVG(latency_ms), 0.0),
                        COALESCE(SUM(total_tokens), 0),
                        COALESCE(SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END), 0)
                    FROM telemetry
                    {where_sql}
                """, params)
                row = cursor.fetchone()
                count, total_cost, avg_lat, total_tok, error_cnt = row

                if count == 0:
                    return {
                        "total_requests": 0,
                        "total_cost_usd": 0.0,
                        "avg_latency_ms": 0.0,
                        "total_tokens": 0,
                        "error_count": 0,
                    }

                return {
                    "total_requests": count,
                    "total_cost_usd": round(total_cost, 6),
                    "avg_latency_ms": round(avg_lat, 2),
                    "total_tokens": total_tok,
                    "error_count": error_cnt,
                }


class TelemetryStore:
    """
    Unified TelemetryStore interface that delegates transparently to either
    SQLiteTelemetryStore or PostgresTelemetryStore based on environment variables.

    Defaults to SQLite for local development compatibility.
    """

    def __init__(self, db_path: str | None = None) -> None:
        backend = os.environ.get("TELEMETRY_BACKEND", "").lower()
        db_url = os.environ.get("DATABASE_URL", "")

        if backend == "postgres" or db_url.startswith("postgres"):
            if not db_url:
                db_url = "postgresql://llmops:llmops123@postgres:5432/llmops_telemetry"
            self.impl = PostgresTelemetryStore(db_url)
        else:
            self.impl = SQLiteTelemetryStore(db_path)

    def record(self, entry: RequestTelemetry) -> None:
        self.impl.record(entry)

    def all(
        self,
        limit: int | None = None,
        status: str | None = None,
        provider: str | None = None,
    ) -> list[dict]:
        return self.impl.all(limit=limit, status=status, provider=provider)

    def summary(self, status: str | None = None, provider: str | None = None) -> dict:
        return self.impl.summary(status=status, provider=provider)
