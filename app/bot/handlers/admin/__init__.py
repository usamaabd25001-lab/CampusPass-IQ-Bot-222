from aiogram import Router

from app.bot.handlers.admin import (
    catalog,
    core,
    customization,
    finance,
    operations,
    owner_commerce,
    plans,
    subscriptions,
    v5,
    users_security,
)

router = Router(name="admin")
router.include_router(core.router)
router.include_router(catalog.router)
router.include_router(operations.router)
router.include_router(owner_commerce.router)
router.include_router(finance.router)
router.include_router(subscriptions.router)
router.include_router(plans.router)
router.include_router(customization.router)
router.include_router(v5.router)
router.include_router(users_security.router)
