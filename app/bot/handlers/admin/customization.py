from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.admin.common import admin_actor, admin_back, require_admin
from app.bot.keyboards.inline import (
    feature_flags_keyboard,
    menu_button_editor_keyboard,
    menu_buttons_keyboard,
    menu_manager_keyboard,
    menu_move_keyboard,
    menu_surface_keyboard,
    style_keyboard,
)
from app.bot.states import (
    AdminMediaStates,
    AdminMenuPositionStates,
    AdminMenuTextStates,
    AdminMessageTemplateStates,
    AdminSettingStates,
    AdminStartMessageStates,
)
from app.bot.ui import edit_or_send, callback_notice
from app.core.config import Settings
from app.db.models import FeatureFlag, MediaAsset, PluginRecord, SystemSetting
from app.services.container import Services
from app.services.templates import validate_telegram_html

router = Router(name="admin_customization")


async def _menu_item_from_token(
    session: AsyncSession, services: Services, token: str
):
    return await services.menus.resolve_button_token(session, token)


async def _render_menu_item(message: Message, item) -> None:
    surface_names = {
        "reply": "كيبورد سفلي",
        "inline": "داخل الرسالة",
        "both": "في المكانين",
        "hidden": "مخفي",
    }
    await edit_or_send(
        message,
        f"🎛 <b>{item.text}</b>\n\n"
        f"المعرّف الثابت: <code>{item.key}</code>\n"
        f"الوظيفة: <code>{item.action}</code>\n"
        f"النوع: {surface_names.get(item.surface, item.surface)}\n"
        f"اللون: <code>{item.style}</code>\n"
        f"المكان: قابل للتحريك من الأسهم 🧭\n"
        f"الحالة: {'مفعل ✅' if item.is_enabled else 'متوقف ❌'}\n\n"
        "تغيير الاسم أو المكان أو اللون لا يغيّر الوظيفة البرمجية للزر.",
        reply_markup=menu_button_editor_keyboard(item),
    )


