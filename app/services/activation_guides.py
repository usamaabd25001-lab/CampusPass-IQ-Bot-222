from __future__ import annotations

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    ActivationMode,
    GuideStepKind,
    Offer,
    OfferActivationGuide,
    OfferGuideStep,
    Order,
    OrderGuideAcknowledgement,
    User,
)

ACTIVATION_MODE_LABELS = {
    ActivationMode.EMAIL_PASSWORD.value: "إيميل + كلمة مرور",
    ActivationMode.EMAIL_CODE.value: "إيميل + رمز تحقق",
    ActivationMode.EMAIL_PASSWORD_CODE.value: "إيميل + كلمة مرور + رمز تحقق",
    ActivationMode.ACTIVATION_CODE.value: "كود تفعيل فقط",
    ActivationMode.CUSTOM_DATA.value: "بيانات مخصصة",
    ActivationMode.MANUAL.value: "تفعيل يدوي",
}


class ActivationGuideService:
    async def get_for_offer(
        self, session: AsyncSession, offer_id: int
    ) -> OfferActivationGuide | None:
        return await session.scalar(
            select(OfferActivationGuide)
            .options(selectinload(OfferActivationGuide.steps))
            .where(
                OfferActivationGuide.offer_id == offer_id,
                OfferActivationGuide.is_active.is_(True),
            )
        )

    async def upsert(
        self,
        session: AsyncSession,
        *,
        offer: Offer,
        activation_mode: str,
        title: str,
        intro_text: str,
        steps: list[dict],
        actor_user_id: int | None,
        acknowledgement_required: bool = True,
        show_before_delivery: bool = True,
    ) -> OfferActivationGuide:
        if activation_mode not in {mode.value for mode in ActivationMode}:
            raise ValueError("طريقة التفعيل غير معتمدة")
        normalized_steps = self._normalize_steps(steps)
        if not normalized_steps:
            raise ValueError("يجب إضافة خطوة تعليمات واحدة على الأقل")
        guide = await session.scalar(
            select(OfferActivationGuide)
            .where(OfferActivationGuide.offer_id == offer.id)
            .with_for_update()
        )
        if not guide:
            guide = OfferActivationGuide(
                offer_id=offer.id,
                activation_mode=activation_mode,
                created_by_user_id=actor_user_id,
            )
            session.add(guide)
            await session.flush()
        guide.activation_mode = activation_mode
        guide.title = (title or "طريقة التسجيل والتفعيل").strip()[:220]
        guide.intro_text = (intro_text or "").strip()[:4000]
        guide.acknowledgement_required = acknowledgement_required
        guide.show_before_delivery = show_before_delivery
        guide.is_active = True
        await session.execute(delete(OfferGuideStep).where(OfferGuideStep.guide_id == guide.id))
        for position, item in enumerate(normalized_steps, start=1):
            session.add(
                OfferGuideStep(
                    guide_id=guide.id,
                    position=position,
                    kind=item["kind"],
                    text=item.get("text", ""),
                    telegram_file_id=item.get("telegram_file_id"),
                    url=item.get("url"),
                    button_text=item.get("button_text"),
                )
            )
        await session.flush()
        return await self.get_for_offer(session, offer.id) or guide

    @staticmethod
    def _normalize_steps(steps: list[dict]) -> list[dict]:
        result: list[dict] = []
        valid = {kind.value for kind in GuideStepKind}
        for item in steps[:30]:
            kind = str(item.get("kind") or GuideStepKind.TEXT.value)
            if kind not in valid:
                continue
            text = str(item.get("text") or "").strip()[:4000]
            file_id = str(item.get("telegram_file_id") or "").strip() or None
            url = str(item.get("url") or "").strip() or None
            if kind == GuideStepKind.TEXT.value and not text:
                continue
            if kind in {
                GuideStepKind.PHOTO.value,
                GuideStepKind.VIDEO.value,
                GuideStepKind.DOCUMENT.value,
            } and not file_id:
                continue
            if kind == GuideStepKind.LINK.value and not url:
                continue
            result.append(
                {
                    "kind": kind,
                    "text": text,
                    "telegram_file_id": file_id,
                    "url": url,
                    "button_text": str(item.get("button_text") or "فتح الرابط").strip()[:120],
                }
            )
        return result

    async def acknowledged(
        self, session: AsyncSession, *, order_id: int, user_id: int
    ) -> bool:
        return bool(
            await session.scalar(
                select(OrderGuideAcknowledgement.id).where(
                    OrderGuideAcknowledgement.order_id == order_id,
                    OrderGuideAcknowledgement.user_id == user_id,
                )
            )
        )

    async def acknowledge(
        self,
        session: AsyncSession,
        *,
        order: Order,
        user: User,
    ) -> OrderGuideAcknowledgement:
        if order.user_id != user.id:
            raise PermissionError("غير مصرح")
        guide = await self.get_for_offer(session, order.offer_id)
        if not guide:
            raise ValueError("لا توجد تعليمات لهذا العرض")
        row = await session.scalar(
            select(OrderGuideAcknowledgement)
            .where(OrderGuideAcknowledgement.order_id == order.id)
            .with_for_update()
        )
        if not row:
            row = OrderGuideAcknowledgement(
                order_id=order.id,
                guide_id=guide.id,
                user_id=user.id,
            )
            session.add(row)
            await session.flush()
        return row

    @staticmethod
    def acknowledgement_keyboard(order_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ قرأت التعليمات وأفهمها",
                        callback_data=f"guide:ack:{order_id}",
                        style="success",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🆘 أحتاج مساعدة",
                        callback_data=f"support:order:{order_id}",
                        style="danger",
                    )
                ],
            ]
        )

    async def send_to_chat(
        self,
        bot: Bot,
        chat_id: int,
        guide: OfferActivationGuide,
        *,
        order_id: int | None = None,
        include_acknowledgement: bool = False,
    ) -> None:
        heading = f"📖 <b>{guide.title}</b>"
        mode = ACTIVATION_MODE_LABELS.get(guide.activation_mode, guide.activation_mode)
        intro = f"{heading}\nطريقة التسليم: <b>{mode}</b>"
        if guide.intro_text:
            intro += f"\n\n{guide.intro_text}"
        await bot.send_message(chat_id, intro)
        for step in sorted(guide.steps, key=lambda item: item.position):
            prefix = f"<b>الخطوة {step.position}</b>"
            caption = f"{prefix}\n{step.text}" if step.text else prefix
            if step.kind == GuideStepKind.TEXT.value:
                await bot.send_message(chat_id, caption)
            elif step.kind == GuideStepKind.PHOTO.value and step.telegram_file_id:
                await bot.send_photo(chat_id, step.telegram_file_id, caption=caption)
            elif step.kind == GuideStepKind.VIDEO.value and step.telegram_file_id:
                await bot.send_video(chat_id, step.telegram_file_id, caption=caption)
            elif step.kind == GuideStepKind.DOCUMENT.value and step.telegram_file_id:
                await bot.send_document(chat_id, step.telegram_file_id, caption=caption)
            elif step.kind == GuideStepKind.LINK.value and step.url:
                markup = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text=step.button_text or "فتح الرابط",
                                url=step.url,
                                style="primary",
                            )
                        ]
                    ]
                )
                await bot.send_message(chat_id, caption, reply_markup=markup)
        if include_acknowledgement and order_id:
            await bot.send_message(
                chat_id,
                "⚠️ راجع الخطوات قبل استلام بيانات الحساب.",
                reply_markup=self.acknowledgement_keyboard(order_id),
            )

    async def send_to_message(
        self,
        message: Message,
        guide: OfferActivationGuide,
        *,
        order_id: int | None = None,
        include_acknowledgement: bool = False,
    ) -> None:
        await self.send_to_chat(
            message.bot,
            message.chat.id,
            guide,
            order_id=order_id,
            include_acknowledgement=include_acknowledgement,
        )
