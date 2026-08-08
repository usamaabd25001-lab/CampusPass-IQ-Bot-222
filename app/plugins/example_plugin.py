from aiogram import Router
from aiogram.filters import Command

PLUGIN_NAME = "Example safe plugin"
PLUGIN_VERSION = "1.0.0"


def register(dispatcher, context):
    router = Router(name="example_plugin")

    @router.message(Command("plugin_test"))
    async def test(message):
        await message.answer("الإضافة تعمل ✅")

    dispatcher.include_router(router)
