from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket
import time
from datetime import UTC, datetime, timedelta

from aiogram.enums import ChatAction
from sqlalchemy import delete, select

from app.bot.keyboards.inline import ai_support_result_keyboard
from app.core.context import AppContext
from app.core.utils import safe
from app.db.models import DistributedJob, DistributedJobStatus
from app.integrations.ai.gemini import GeminiPermanentError

logger = logging.getLogger(__name__)


class AISupportWorker:
    """Durable PostgreSQL-backed AI worker running inside the combined service."""

    def __init__(self, context: AppContext) -> None:
        self.context = context
        self.task: asyncio.Task | None = None
        self.stop_event = asyncio.Event()
        self.worker_id = (
            f"{context.settings.release_id}:ai-support:"
            f"{socket.gethostname()}:{os.getpid()}"
        )
        self._last_cleanup_at = 0.0

    async def start(self) -> None:
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.run(), name="campuspass-ai-support-worker")

    async def stop(self) -> None:
        self.stop_event.set()
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task

    async def run(self) -> None:
        poll = max(0.25, float(self.context.settings.gemini_worker_poll_seconds))
        while not self.stop_event.is_set():
            try:
                if not self.context.settings.gemini_ready:
                    await self._sleep(poll * 5)
                    continue
                if time.monotonic() - self._last_cleanup_at >= 3600:
                    await self._cleanup_finished_jobs()
                    self._last_cleanup_at = time.monotonic()
                job_ids = await self._claim()
                if not job_ids:
                    await self._sleep(poll)
                    continue
                await asyncio.gather(
                    *(self._process(job_id) for job_id in job_ids),
                    return_exceptions=False,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("AI support worker loop recovered from %s", type(exc).__name__)
                await self._sleep(min(10.0, poll * 3))

    async def _sleep(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self.stop_event.wait(), timeout=seconds)
        except TimeoutError:
            pass

    async def _cleanup_finished_jobs(self) -> None:
        cutoff = datetime.now(UTC) - timedelta(
            days=int(self.context.settings.gemini_job_retention_days)
        )
        async with self.context.database.session_factory() as session:
            result = await session.execute(
                delete(DistributedJob).where(
                    DistributedJob.queue_name == self.context.services.support.AI_QUEUE,
                    DistributedJob.status.in_(
                        [
                            DistributedJobStatus.SUCCEEDED.value,
                            DistributedJobStatus.DEAD.value,
                        ]
                    ),
                    DistributedJob.updated_at < cutoff,
                )
            )
            await session.commit()
            deleted = int(result.rowcount or 0)
            if deleted:
                logger.info("Pruned %s expired AI support jobs", deleted)

    async def _claim(self) -> list[int]:
        async with self.context.database.session_factory() as session:
            jobs = await self.context.services.enterprise_scale.claim_jobs(
                session,
                queue_name=self.context.services.support.AI_QUEUE,
                worker_id=self.worker_id,
                limit=max(1, min(int(self.context.settings.ai_concurrency_limit), 5)),
                lease_seconds=max(
                    180,
                    int(self.context.settings.gemini_timeout_seconds)
                    * int(self.context.settings.gemini_retry_attempts)
                    + 90,
                ),
            )
            ids = [job.id for job in jobs]
            await session.commit()
            return ids

    async def _typing_loop(self, chat_id: int, stop: asyncio.Event) -> None:
        while not stop.is_set():
            with contextlib.suppress(Exception):
                await self.context.bot.send_chat_action(
                    chat_id=chat_id, action=ChatAction.TYPING
                )
            try:
                await asyncio.wait_for(stop.wait(), timeout=4.0)
            except TimeoutError:
                continue

    async def _process(self, job_id: int) -> None:
        payload: dict = {}
        try:
            async with self.context.database.session_factory() as session:
                job = await session.get(DistributedJob, job_id)
                if job is None or job.status != DistributedJobStatus.LEASED.value:
                    return
                payload = dict(job.payload_json or {})
                if int(payload.get("job_schema_version", 0) or 0) != 1:
                    raise GeminiPermanentError("Unsupported AI support job schema")
                ai_enabled = await self.context.services.features.enabled(
                    session, "gemini", self.context.settings.gemini_ready
                )
                if not ai_enabled:
                    raise GeminiPermanentError("Gemini feature flag is disabled")
                ai_context = await self.context.services.support.build_ai_context(
                    session,
                    user_id=int(payload.get("user_id", 0) or 0),
                    order_id=int(payload.get("order_id", 0) or 0),
                    question=str(payload.get("question") or ""),
                )

            chat_id = int(payload.get("chat_id", 0) or 0)
            if chat_id <= 0:
                raise ValueError("AI support job has an invalid chat_id")
            stop_typing = asyncio.Event()
            typing_task = asyncio.create_task(self._typing_loop(chat_id, stop_typing))
            try:
                answer = await self.context.services.support.generate_ai_answer(
                    str(payload.get("question") or ""), ai_context
                )
            finally:
                stop_typing.set()
                with contextlib.suppress(asyncio.CancelledError):
                    await typing_task

            await self._deliver_answer(job_id, payload, answer)
            async with self.context.database.session_factory() as session:
                job = await session.scalar(
                    select(DistributedJob)
                    .where(DistributedJob.id == job_id)
                    .with_for_update()
                )
                if job is None:
                    return
                await self.context.services.enterprise_scale.finish_job(
                    session,
                    job,
                    success=True,
                    result={
                        "answer": answer,
                        "delivered_at": datetime.now(UTC).isoformat(),
                    },
                )
                await session.commit()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._handle_failure(job_id, payload, exc)

    async def _deliver_answer(self, job_id: int, payload: dict, answer: str) -> None:
        chat_id = int(payload.get("chat_id", 0) or 0)
        placeholder_id = int(payload.get("placeholder_message_id", 0) or 0)
        text = (
            "🤖 <b>مساعد CampusPass IQ</b>\n\n"
            f"{safe(answer)}\n\n"
            "هذه إجابة مساعدة مبنية على السياق المسموح. العمليات المالية والحساسة "
            "تُنفذ فقط من الأزرار الرسمية أو عبر فريق الدعم."
        )
        keyboard = ai_support_result_keyboard(job_id)
        if placeholder_id:
            try:
                await self.context.bot.edit_message_text(
                    text,
                    chat_id=chat_id,
                    message_id=placeholder_id,
                    reply_markup=keyboard,
                )
                return
            except Exception as exc:
                logger.warning(
                    "Could not edit AI placeholder job=%s error=%s",
                    job_id,
                    type(exc).__name__,
                )
        await self.context.bot.send_message(chat_id, text, reply_markup=keyboard)

    async def _handle_failure(self, job_id: int, payload: dict, exc: Exception) -> None:
        permanent = isinstance(exc, (GeminiPermanentError, PermissionError, ValueError))
        status = DistributedJobStatus.RETRY.value
        async with self.context.database.session_factory() as session:
            job = await session.scalar(
                select(DistributedJob)
                .where(DistributedJob.id == job_id)
                .with_for_update()
            )
            if job is None:
                return
            if permanent:
                job.attempts = job.max_attempts
            await self.context.services.enterprise_scale.finish_job(
                session,
                job,
                success=False,
                error=f"{type(exc).__name__}: {str(exc)[:500]}",
            )
            status = job.status
            await session.commit()
        logger.warning(
            "AI support job failed job=%s status=%s error=%s",
            job_id,
            status,
            type(exc).__name__,
        )
        if status == DistributedJobStatus.DEAD.value:
            chat_id = int(payload.get("chat_id", 0) or 0)
            placeholder_id = int(payload.get("placeholder_message_id", 0) or 0)
            text = (
                "⚠️ تعذر الحصول على رد من المساعد الذكي حالياً.\n\n"
                "سؤالك محفوظ ويمكنك فتح تذكرة دعم من الزر أدناه، بدون إعادة كتابته."
            )
            keyboard = ai_support_result_keyboard(job_id, failed=True)
            try:
                if placeholder_id:
                    await self.context.bot.edit_message_text(
                        text,
                        chat_id=chat_id,
                        message_id=placeholder_id,
                        reply_markup=keyboard,
                    )
                else:
                    await self.context.bot.send_message(chat_id, text, reply_markup=keyboard)
            except Exception as delivery_exc:
                logger.warning(
                    "Could not deliver AI failure notice job=%s error=%s",
                    job_id,
                    type(delivery_exc).__name__,
                )
