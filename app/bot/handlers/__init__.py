from aiogram import Router

from app.bot.handlers import (
    admin,
    catalog,
    friends_warranty,
    menu,
    navigation,
    orders,
    owner_commerce,
    payments,
    provider,
    provider_operations,
    provider_catalog,
    provider_coupons,
    start,
    student_fulfillment,
    subscriptions,
    support,
)


def build_router() -> Router:
    router = Router(name="root")
    router.include_router(navigation.router)
    router.include_router(start.router)
    router.include_router(catalog.router)
    router.include_router(friends_warranty.router)
    router.include_router(owner_commerce.router)
    router.include_router(payments.router)
    router.include_router(student_fulfillment.router)
    router.include_router(orders.router)
    router.include_router(subscriptions.router)
    router.include_router(support.router)
    router.include_router(provider.router)
    router.include_router(provider_operations.router)
    router.include_router(provider_catalog.router)
    router.include_router(provider_coupons.router)
    router.include_router(admin.router)
    router.include_router(menu.router)  # Generic text menu must be last.
    return router
