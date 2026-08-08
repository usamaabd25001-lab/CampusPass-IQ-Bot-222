from __future__ import annotations

import importlib
import logging
from datetime import UTC, datetime

from aiogram import Dispatcher
from sqlalchemy import select

from app.core.context import AppContext
from app.db.models import PluginRecord

logger = logging.getLogger(__name__)


async def load_plugins(dispatcher: Dispatcher, context: AppContext) -> None:
    for module_name in context.settings.plugin_modules:
        try:
            module = importlib.import_module(module_name)
            register = getattr(module, "register", None)
            if not callable(register):
                raise RuntimeError("plugin must expose register(dispatcher, context)")
            result = register(dispatcher, context)
            if hasattr(result, "__await__"):
                await result
            async with context.database.session() as session:
                rec = await session.scalar(
                    select(PluginRecord).where(PluginRecord.module_name == module_name)
                )
                if not rec:
                    rec = PluginRecord(
                        module_name=module_name,
                        display_name=getattr(module, "PLUGIN_NAME", module_name),
                    )
                    session.add(rec)
                rec.version = str(getattr(module, "PLUGIN_VERSION", ""))
                rec.is_enabled = True
                rec.last_error = None
                rec.loaded_at = datetime.now(UTC)
                await session.commit()
            logger.info("Loaded plugin %s", module_name)
        except Exception as exc:
            logger.exception("Failed plugin %s", module_name)
            async with context.database.session() as session:
                rec = await session.scalar(
                    select(PluginRecord).where(PluginRecord.module_name == module_name)
                )
                if not rec:
                    rec = PluginRecord(module_name=module_name)
                    session.add(rec)
                rec.last_error = str(exc)[:2000]
                rec.is_enabled = False
                await session.commit()