@router.callback_query(F.data == "admin:menu_manager")
async def menu_manager(
    callback: CallbackQuery, session: AsyncSession, settings: Settings, services: Services
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    buttons = await services.menus.list_buttons(session)
    await edit_or_send(callback.message, 
        "🎛 <b>إدارة واجهة الأزرار</b>\n\n"
        "يمكن تعديل زر واحد دون تغيير وظيفته أو التأثير على بقية الأزرار. "
        "النوع يحدد مكان ظهوره: كيبورد سفلي، داخل الرسالة، في المكانين، أو مخفي.",
        reply_markup=menu_manager_keyboard(buttons),
    )


@router.callback_query(F.data.startswith("admin:menu_button:"))
async def menu_button_details(
    callback: CallbackQuery, session: AsyncSession, settings: Settings, services: Services
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    token = (callback.data or "").split(":", 2)[2]
    item = await _menu_item_from_token(session, services, token)
    if not item:
        await edit_or_send(callback.message, "الزر غير موجود.")
        return
    await _render_menu_item(callback.message, item)


@router.callback_query(F.data.startswith("admin:menu_edit_text:"))
async def menu_manager_text_start(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, settings: Settings, services: Services
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    token = (callback.data or "").split(":", 2)[2]
    item = await _menu_item_from_token(session, services, token)
    if not item:
        await edit_or_send(callback.message, "الزر غير موجود.")
        return
    await state.clear()
    await state.update_data(menu_text_key=item.key)
    await state.set_state(AdminMenuTextStates.text)
    await edit_or_send(callback.message, "اكتب الاسم الجديد للزر. الوظيفة ستبقى نفسها، ويمكن إضافة إيموجي.")


@router.callback_query(F.data.startswith("admin:menu_edit_style:"))
async def menu_manager_style_start(
    callback: CallbackQuery, session: AsyncSession, settings: Settings, services: Services
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    token = (callback.data or "").split(":", 2)[2]
    item = await _menu_item_from_token(session, services, token)
    if not item:
        await edit_or_send(callback.message, "الزر غير موجود.")
        return
    await edit_or_send(callback.message, "اختر لون الزر:", reply_markup=style_keyboard(item.id))


@router.callback_query(F.data.startswith("admin:menu_edit_surface:"))
async def menu_manager_surface_start(
    callback: CallbackQuery, session: AsyncSession, settings: Settings, services: Services
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    token = (callback.data or "").split(":", 2)[2]
    item = await _menu_item_from_token(session, services, token)
    if not item:
        await edit_or_send(callback.message, "الزر غير موجود.")
        return
    await edit_or_send(callback.message, "اختر نوع ومكان ظهور الزر:", reply_markup=menu_surface_keyboard(item.id))


@router.callback_query(F.data.startswith("admin:setsurface:"))
async def menu_manager_surface_set(
    callback: CallbackQuery, session: AsyncSession, settings: Settings, services: Services
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    _, _, token, surface = (callback.data or "").split(":", 3)
    item = await _menu_item_from_token(session, services, token)
    if not item:
        await edit_or_send(callback.message, "الزر غير موجود.")
        return
    ok = await services.menus.set_surface(session, item.key, surface)
    actor = await admin_actor(session, services, callback)
    if ok:
        await services.audit.log(session, actor, "menu.surface.updated", "menu_button", item.key, {"surface": surface})
    refreshed = await services.menus.get_button(session, item.key)
    if ok and refreshed:
        await _render_menu_item(callback.message, refreshed)
    else:
        await edit_or_send(callback.message, "تعذر تغيير نوع الزر.")


@router.callback_query(F.data.startswith("admin:menu_move_panel:"))
async def menu_move_panel(
    callback: CallbackQuery, session: AsyncSession, settings: Settings, services: Services
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    token = (callback.data or "").split(":", 2)[2]
    item = await _menu_item_from_token(session, services, token)
    if not item:
        await edit_or_send(callback.message, "الزر غير موجود.")
        return
    await edit_or_send(callback.message, "🧭 حرّك الزر بصريًا. لا تحتاج أرقام صفوف أو أعمدة.", reply_markup=menu_move_keyboard(item.id))


@router.callback_query(F.data.regexp(r"^admin:menu_move:[^:]+:(left|right|up|down)$"))
async def menu_move_apply(
    callback: CallbackQuery, session: AsyncSession, settings: Settings, services: Services
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    _, _, token, direction = (callback.data or "").split(":", 3)
    item = await _menu_item_from_token(session, services, token)
    if not item:
        await edit_or_send(callback.message, "الزر غير موجود.")
        return
    ok = await services.menus.move_button(session, item.key, direction)
    actor = await admin_actor(session, services, callback)
    if ok:
        await services.audit.log(session, actor, "menu.position.moved", "menu_button", item.key, {"direction": direction})
    refreshed = await services.menus.get_button(session, item.key)
    await edit_or_send(
        callback.message,
        "تم التحريك ✅" if ok else "لا يمكن التحريك أكثر بهذا الاتجاه.",
        reply_markup=menu_move_keyboard(refreshed.id if refreshed else item.id),
    )


@router.callback_query(F.data.startswith("admin:menu_edit_position:"))
async def menu_manager_position_start(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, settings: Settings, services: Services
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    token = (callback.data or "").split(":", 2)[2]
    item = await _menu_item_from_token(session, services, token)
    if not item:
        await edit_or_send(callback.message, "الزر غير موجود.")
        return
    await state.clear()
    await state.update_data(menu_position_key=item.key)
    await state.set_state(AdminMenuPositionStates.value)
    await edit_or_send(callback.message, "اكتب رقم الصف ثم فاصلة ثم ترتيب الزر داخل الصف.\nمثال: <code>2,1</code>")


@router.message(AdminMenuPositionStates.value)
async def menu_manager_position_finish(
    message: Message, state: FSMContext, session: AsyncSession, settings: Settings, services: Services
) -> None:
    if not await require_admin(message, settings):
        return
    raw = (message.text or "").replace("؛", ",").replace(" ", "")
    try:
        row_number, position = (int(part) for part in raw.split(",", 1))
    except (ValueError, TypeError):
        await message.answer("الصيغة غير صحيحة. اكتب مثلًا: <code>2,1</code>")
        return
    data = await state.get_data()
    key = str(data.get("menu_position_key", ""))
    ok = await services.menus.set_position(session, key, row_number, position)
    actor = await admin_actor(session, services, message)
    if ok:
        await services.audit.log(session, actor, "menu.position.updated", "menu_button", key, {"row": row_number, "position": position})
    await state.clear()
    await message.answer("تم تغيير مكان الزر ✅" if ok else "المكان غير صالح.", reply_markup=admin_back())


@router.callback_query(F.data.startswith("admin:menu_toggle:"))
async def menu_manager_toggle(
    callback: CallbackQuery, session: AsyncSession, settings: Settings, services: Services
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    token = (callback.data or "").split(":", 2)[2]
    item = await _menu_item_from_token(session, services, token)
    if not item:
        await edit_or_send(callback.message, "الزر غير موجود.")
        return
    enabled = not item.is_enabled
    ok = await services.menus.set_enabled(session, item.key, enabled)
    actor = await admin_actor(session, services, callback)
    if ok:
        await services.audit.log(session, actor, "menu.enabled.updated", "menu_button", item.key, {"enabled": enabled})
    refreshed = await services.menus.get_button(session, item.key)
    if ok and refreshed:
        await _render_menu_item(callback.message, refreshed)
    else:
        await edit_or_send(callback.message, "تعذر تحديث حالة الزر.")


@router.callback_query(F.data.startswith("admin:menu_delete_prompt:"))
async def menu_delete_prompt(
    callback: CallbackQuery, session: AsyncSession, settings: Settings, services: Services
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    token = (callback.data or "").split(":", 2)[2]
    item = await _menu_item_from_token(session, services, token)
    if not item:
        await edit_or_send(callback.message, "الزر غير موجود.")
        return
    await edit_or_send(
        callback.message,
        "⚠️ حذف الزر المخصص نهائيًا؟ لا يمكن حذف زر يحتوي أزرارًا فرعية قبل حذفها أو نقلها.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑 نعم، حذف نهائي", callback_data=f"admin:menu_delete_confirm:{item.id}", style="danger")],
            [InlineKeyboardButton(text="↩️ تراجع", callback_data=f"admin:menu_button:{item.id}")],
        ]),
    )


@router.callback_query(F.data.startswith("admin:menu_delete_confirm:"))
async def menu_delete_confirm(
    callback: CallbackQuery, session: AsyncSession, settings: Settings, services: Services
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    token = (callback.data or "").split(":", 2)[2]
    item = await _menu_item_from_token(session, services, token)
    if not item:
        await edit_or_send(callback.message, "الزر غير موجود.")
        return
    actor = await admin_actor(session, services, callback)
    try:
        deleted = await services.menus.delete_custom_button(session, item.key)
    except ValueError as exc:
        await edit_or_send(callback.message, str(exc))
        return
    if deleted:
        await services.audit.log(session, actor, "menu.custom.deleted", "menu_button", item.key, {})
    buttons = await services.menus.list_buttons(session)
    await edit_or_send(
        callback.message,
        "تم حذف الزر المخصص ✅" if deleted else "هذا زر نظام ولا يمكن حذفه؛ يمكن إخفاؤه.",
        reply_markup=menu_manager_keyboard(buttons),
    )


@router.callback_query(F.data.startswith("admin:menu_preset:"))
async def menu_manager_preset(
    callback: CallbackQuery, session: AsyncSession, settings: Settings, services: Services
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    surface = (callback.data or "").split(":", 2)[2]
    changed = await services.menus.set_all_surfaces(session, surface)
    actor = await admin_actor(session, services, callback)
    if changed:
        await services.audit.log(session, actor, "menu.preset.updated", "menu", "all", {"surface": surface, "buttons": changed})
    buttons = await services.menus.list_buttons(session)
    await edit_or_send(callback.message, f"تم توحيد {changed} زرًا ✅", reply_markup=menu_manager_keyboard(buttons))


@router.callback_query(F.data == "admin:menu_preview")
async def menu_manager_preview(
    callback: CallbackQuery, session: AsyncSession, settings: Settings, services: Services
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    user = await services.users.get_or_create(
        session,
        callback.from_user.id,
        callback.from_user.username,
        callback.from_user.full_name or "Telegram User",
    )
    from app.bot.handlers.start import send_home
    await send_home(callback.message, session, services, user, in_place=True)


@router.callback_query(F.data == "admin:menu_colors")
async def menu_colors(
    callback: CallbackQuery, session: AsyncSession, settings: Settings, services: Services
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    buttons = await services.menus.list_buttons(session)
    await edit_or_send(callback.message, "🎨 اختر الزر الذي تريد تغيير لونه:", reply_markup=menu_buttons_keyboard(buttons, "color"))


@router.callback_query(F.data.startswith("admin:color:"))
async def menu_color_pick(
    callback: CallbackQuery, session: AsyncSession, settings: Settings, services: Services
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    token = (callback.data or "").split(":", 2)[2]
    item = await _menu_item_from_token(session, services, token)
    if not item:
        await edit_or_send(callback.message, "الزر غير موجود.")
        return
    await edit_or_send(callback.message, "اختر اللون:", reply_markup=style_keyboard(item.id))


@router.callback_query(F.data.startswith("admin:setstyle:"))
async def menu_color_set(
    callback: CallbackQuery, session: AsyncSession, settings: Settings, services: Services
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    _, _, token, style = (callback.data or "").split(":", 3)
    item = await _menu_item_from_token(session, services, token)
    if not item:
        await edit_or_send(callback.message, "الزر غير موجود.")
        return
    ok = await services.menus.set_style(session, item.key, style)
    actor = await admin_actor(session, services, callback)
    if ok:
        await services.audit.log(session, actor, "menu.style.updated", "menu_button", item.key, {"style": style})
    refreshed = await services.menus.get_button(session, item.key)
    if ok and refreshed:
        await _render_menu_item(callback.message, refreshed)
    else:
        await edit_or_send(callback.message, "تعذر تغيير اللون.")


@router.callback_query(F.data == "admin:menu_text")
async def menu_texts(
    callback: CallbackQuery, session: AsyncSession, settings: Settings, services: Services
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    buttons = await services.menus.list_buttons(session)
    await edit_or_send(callback.message, "✏️ اختر الزر لتغيير اسمه:", reply_markup=menu_buttons_keyboard(buttons, "text"))


@router.callback_query(F.data.startswith("admin:text:"))
async def menu_text_start(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, settings: Settings, services: Services
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    token = (callback.data or "").split(":", 2)[2]
    item = await _menu_item_from_token(session, services, token)
    if not item:
        await edit_or_send(callback.message, "الزر غير موجود.")
        return
    await state.clear()
    await state.update_data(menu_text_key=item.key)
    await state.set_state(AdminMenuTextStates.text)
    await edit_or_send(callback.message, "اكتب الاسم الجديد للزر، ويمكن أن يتضمن إيموجي:")


@router.message(AdminMenuTextStates.text)
async def menu_text_finish(
    message: Message, state: FSMContext, session: AsyncSession, settings: Settings, services: Services
) -> None:
    if not await require_admin(message, settings):
        return
    data = await state.get_data()
    value = " ".join((message.text or "").split())
    key = str(data.get("menu_text_key", ""))
    ok = await services.menus.set_text(session, key, value)
    actor = await admin_actor(session, services, message)
    if ok:
        await services.audit.log(session, actor, "menu.text.updated", "menu_button", key, {"text": value})
    await state.clear()
    await message.answer("تم تغيير نص الزر ✅" if ok else "النص غير صالح أو مستخدم في زر آخر.", reply_markup=admin_back())


@router.callback_query(F.data == "admin:features")
async def features(callback: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    flags = list((await session.scalars(select(FeatureFlag).order_by(FeatureFlag.key))).all())
    await edit_or_send(callback.message, 
        "🧩 <b>الميزات</b>\n\n"
        "تشغيل ميزة من هنا لا يتجاوز متطلبات Railway Variables. مثال: Gemini يحتاج مفتاحًا أيضًا.",
        reply_markup=feature_flags_keyboard(flags),
    )


@router.callback_query(F.data.startswith("admin:flag:"))
async def feature_toggle(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings):
        return
    token = (callback.data or "").split(":", 2)[2]
    row = await session.get(FeatureFlag, int(token)) if token.isdecimal() else None
    key = row.key if row else token
    actor = await admin_actor(session, services, callback)
    flag = await services.features.toggle(session, key, actor.id if actor else None)
    if flag:
        await services.audit.log(
            session, actor, "feature.toggled", "feature", key, {"enabled": flag.is_enabled}
        )
    await callback_notice(callback, 
        f"{key}: {'مفعل' if flag and flag.is_enabled else 'متوقف'}", show_alert=True
    )


@router.callback_query(F.data == "admin:plugins")
async def plugins(callback: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    records = list(
        (await session.scalars(select(PluginRecord).order_by(PluginRecord.module_name))).all()
    )
    rows = []
    for record in records:
        icon = "✅" if record.is_enabled else "❌"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{icon} {record.display_name or record.module_name}",
                    callback_data=f"admin:plugin_toggle:{record.id}",
                    style="primary",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="↩️ الميزات", callback_data="admin:features")])
    await edit_or_send(callback.message, 
        "🧩 <b>الإضافات البرمجية الآمنة</b>\n\n"
        "تُضاف الإضافة داخل GitHub كموديول مستقل ثم يضاف اسمها إلى PLUGIN_MODULES. "
        "لا يسمح برفع Python وتشغيله من تيليغرام لأن ذلك يمنح منفذًا خطيرًا لتنفيذ أوامر على السيرفر.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.startswith("admin:plugin_toggle:"))
async def plugin_toggle(callback: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    await callback.answer()
    if not await require_admin(callback, settings):
        return
    record = await session.get(PluginRecord, int(callback.data.split(":")[2]))
    if record:
        record.is_enabled = not record.is_enabled
    await callback_notice(callback, "تم تحديث الحالة. أعد Restart/Deploy لتطبيقها.", show_alert=True)


@router.callback_query(F.data == "admin:media")
async def media_home(callback: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    assets = list(
        (
            await session.scalars(
                select(MediaAsset).order_by(MediaAsset.created_at.desc()).limit(20)
            )
        ).all()
    )
    lines = ["📁 <b>مكتبة الملفات</b>"]
    for asset in assets:
        lines.append(f"\n• ID {asset.id} — {asset.name} — {asset.file_type}")
    await edit_or_send(callback.message, 
        "".join(lines) if assets else "المكتبة فارغة.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="➕ رفع ملف", callback_data="admin:media_upload", style="success"
                    )
                ],
                [InlineKeyboardButton(text="↩️ لوحة الإدارة", callback_data="admin:home")],
            ]
        ),
    )


@router.callback_query(F.data == "admin:media_upload")
async def media_upload_start(
    callback: CallbackQuery, state: FSMContext, settings: Settings
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    await state.clear()
    await state.set_state(AdminMediaStates.name)
    await edit_or_send(callback.message, "اكتب اسم الملف داخل المكتبة:")


@router.message(AdminMediaStates.name)
async def media_name(message: Message, state: FSMContext) -> None:
    name = " ".join((message.text or "").split())
    if len(name) < 2:
        return await message.answer("اكتب اسمًا واضحًا.")
    await state.update_data(media_name=name[:180])
    await state.set_state(AdminMediaStates.file)
    await message.answer("أرسل صورة أو فيديو أو PDF أو HTML أو مستند. الملفات التنفيذية محظورة.")


@router.message(AdminMediaStates.file)
async def media_save(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    if not await require_admin(message, settings):
        return
    file_id = file_type = mime_type = None
    size = None
    filename = None
    if message.photo:
        item = message.photo[-1]
        file_id = item.file_id
        file_type = "photo"
        mime_type = "image/jpeg"
        size = item.file_size
    elif message.video:
        item = message.video
        file_id = item.file_id
        file_type = "video"
        mime_type = item.mime_type
        size = item.file_size
        filename = item.file_name
    elif message.document:
        item = message.document
        file_id = item.file_id
        file_type = "document"
        mime_type = item.mime_type
        size = item.file_size
        filename = item.file_name
    if not file_id:
        return await message.answer("أرسل ملفًا مدعومًا.")
    ext = (filename or "").lower().rsplit(".", 1)[-1] if "." in (filename or "") else ""
    if ext in {"py", "pyc", "pyo", "sh", "exe", "bat", "cmd", "ps1", "jar", "dll", "so"}:
        return await message.answer("الملفات التنفيذية والبرمجية غير مسموحة داخل لوحة تيليغرام.")
    if size and size > 20 * 1024 * 1024:
        return await message.answer("الحد الأعلى 20MB.")
    data = await state.get_data()
    actor = await admin_actor(session, services, message)
    asset = MediaAsset(
        name=data["media_name"],
        telegram_file_id=file_id,
        file_type=file_type,
        mime_type=mime_type,
        size_bytes=size,
        uploaded_by_user_id=actor.id if actor else None,
    )
    session.add(asset)
    await session.flush()
    await state.clear()
    await message.answer(
        f"تم حفظ الملف ID <code>{asset.id}</code> ✅\nيمكن استخدام Telegram file_id داخل العروض والشعارات دون تخزين الملف على السيرفر.",
        reply_markup=admin_back(),
    )


@router.callback_query(F.data.startswith("admin:setting:"))
async def setting_start(callback: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    key = callback.data.split(":", 2)[2]
    await state.clear()
    await state.update_data(setting_key=key)
    await state.set_state(AdminSettingStates.value)
    await edit_or_send(callback.message, f"اكتب القيمة الجديدة للإعداد <code>{key}</code>:")


@router.message(AdminSettingStates.value)
async def setting_finish(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    if not await require_admin(message, settings):
        return
    data = await state.get_data()
    key = str(data["setting_key"])
    value = (message.text or "").strip()
    if key == "service_fee_iqd":
        try:
            numeric = int(value)
        except ValueError:
            return await message.answer("اكتب رقمًا صحيحًا.")
        if not 0 <= numeric <= 1_000_000:
            return await message.answer("القيمة خارج النطاق.")
    row = await session.scalar(select(SystemSetting).where(SystemSetting.key == key))
    actor = await admin_actor(session, services, message)
    if not row:
        row = SystemSetting(key=key, value=value, updated_by_user_id=actor.id if actor else None)
        session.add(row)
    else:
        row.value = value
        row.updated_by_user_id = actor.id if actor else None
    await state.clear()
    await message.answer("تم حفظ الإعداد ✅", reply_markup=admin_back())


async def _render_start_message_admin(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    current = await services.templates.welcome_text(session, settings.welcome_text)
    await edit_or_send(
        message,
        "✍️ <b>رسالة /start</b>\n\n"
        "هذا النص يُقرأ من cache سريع، ويُحدّث فور الحفظ دون استعلام جديد مع كل /start.\n\n"
        f"<b>النص الحالي:</b>\n{current}",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✏️ تعديل", callback_data="admin:start_message_edit", style="primary"
                    ),
                    InlineKeyboardButton(
                        text="↩️ استعادة الافتراضي",
                        callback_data="admin:start_message_reset",
                        style="danger",
                    ),
                ],
                [InlineKeyboardButton(text="↩️ لوحة الإدارة", callback_data="admin:home")],
            ]
        ),
    )


@router.callback_query(F.data == "admin:start_message")
async def start_message_admin(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    await state.clear()
    await _render_start_message_admin(callback.message, session, settings, services)


@router.callback_query(F.data == "admin:start_message_edit")
async def start_message_edit_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    current = await services.templates.welcome_text(session, settings.welcome_text)
    await state.clear()
    await state.set_state(AdminStartMessageStates.body)
    await state.update_data(navigation_parent="admin")
    await edit_or_send(
        callback.message,
        "أرسل رسالة /start الجديدة كاملة.\n"
        "الحد: 3–4000 حرف، وHTML يجب أن يكون متوافقًا مع تيليجرام.\n\n"
        f"النص الحالي:\n{current}",
        back_callback="nav:back:admin",
    )


@router.message(AdminStartMessageStates.body)
async def start_message_preview(
    message: Message,
    state: FSMContext,
    settings: Settings,
) -> None:
    if not await require_admin(message, settings):
        return
    body = (message.text or "").strip()
    if not 3 <= len(body) <= 4000:
        await message.answer("النص يجب أن يكون بين 3 و4000 حرف.")
        return
    try:
        validate_telegram_html(body)
    except ValueError as exc:
        await message.answer(f"HTML غير صالح: {exc}")
        return
    await state.update_data(start_message_candidate=body)
    await state.set_state(AdminStartMessageStates.confirm)
    await message.answer(
        "🔎 <b>معاينة رسالة /start</b>\n\n" + body,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ تأكيد الحفظ",
                        callback_data="admin:start_message_confirm",
                        style="success",
                    ),
                    InlineKeyboardButton(
                        text="❌ إلغاء",
                        callback_data="admin:start_message_cancel",
                        style="danger",
                    ),
                ]
            ]
        ),
    )


@router.callback_query(F.data == "admin:start_message_confirm")
async def start_message_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    if await state.get_state() != AdminStartMessageStates.confirm.state:
        await callback_notice(callback, "المعاينة قديمة؛ أعد التعديل", show_alert=True)
        return
    body = str((await state.get_data()).get("start_message_candidate") or "").strip()
    try:
        validate_telegram_html(body)
    except ValueError as exc:
        await edit_or_send(callback.message, f"HTML غير صالح: {exc}")
        return
    actor = await admin_actor(session, services, callback)
    row = await services.templates.update(session, "start.welcome", body, actor, "ar")
    await services.audit.log(
        session, actor, "start_message.updated", "message_template", str(row.id), {}
    )
    await state.clear()
    await edit_or_send(
        callback.message,
        "تم تحديث رسالة /start وcache فورًا ✅\n\n" + body,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="↩️ إعداد الرسالة", callback_data="admin:start_message")]]
        ),
    )


@router.callback_query(F.data == "admin:start_message_cancel")
async def start_message_cancel(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    await state.clear()
    await _render_start_message_admin(callback.message, session, settings, services)


@router.callback_query(F.data == "admin:start_message_reset")
async def start_message_reset_prompt(
    callback: CallbackQuery, settings: Settings
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    await edit_or_send(
        callback.message,
        "هل تريد استعادة WELCOME_TEXT الافتراضي؟",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ استعادة",
                        callback_data="admin:start_message_reset_apply",
                        style="success",
                    ),
                    InlineKeyboardButton(
                        text="❌ إلغاء", callback_data="admin:start_message", style="danger"
                    ),
                ]
            ]
        ),
    )


@router.callback_query(F.data == "admin:start_message_reset_apply")
async def start_message_reset_apply(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    actor = await admin_actor(session, services, callback)
    row = await services.templates.reset_welcome(session, settings.welcome_text, actor)
    await services.audit.log(
        session, actor, "start_message.reset", "message_template", str(row.id), {}
    )
    await state.clear()
    await _render_start_message_admin(callback.message, session, settings, services)


@router.callback_query(F.data == "admin:message_templates")
async def message_templates_list(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    await callback_notice(callback, "جاري تحميل قوالب الرسائل...")
    templates = await services.templates.list(session)
    rows = [
        [
            InlineKeyboardButton(
                text=f"📝 {item.title or item.template_key}",
                callback_data=f"admin:template:{item.id}",
                style="primary",
            )
        ]
        for item in templates
    ]
    rows.append([InlineKeyboardButton(text="↩️ لوحة الإدارة", callback_data="admin:home")])
    await edit_or_send(callback.message, 
        "📝 <b>قوالب الرسائل</b>\n\n"
        "يمكن تغيير الرسائل المتكررة دون تعديل Python. لا تحذف المتغيرات المكتوبة بين "
        "الأقواس مثل <code>{order_id}</code>.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.regexp(r"^admin:template:\d+$"))
async def message_template_details(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    from app.db.models import MessageTemplate

    row = await session.get(MessageTemplate, int((callback.data or "").split(":")[2]))
    if not row:
        await edit_or_send(callback.message, "القالب غير موجود.")
        return
    variables = "، ".join(f"<code>{{{name}}}</code>" for name in row.variables) or "لا توجد"
    await edit_or_send(callback.message, 
        f"📝 <b>{row.title or row.template_key}</b>\n\n"
        f"المعرف: <code>{row.template_key}</code>\n"
        f"المتغيرات: {variables}\n\n"
        f"النص الحالي:\n{row.body}",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✏️ تعديل النص",
                        callback_data=f"admin:template_edit:{row.id}",
                        style="primary",
                    )
                ],
                [InlineKeyboardButton(text="↩️ القوالب", callback_data="admin:message_templates")],
            ]
        ),
    )


@router.callback_query(F.data.startswith("admin:template_edit:"))
async def message_template_edit_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    from app.bot.states import AdminMessageTemplateStates
    from app.db.models import MessageTemplate

    template_id = int((callback.data or "").split(":")[2])
    row = await session.get(MessageTemplate, template_id)
    if not row:
        await edit_or_send(callback.message, "القالب غير موجود.")
        return
    await state.clear()
    await state.update_data(message_template_id=template_id)
    await state.set_state(AdminMessageTemplateStates.body)
    await edit_or_send(callback.message, 
        "أرسل النص الجديد كاملًا. حافظ على المتغيرات الضرورية بين الأقواس.\n\n"
        f"النص الحالي:\n{row.body}"
    )


@router.message(AdminMessageTemplateStates.body)
async def message_template_edit_finish(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    services: Services,
) -> None:
    if not await require_admin(message, settings):
        return
    body = (message.text or "").strip()
    if len(body) < 3 or len(body) > 4000:
        await message.answer("النص يجب أن يكون بين 3 و4000 حرف.")
        return
    from app.db.models import MessageTemplate

    data = await state.get_data()
    template_id = int(data.get("message_template_id", 0))
    row = await session.get(MessageTemplate, template_id)
    if not row:
        await state.clear()
        await message.answer("القالب غير موجود.")
        return
    missing = [name for name in row.variables if "{" + name + "}" not in body]
    if missing:
        await message.answer(
            "النص يفتقد المتغيرات التالية: "
            + "، ".join(f"<code>{{{name}}}</code>" for name in missing)
        )
        return
    actor = await admin_actor(session, services, message)
    await services.templates.update(session, row.template_key, body, actor, row.locale)
    await services.audit.log(
        session,
        actor,
        "message_template.updated",
        "message_template",
        str(row.id),
        {"key": row.template_key},
    )
    await state.clear()
    await message.answer("تم تحديث قالب الرسالة ✅", reply_markup=admin_back())

@router.callback_query(F.data == "admin:menu_revision_save")
async def menu_revision_save(
    callback: CallbackQuery, session: AsyncSession, settings: Settings, services: Services
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    actor = await admin_actor(session, services, callback)
    revision = await services.menus.snapshot_revision(
        session, actor_user_id=actor.id if actor else None, label="نسخة يدوية من واجهة البوت"
    )
    if actor:
        await services.audit.log(session, actor, "menu.revision.created", "menu_revision", str(revision.id), {"revision": revision.revision, "checksum": revision.checksum})
    await edit_or_send(callback.message, f"تم حفظ نسخة الواجهة رقم <b>#{revision.revision}</b> ✅\n<code>{revision.checksum[:16]}</code>", reply_markup=admin_back())


@router.callback_query(F.data == "admin:menu_revision_list")
async def menu_revision_list(
    callback: CallbackQuery, session: AsyncSession, settings: Settings, services: Services
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    revisions = await services.menus.list_revisions(session)
    rows = [[InlineKeyboardButton(
        text=f"↩️ استعادة #{row.revision} · {row.created_at:%Y-%m-%d %H:%M}",
        callback_data=f"admin:menu_revision_restore:{row.id}", style="primary"
    )] for row in revisions]
    rows.append([InlineKeyboardButton(text="↩️ منشئ القوائم", callback_data="admin:menu_builder")])
    text = "🕘 <b>نسخ واجهة البوت</b>\n\nكل استعادة تنشئ نسخة أمان تلقائية قبل التطبيق." if revisions else "لا توجد نسخ محفوظة بعد."
    await edit_or_send(callback.message, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("admin:menu_revision_restore:"))
async def menu_revision_restore(
    callback: CallbackQuery, session: AsyncSession, settings: Settings, services: Services
) -> None:
    await callback.answer()
    if not await require_admin(callback, settings) or not callback.message:
        return
    try:
        revision_id = int((callback.data or "").rsplit(":", 1)[1])
    except (ValueError, IndexError):
        return
    actor = await admin_actor(session, services, callback)
    try:
        revision = await services.menus.restore_revision(
            session, revision_id, actor_user_id=actor.id if actor else None
        )
    except ValueError as exc:
        await edit_or_send(callback.message, str(exc), reply_markup=admin_back())
        return
    if actor:
        await services.audit.log(session, actor, "menu.revision.restored", "menu_revision", str(revision.id), {"revision": revision.revision})
    await edit_or_send(callback.message, f"تمت استعادة نسخة الواجهة <b>#{revision.revision}</b> ✅", reply_markup=admin_back())

