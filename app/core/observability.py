from __future__ import annotations

import logging

from app.core.config import Settings

logger = logging.getLogger(__name__)


def configure_observability(settings: Settings) -> None:
    if not settings.sentry_dsn:
        return
    try:
        import sentry_sdk
    except ImportError:
        logger.warning("SENTRY_DSN is set but sentry-sdk is not installed")
        return
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        release=settings.release_id,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
        max_breadcrumbs=50,
    )
