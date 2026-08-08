from __future__ import annotations

import asyncio
import base64
import logging
import ssl
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings
from app.core.db_url import database_hostname, safe_database_label
from app.db.models import Base

logger = logging.getLogger(__name__)


class Database:
    """Async SQLAlchemy database layer optimized for Supabase/PostgreSQL.

    The same class remains SQLite-compatible for local tests. Production uses a
    bounded async pool with pre-ping, recycling, rollback-on-return and strict
    connection/statement timeouts. Supabase/Supavisor pooler URLs are detected
    automatically and asyncpg prepared-statement caching is disabled.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        url: URL = make_url(settings.database_url)
        is_sqlite = url.drivername.startswith("sqlite")
        hostname = database_hostname(settings.database_url)
        self.is_supabase = "supabase" in hostname or "supavisor" in hostname
        self.is_transaction_pooler = self.is_supabase and url.port == 6543
        self.is_railway_internal = hostname.endswith(".railway.internal")

        connect_args: dict[str, object] = {}
        engine_kwargs: dict[str, object] = {
            # A pre-ping costs one extra SQL round-trip on every connection checkout.
            # Railway's private network plus pool recycling is faster without it;
            # operators can turn it back on for unstable external providers.
            "pool_pre_ping": bool(settings.db_pool_pre_ping),
        }

        if is_sqlite:
            connect_args["check_same_thread"] = False
        else:
            # Railway private PostgreSQL stays inside the project network and
            # does not need TLS. Avoiding an unnecessary SSL negotiation lowers
            # connection setup latency. External providers keep the configured
            # SSL policy.
            ssl_value = False if self.is_railway_internal else self._build_ssl_argument(settings)
            if ssl_value is not None:
                connect_args["ssl"] = ssl_value

            connect_args["timeout"] = settings.db_connect_timeout_seconds
            connect_args["command_timeout"] = max(
                1.0, settings.db_statement_timeout_ms / 1_000
            )
            connect_args["server_settings"] = {
                "application_name": settings.db_application_name,
                "statement_timeout": str(settings.db_statement_timeout_ms),
                "idle_in_transaction_session_timeout": str(
                    max(settings.db_statement_timeout_ms * 2, 60_000)
                ),
            }

            prepared_cache_size = settings.db_prepared_statement_cache_size
            if self.is_transaction_pooler:
                # Supabase transaction pooling (Supavisor, usually port 6543)
                # must not reuse asyncpg prepared statements across transactions.
                prepared_cache_size = 0
                connect_args["statement_cache_size"] = 0
                logger.info("Supabase transaction pooler mode enabled; statement cache disabled")
            if prepared_cache_size >= 0:
                url = url.update_query_dict(
                    {"prepared_statement_cache_size": str(prepared_cache_size)}
                )

            if self.is_transaction_pooler:
                engine_kwargs["pool_pre_ping"] = False
                # Supavisor transaction mode is already a connection pool. A local
                # SQLAlchemy pool would double-pool connections and can retain a
                # server connection that no longer owns its prepared statements.
                engine_kwargs["poolclass"] = NullPool
            else:
                engine_kwargs.update(
                    {
                        "pool_size": settings.db_pool_size,
                        "max_overflow": settings.db_max_overflow,
                        "pool_timeout": settings.db_pool_timeout_seconds,
                        "pool_recycle": settings.db_pool_recycle_seconds,
                        "pool_use_lifo": True,
                        "pool_reset_on_return": "rollback",
                    }
                )

        self.engine: AsyncEngine = create_async_engine(
            url,
            connect_args=connect_args,
            **engine_kwargs,
        )
        self.session_factory = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
            autoflush=False,
            class_=AsyncSession,
        )

        if self.is_supabase and not self.is_transaction_pooler:
            logger.warning(
                "Supabase direct database URL detected. For burst concurrency, prefer the "
                "Supabase transaction pooler URL (normally port 6543)."
            )

    @staticmethod
    def _build_ssl_argument(settings: Settings) -> ssl.SSLContext | bool | None:
        mode = settings.db_ssl_mode
        if mode == "disable":
            return False
        if mode == "prefer":
            return None
        if mode == "require":
            # Encrypt while remaining compatible with managed providers whose
            # copied URL does not include a downloadable CA certificate.
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            return context

        # verify-full: encryption plus certificate and hostname verification.
        context = ssl.create_default_context()
        if settings.db_ca_cert_b64:
            pem = base64.b64decode(settings.db_ca_cert_b64, validate=True).decode("utf-8")
            context.load_verify_locations(cadata=pem)
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        return context

    async def wait_until_ready(self) -> None:
        last_error: Exception | None = None
        for attempt in range(1, self.settings.db_startup_retries + 1):
            try:
                async with self.engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
                logger.info(
                    "External database ready: %s%s",
                    safe_database_label(self.settings.database_url),
                    " (Supabase pooler)" if self.is_transaction_pooler else "",
                )
                return
            except Exception as exc:  # pragma: no cover - provider/network dependent
                last_error = exc
                if attempt >= self.settings.db_startup_retries:
                    break
                delay = min(self.settings.db_startup_retry_seconds * attempt, 60.0)
                logger.warning(
                    "Database unavailable (attempt %s/%s); retrying in %.1fs: %s",
                    attempt,
                    self.settings.db_startup_retries,
                    delay,
                    type(exc).__name__,
                )
                await asyncio.sleep(delay)
        raise RuntimeError(
            "External PostgreSQL did not become ready after startup retries"
        ) from last_error

    async def create_tables(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.session_factory() as session:
            yield session

    async def try_transaction_lock(self, session: AsyncSession, lock_id: int) -> bool:
        """Acquire a PostgreSQL transaction advisory lock for one scheduler cycle."""
        if self.engine.dialect.name != "postgresql":
            return True
        return bool(
            await session.scalar(
                text("SELECT pg_try_advisory_xact_lock(:lock_id)"),
                {"lock_id": int(lock_id)},
            )
        )

    async def close(self) -> None:
        await self.engine.dispose()
