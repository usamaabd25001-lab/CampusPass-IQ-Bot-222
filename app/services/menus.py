from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from collections import defaultdict
from dataclasses import dataclass

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import (
    MenuButtonConfig,
    MenuButtonContent,
    MenuContentType,
    MenuRevision,
    MenuStyle,
    SystemSetting,
    User,
    UserRole,
)
from app.services.features import FeatureService
from app.services.cache_coherence import CacheCoherenceService
from app.services.platform_access import resolve_provider_access

MENU_SURFACES = {"reply", "inline", "both", "hidden"}
MENU_SURFACE_PREFIX = "menu.surface."
MENU_ALIAS_PREFIX = "menu.aliases."
MENU_PARENT_PREFIX = "menu.parent."


@dataclass(slots=True, frozen=True)
class MenuButtonView:
    id: int
    key: str
    text: str
    action: str
    style: str
    row_number: int
    position: int
    role_scope: list[str]
    is_enabled: bool
    surface: str
    content_type: str = MenuContentType.SYSTEM_ACTION.value
    parent_key: str | None = None


class MenuService:
    """Builds the user menu from database configuration.

    The action/key are stable identifiers. Administrators may change presentation
    (text, color, surface and position) without changing the action executed by the bot.
    """

    def __init__(
        self,
        settings: Settings,
        features: FeatureService,
        cache_coherence: CacheCoherenceService | None = None,
    ) -> None:
        self.settings = settings
        self.features = features
        self.cache_coherence = cache_coherence or CacheCoherenceService()
        self._menu_generation = 0
        # Menu metadata is a hot read path and changes rarely. Keep a five-minute
        # in-process snapshot to eliminate repeated Neon round-trips. Every menu
        # mutation already invalidates this cache immediately, so owner changes
        # remain visible without waiting for the TTL.
        self._menu_cache_ttl = 300.0
        self._menu_cache_expires = 0.0
        self._menu_cache: list[MenuButtonView] | None = None

    async def _invalidate_menu_cache(
        self, session: AsyncSession, *, reason: str = "menu-mutation"
    ) -> None:
        self._menu_cache = None
        self._menu_cache_expires = 0.0
        self._menu_generation = await self.cache_coherence.bump(
            session, "menus", reason=reason
        )

    async def effective_role(self, session: AsyncSession, user: User) -> str:
        if self.settings.is_admin(user.telegram_id) or user.role == UserRole.ADMIN.value:
            return UserRole.ADMIN.value
        context = await resolve_provider_access(
            session,
            self.settings,
            user.telegram_id,
            require_terms=False,
            allow_paused_provider=True,
        )
        # The resolver already provides a short process-local cache with targeted
        # invalidation. A second role cache delayed newly linked staff for several
        # seconds and made the visible button disagree with handler authorization.
        return UserRole.PROVIDER.value if context.memberships else UserRole.USER.value

    async def _surface_map(self, session: AsyncSession) -> dict[str, str]:
        settings = list(
            (
                await session.scalars(
                    select(SystemSetting).where(SystemSetting.key.like(f"{MENU_SURFACE_PREFIX}%"))
                )
            ).all()
        )
        result: dict[str, str] = {}
        for item in settings:
            key = item.key.removeprefix(MENU_SURFACE_PREFIX)
            result[key] = item.value if item.value in MENU_SURFACES else "reply"
        return result

    async def list_buttons(self, session: AsyncSession) -> list[MenuButtonView]:
        generation = await self.cache_coherence.generation(session, "menus")
        if generation != self._menu_generation:
            self._menu_generation = generation
            self._menu_cache = None
            self._menu_cache_expires = 0.0
        now = time.monotonic()
        if self._menu_cache is not None and self._menu_cache_expires > now:
            return self._menu_cache
        items = list(
            (
                await session.scalars(
                    select(MenuButtonConfig).order_by(
                        MenuButtonConfig.row_number,
                        MenuButtonConfig.position,
                        MenuButtonConfig.id,
                    )
                )
            ).all()
        )
        surfaces = await self._surface_map(session)
        content_rows = list((await session.scalars(select(MenuButtonContent))).all())
        content_map = {item.button_key: item for item in content_rows}
        parent_rows = list((await session.scalars(
            select(SystemSetting).where(SystemSetting.key.like(f"{MENU_PARENT_PREFIX}%"))
        )).all())
        parent_map = {item.key.removeprefix(MENU_PARENT_PREFIX): (item.value or None) for item in parent_rows}
        result = [
            MenuButtonView(
                id=item.id,
                key=item.key,
                text=item.text,
                action=item.action,
                style=item.style,
                row_number=item.row_number,
                position=item.position,
                role_scope=list(item.role_scope or []),
                is_enabled=item.is_enabled,
                surface=surfaces.get(item.key, "reply"),
                content_type=(
                    content_map[item.key].content_type
                    if item.key in content_map
                    else MenuContentType.SYSTEM_ACTION.value
                ),
                parent_key=(
                    content_map[item.key].parent_key
                    if item.key in content_map and content_map[item.key].parent_key is not None
                    else parent_map.get(item.key)
                ),
            )
            for item in items
        ]
        self._menu_cache = result
        self._menu_cache_expires = now + self._menu_cache_ttl
        return result

    async def get_button(self, session: AsyncSession, key: str) -> MenuButtonView | None:
        for item in await self.list_buttons(session):
            if item.key == key:
                return item
        return None

    async def get_button_by_text(self, session: AsyncSession, text: str) -> MenuButtonView | None:
        for item in await self.list_buttons(session):
            if item.text == text:
                return item
        return None

    async def get_button_by_id(self, session: AsyncSession, button_id: int) -> MenuButtonView | None:
        for item in await self.list_buttons(session):
            if item.id == button_id:
                return item
        return None

    async def resolve_button_token(
        self, session: AsyncSession, token: str | int
    ) -> MenuButtonView | None:
        """Resolve compact numeric callback tokens with legacy key compatibility."""
        raw = str(token).strip()
        if raw.isdecimal():
            return await self.get_button_by_id(session, int(raw))
        return await self.get_button(session, raw)

    async def _visible_buttons(
        self,
        session: AsyncSession,
        user: User,
        surfaces: set[str],
        *,
        parent_key: str | None = None,
    ) -> list[MenuButtonView]:
        context = await resolve_provider_access(
            session,
            self.settings,
            user.telegram_id,
            require_terms=False,
            allow_paused_provider=True,
        )
        role = (
            UserRole.ADMIN.value
            if self.settings.is_admin(user.telegram_id) or user.role == UserRole.ADMIN.value
            else UserRole.PROVIDER.value
            if context.memberships
            else UserRole.USER.value
        )
        platform_allowed = context.failure_reason.value in {
            "none", "terms_required", "selection_required"
        }
        reward_tasks_enabled = await self.features.enabled(
            session, "reward_tasks", default=False
        )
        return [
            item
            for item in await self.list_buttons(session)
            if item.is_enabled
            and item.action != "privacy"
            and (item.action != "earn" or reward_tasks_enabled)
            and role in item.role_scope
            and item.surface in surfaces
            and item.surface != "hidden"
            and item.parent_key == parent_key
            and (
                item.action != "provider_dashboard"
                or platform_allowed
            )
            and (
                item.action != "admin_dashboard"
                or self.settings.is_admin(user.telegram_id)
            )
        ]

    async def reply_keyboard(
        self,
        session: AsyncSession,
        user: User,
        *,
        parent_key: str | None = None,
        include_inline_surfaces: bool = False,
    ) -> ReplyKeyboardMarkup | None:
        colored = self.settings.feature_colored_buttons and await self.features.enabled(
            session, "colored_buttons", True
        )
        visible_surfaces = {"reply", "both", "inline"} if include_inline_surfaces else {"reply", "both"}
        configs = await self._visible_buttons(
            session, user, visible_surfaces, parent_key=parent_key
        )
        rows: dict[int, list[KeyboardButton]] = defaultdict(list)
        for item in configs:
            style = None
            if colored and item.style != MenuStyle.DEFAULT.value:
                style = item.style
            rows[item.row_number].append(KeyboardButton(text=item.text, style=style))
        keyboard_rows = [rows[key] for key in sorted(rows)]
        # Root stays intentionally clean. Back/Home appear only after the user
        # enters a section, matching the menu-builder navigation model.
        if parent_key is not None:
            nav_row = [KeyboardButton(text="⬅️ رجوع")]
            nav_row.append(KeyboardButton(text="🏠 الرئيسية", style="primary" if colored else None))
            keyboard_rows.append(nav_row)
        return ReplyKeyboardMarkup(
            keyboard=keyboard_rows,
            resize_keyboard=True,
            is_persistent=True,
            input_field_placeholder="اختر من القائمة أو اكتب المطلوب",
        )

    async def inline_keyboard(
        self,
        session: AsyncSession,
        user: User,
        *,
        parent_key: str | None = None,
    ) -> InlineKeyboardMarkup | None:
        colored = self.settings.feature_colored_buttons and await self.features.enabled(
            session, "colored_buttons", True
        )
        configs = await self._visible_buttons(
            session,
            user,
            {"inline", "both"},
            parent_key=parent_key,
        )
        rows: dict[int, list[InlineKeyboardButton]] = defaultdict(list)
        for item in configs:
            style = None
            if colored and item.style != MenuStyle.DEFAULT.value:
                style = item.style
            rows[item.row_number].append(
                InlineKeyboardButton(
                    text=item.text,
                    callback_data=f"menu:open:{item.id}",
                    style=style,
                )
            )
        if not rows:
            return None
        return InlineKeyboardMarkup(inline_keyboard=[rows[key] for key in sorted(rows)])

    async def keyboard(self, session: AsyncSession, user: User) -> ReplyKeyboardMarkup | None:
        """Backward-compatible alias used by older handlers."""
        return await self.reply_keyboard(session, user)

    async def _platform_button_allowed(self, session: AsyncSession, user: User | None) -> bool:
        if user is None:
            return False
        context = await resolve_provider_access(
            session,
            self.settings,
            user.telegram_id,
            require_terms=False,
            allow_paused_provider=True,
        )
        return context.failure_reason.value in {
            "none", "terms_required", "selection_required"
        }

    async def resolve_action(
        self,
        session: AsyncSession,
        text: str,
        role: str,
        user: User | None = None,
    ) -> str | None:
        # Normal keyboard presses resolve entirely from the short-lived menu
        # snapshot. The alias DB path remains only for renamed/legacy labels.
        cached_item = next(
            (item for item in await self.list_buttons(session) if item.text == text and item.is_enabled),
            None,
        )
        if cached_item is not None:
            if role not in cached_item.role_scope or cached_item.surface == "hidden":
                return None
            if cached_item.action == "privacy":
                return None
            if cached_item.action == "provider_dashboard" and (
                not await self._platform_button_allowed(session, user)
            ):
                return None
            if cached_item.action == "admin_dashboard" and (
                user is None or not self.settings.is_admin(user.telegram_id)
            ):
                return None
            return cached_item.action

        item = None
        if item is None:
            alias_settings = list(
                (
                    await session.scalars(
                        select(SystemSetting).where(SystemSetting.key.like(f"{MENU_ALIAS_PREFIX}%"))
                    )
                ).all()
            )
            alias_key = None
            for setting in alias_settings:
                try:
                    aliases = json.loads(setting.value)
                except (TypeError, ValueError, json.JSONDecodeError):
                    aliases = []
                if text in aliases:
                    alias_key = setting.key.removeprefix(MENU_ALIAS_PREFIX)
                    break
            if alias_key:
                item = await session.scalar(
                    select(MenuButtonConfig).where(
                        MenuButtonConfig.key == alias_key,
                        MenuButtonConfig.is_enabled.is_(True),
                    )
                )
        if not item or role not in (item.role_scope or []):
            return None
        surface = await self.surface(session, item.key)
        if surface == "hidden" or item.action == "privacy":
            return None
        if item.action == "provider_dashboard" and (
            not await self._platform_button_allowed(session, user)
        ):
            return None
        if item.action == "admin_dashboard" and (
            user is None or not self.settings.is_admin(user.telegram_id)
        ):
            return None
        return item.action

    async def resolve_action_by_key(
        self,
        session: AsyncSession,
        key: str,
        role: str,
        user: User | None = None,
    ) -> str | None:
        item = await self.get_button(session, key)
        if not item or not item.is_enabled or role not in item.role_scope:
            return None
        if item.surface == "hidden" or item.action == "privacy":
            return None
        if item.action == "provider_dashboard" and (
            not await self._platform_button_allowed(session, user)
        ):
            return None
        if item.action == "admin_dashboard" and (
            user is None or not self.settings.is_admin(user.telegram_id)
        ):
            return None
        return item.action

    async def surface(self, session: AsyncSession, key: str) -> str:
        item = await self.get_button(session, key)
        return item.surface if item is not None else "reply"

    async def set_surface(self, session: AsyncSession, key: str, surface: str) -> bool:
        if surface not in MENU_SURFACES:
            return False
        item = await session.scalar(select(MenuButtonConfig.id).where(MenuButtonConfig.key == key))
        if not item:
            return False
        setting_key = f"{MENU_SURFACE_PREFIX}{key}"
        setting = await session.scalar(
            select(SystemSetting).where(SystemSetting.key == setting_key)
        )
        if setting is None:
            session.add(SystemSetting(key=setting_key, value=surface))
        else:
            setting.value = surface
        await session.flush()
        await self._invalidate_menu_cache(session)
        return True

    async def set_all_surfaces(self, session: AsyncSession, surface: str) -> int:
        if surface not in MENU_SURFACES:
            return 0
        buttons = list((await session.scalars(select(MenuButtonConfig))).all())
        changed = 0
        for item in buttons:
            if await self.set_surface(session, item.key, surface):
                changed += 1
        return changed

    async def content(self, session: AsyncSession, key: str) -> MenuButtonContent | None:
        return await session.scalar(
            select(MenuButtonContent).where(MenuButtonContent.button_key == key)
        )

    async def children_keyboard(
        self, session: AsyncSession, user: User, parent_key: str
    ) -> InlineKeyboardMarkup | None:
        colored = self.settings.feature_colored_buttons and await self.features.enabled(
            session, "colored_buttons", True
        )
        configs = await self._visible_buttons(
            session, user, {"inline", "both", "reply"}, parent_key=parent_key
        )
        rows: dict[int, list[InlineKeyboardButton]] = defaultdict(list)
        for item in configs:
            style = item.style if colored and item.style != MenuStyle.DEFAULT.value else None
            rows[item.row_number].append(
                InlineKeyboardButton(
                    text=item.text,
                    callback_data=f"menu:open:{item.id}",
                    style=style,
                )
            )
        if not rows:
            return None
        result = [rows[key] for key in sorted(rows)]
        parent_button = await self.get_button(session, parent_key)
        back_parent = parent_button.parent_key if parent_button else None
        back_button = await self.get_button(session, back_parent) if back_parent else None
        callback = f"menu:open:{back_button.id}" if back_button else "nav:home"
        result.append([InlineKeyboardButton(text="↩️ رجوع", callback_data=callback)])
        return InlineKeyboardMarkup(inline_keyboard=result)

    async def create_custom_button(
        self,
        session: AsyncSession,
        *,
        key: str,
        text: str,
        content_type: str,
        roles: list[str],
        parent_key: str | None = None,
        content_text: str = "",
        media_file_id: str | None = None,
        url: str | None = None,
        row_number: int = 1,
        position: int = 1,
        surface: str = "inline",
        actor_user_id: int | None = None,
    ) -> MenuButtonConfig:
        if content_type not in {item.value for item in MenuContentType}:
            raise ValueError("نوع الزر غير معتمد")
        normalized_key = "".join(ch for ch in key.lower().strip() if ch.isalnum() or ch in "_-")
        if not 3 <= len(normalized_key) <= 80:
            raise ValueError("معرف الزر غير صالح")
        if await session.scalar(
            select(MenuButtonConfig.id).where(MenuButtonConfig.key == normalized_key)
        ):
            raise ValueError("معرف الزر مستخدم")
        text = " ".join(text.split()).strip()
        if not 1 <= len(text) <= 120:
            raise ValueError("اسم الزر غير صالح")
        button = MenuButtonConfig(
            key=normalized_key,
            text=text,
            action="custom_content",
            style=MenuStyle.DEFAULT.value,
            row_number=max(1, min(50, row_number)),
            position=max(1, min(20, position)),
            role_scope=roles or [UserRole.USER.value],
            is_enabled=True,
        )
        session.add(button)
        await session.flush()
        session.add(
            MenuButtonContent(
                button_key=button.key,
                content_type=content_type,
                parent_key=parent_key,
                text=content_text[:10000],
                telegram_file_id=media_file_id,
                url=url,
                created_by_user_id=actor_user_id,
            )
        )
        await self.set_surface(session, button.key, surface)
        await session.flush()
        await self._invalidate_menu_cache(session)
        return button

    async def delete_custom_button(self, session: AsyncSession, key: str) -> bool:
        content = await self.content(session, key)
        if not content:
            return False
        child = await session.scalar(
            select(MenuButtonContent.id).where(MenuButtonContent.parent_key == key).limit(1)
        )
        if child:
            raise ValueError("انقل أو احذف الأزرار الفرعية أولًا")
        button = await session.scalar(select(MenuButtonConfig).where(MenuButtonConfig.key == key))
        if not button:
            return False
        await session.delete(content)
        await session.delete(button)
        setting = await session.scalar(
            select(SystemSetting).where(SystemSetting.key == f"{MENU_SURFACE_PREFIX}{key}")
        )
        if setting:
            await session.delete(setting)
        await session.flush()
        await self._invalidate_menu_cache(session)
        return True

    async def set_style(self, session: AsyncSession, key: str, style: str) -> bool:
        if style not in {x.value for x in MenuStyle}:
            return False
        item = await session.scalar(select(MenuButtonConfig).where(MenuButtonConfig.key == key))
        if not item:
            return False
        item.style = style
        await session.flush()
        await self._invalidate_menu_cache(session)
        return True

    async def set_text(self, session: AsyncSession, key: str, text: str) -> bool:
        item = await session.scalar(select(MenuButtonConfig).where(MenuButtonConfig.key == key))
        text = " ".join(text.split()).strip()
        if not item or not 1 <= len(text) <= 120 or any(ord(ch) < 32 for ch in text):
            return False
        duplicate = await session.scalar(
            select(MenuButtonConfig.id).where(
                MenuButtonConfig.text == text,
                MenuButtonConfig.key != key,
                MenuButtonConfig.is_enabled.is_(True),
            )
        )
        if duplicate:
            return False
        if item.text != text:
            alias_key = f"{MENU_ALIAS_PREFIX}{key}"
            alias_setting = await session.scalar(
                select(SystemSetting).where(SystemSetting.key == alias_key)
            )
            try:
                aliases = json.loads(alias_setting.value) if alias_setting else []
            except (TypeError, ValueError, json.JSONDecodeError):
                aliases = []
            aliases = [value for value in aliases if isinstance(value, str) and value != text]
            aliases.append(item.text)
            aliases = aliases[-10:]
            if alias_setting is None:
                session.add(
                    SystemSetting(key=alias_key, value=json.dumps(aliases, ensure_ascii=False))
                )
            else:
                alias_setting.value = json.dumps(aliases, ensure_ascii=False)
            item.text = text
        await session.flush()
        await self._invalidate_menu_cache(session)
        return True

    async def move_button(self, session: AsyncSession, key: str, direction: str) -> bool:
        """Move a button visually without exposing row/column numbers to the owner."""
        item = await session.scalar(select(MenuButtonConfig).where(MenuButtonConfig.key == key))
        if not item or direction not in {"left", "right", "up", "down"}:
            return False
        siblings = list((await session.scalars(
            select(MenuButtonConfig).order_by(
                MenuButtonConfig.row_number, MenuButtonConfig.position, MenuButtonConfig.id
            )
        )).all())
        # Keep system storage compatible: movement only changes the same two fields
        # already used by the existing renderer. No handler/action is rewritten.
        if direction == "left":
            same = [x for x in siblings if x.row_number == item.row_number and x.key != key]
            target = max((x for x in same if x.position < item.position), key=lambda x: x.position, default=None)
            if target:
                item.position, target.position = target.position, item.position
            elif item.position > 1:
                item.position -= 1
            else:
                return False
        elif direction == "right":
            same = [x for x in siblings if x.row_number == item.row_number and x.key != key]
            target = min((x for x in same if x.position > item.position), key=lambda x: x.position, default=None)
            if target:
                item.position, target.position = target.position, item.position
            else:
                item.position += 1
        elif direction == "up":
            if item.row_number <= 1:
                return False
            item.row_number -= 1
        else:
            item.row_number += 1
        await session.flush()
        await self._invalidate_menu_cache(session)
        return True

    async def set_position(
        self, session: AsyncSession, key: str, row_number: int, position: int
    ) -> bool:
        if not 1 <= row_number <= 50 or not 1 <= position <= 20:
            return False
        item = await session.scalar(select(MenuButtonConfig).where(MenuButtonConfig.key == key))
        if not item:
            return False
        item.row_number = row_number
        item.position = position
        await session.flush()
        await self._invalidate_menu_cache(session)
        return True

    async def set_enabled(self, session: AsyncSession, key: str, enabled: bool) -> bool:
        item = await session.scalar(select(MenuButtonConfig).where(MenuButtonConfig.key == key))
        if not item:
            return False
        if enabled:
            duplicate = await session.scalar(
                select(MenuButtonConfig.id).where(
                    MenuButtonConfig.text == item.text,
                    MenuButtonConfig.key != key,
                    MenuButtonConfig.is_enabled.is_(True),
                )
            )
            if duplicate:
                return False
        item.is_enabled = enabled
        await session.flush()
        await self._invalidate_menu_cache(session)
        return True

    async def snapshot_revision(
        self, session: AsyncSession, *, actor_user_id: int | None, label: str = ""
    ) -> MenuRevision:
        buttons = list((await session.scalars(select(MenuButtonConfig).order_by(MenuButtonConfig.key))).all())
        contents = list((await session.scalars(select(MenuButtonContent).order_by(MenuButtonContent.button_key))).all())
        settings = list((await session.scalars(
            select(SystemSetting).where(SystemSetting.key.like("menu.%")).order_by(SystemSetting.key)
        )).all())
        snapshot = {
            "buttons": [
                {"key": row.key, "text": row.text, "action": row.action, "style": row.style,
                 "row_number": row.row_number, "position": row.position,
                 "role_scope": row.role_scope or [], "is_enabled": bool(row.is_enabled)}
                for row in buttons
            ],
            "contents": [
                {"button_key": row.button_key, "content_type": row.content_type,
                 "parent_key": row.parent_key, "text": row.text,
                 "telegram_file_id": row.telegram_file_id, "url": row.url,
                 "target_action": row.target_action, "report_type": row.report_type}
                for row in contents
            ],
            "settings": {row.key: row.value for row in settings},
        }
        canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        checksum = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        number = int(await session.scalar(select(func.coalesce(func.max(MenuRevision.revision), 0))) or 0) + 1
        revision = MenuRevision(
            revision=number, label=(label.strip() or f"نسخة الواجهة {number}")[:160],
            snapshot_json=snapshot, checksum=checksum, created_by_user_id=actor_user_id,
        )
        session.add(revision)
        await session.flush()
        return revision

    async def list_revisions(self, session: AsyncSession, limit: int = 10) -> list[MenuRevision]:
        return list((await session.scalars(
            select(MenuRevision).order_by(MenuRevision.revision.desc()).limit(max(1, min(limit, 25)))
        )).all())

    async def restore_revision(
        self, session: AsyncSession, revision_id: int, *, actor_user_id: int | None
    ) -> MenuRevision:
        revision = await session.scalar(
            select(MenuRevision).where(MenuRevision.id == revision_id).with_for_update()
        )
        if revision is None:
            raise ValueError("نسخة الواجهة غير موجودة")
        await self.snapshot_revision(
            session, actor_user_id=actor_user_id, label=f"نسخة تلقائية قبل استعادة #{revision.revision}"
        )
        snapshot = revision.snapshot_json or {}
        current_buttons = {row.key: row for row in (await session.scalars(select(MenuButtonConfig))).all()}
        restored_keys: set[str] = set()
        for item in snapshot.get("buttons", []):
            key = str(item.get("key", "")).strip()
            if not key:
                continue
            row = current_buttons.get(key)
            if row is None:
                row = MenuButtonConfig(key=key, text=str(item.get("text", key)), action=str(item.get("action", "custom_content")))
                session.add(row)
            row.text = str(item.get("text", row.text))[:120]
            row.action = str(item.get("action", row.action))[:80]
            row.style = str(item.get("style", "default"))[:20]
            row.row_number = int(item.get("row_number", 0))
            row.position = int(item.get("position", 0))
            row.role_scope = list(item.get("role_scope") or ["user"])
            row.is_enabled = bool(item.get("is_enabled", True))
            restored_keys.add(key)
        current_contents = {row.button_key: row for row in (await session.scalars(select(MenuButtonContent))).all()}
        for item in snapshot.get("contents", []):
            key = str(item.get("button_key", "")).strip()
            if not key:
                continue
            row = current_contents.get(key)
            if row is None:
                row = MenuButtonContent(button_key=key)
                session.add(row)
            for field in ("content_type", "parent_key", "text", "telegram_file_id", "url", "target_action", "report_type"):
                setattr(row, field, item.get(field))
        for key, value in dict(snapshot.get("settings") or {}).items():
            row = await session.scalar(select(SystemSetting).where(SystemSetting.key == key))
            if row is None:
                session.add(SystemSetting(key=key, value=str(value)))
            else:
                row.value = str(value)
        revision.restored_at = datetime.now(UTC)
        await self._invalidate_menu_cache(session)
        await session.flush()
        return revision

