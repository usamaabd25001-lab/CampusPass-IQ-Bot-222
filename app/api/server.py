from __future__ import annotations

import asyncio

import html
import orjson
import logging
import secrets
from pathlib import Path
from datetime import UTC, datetime

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, ORJSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select, text

from app import AIOGRAM_TARGET, TELEGRAM_BOT_API_TARGET, __version__
from app.core.context import AppContext
from app.core.telegram_webapp import TelegramWebAppAuthError, verify_telegram_init_data
from app.db.models import OrderStatus, ReleaseCompatibility, RuntimeConfigGeneration, User
from app.services.webapp_profile import ProfilePayload

logger = logging.getLogger(__name__)


class StudentProfileUpdate(BaseModel):
    full_name: str = Field(min_length=5, max_length=180)
    phone: str = Field(min_length=10, max_length=20)
    governorate: str = Field(min_length=2, max_length=80)
    university: str = Field(min_length=2, max_length=180)
    college: str = Field(min_length=2, max_length=180)
    department: str = Field(min_length=2, max_length=180)
    stage: str = Field(min_length=1, max_length=80)


def build_api(context: AppContext) -> FastAPI:
    app = FastAPI(
        title="CampusPass IQ",
        version=__version__,
        docs_url=None if context.settings.environment == "production" else "/docs",
        redoc_url=None,
        default_response_class=ORJSONResponse,
    )


    def verified_webapp(request: Request):
        init_data = request.headers.get("X-Telegram-Init-Data", "").strip()
        try:
            return verify_telegram_init_data(
                init_data,
                bot_token=context.settings.bot_token,
                max_age_seconds=900,
            )
        except TelegramWebAppAuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    @app.post(context.settings.telegram_webhook_path)
    async def telegram_webhook(
        request: Request,
        x_telegram_bot_api_secret_token: str = Header(
            default="", alias="X-Telegram-Bot-Api-Secret-Token"
        ),
    ):
        if context.settings.telegram_delivery_mode != "webhook":
            raise HTTPException(404)
        if context.draining:
            # A non-2xx response makes Telegram retry against the replacement
            # Render instance instead of accepting work during graceful drain.
            raise HTTPException(503, "Deployment draining")
        expected = context.settings.telegram_webhook_secret
        if not expected or not secrets.compare_digest(
            x_telegram_bot_api_secret_token.strip(), expected
        ):
            raise HTTPException(403, "Forbidden")
        content_length = request.headers.get("content-length", "").strip()
        if content_length:
            try:
                if int(content_length) > context.settings.telegram_webhook_body_limit_bytes:
                    raise HTTPException(413, "Payload too large")
            except ValueError:
                raise HTTPException(400, "Invalid Content-Length") from None
        body = await request.body()
        if len(body) > context.settings.telegram_webhook_body_limit_bytes:
            raise HTTPException(413, "Payload too large")
        try:
            payload = orjson.loads(body)
        except orjson.JSONDecodeError as exc:
            raise HTTPException(400, "Invalid Telegram update JSON") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("update_id"), int):
            raise HTTPException(422, "Telegram update_id is required")
        try:
            async with context.database.session_factory() as session:
                row, created = await context.services.telegram_updates.enqueue(
                    session,
                    update_id=int(payload["update_id"]),
                    payload=payload,
                    release_id=context.settings.release_id,
                    max_attempts=context.settings.telegram_update_max_attempts,
                )
                await session.commit()
            context.update_wakeup.set()
        except ValueError as exc:
            logger.error("Rejected Telegram update collision update_id=%s", payload.get("update_id"))
            raise HTTPException(409, str(exc)) from exc
        except Exception as exc:
            logger.exception("Telegram update could not be durably accepted")
            raise HTTPException(503, "Update inbox unavailable") from exc
        return ORJSONResponse(
            {"ok": True, "accepted": created, "duplicate": not created, "update_id": row.update_id},
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/webapp/student/profile", response_class=HTMLResponse)
    async def student_profile_webapp():
        template_path = Path(__file__).with_name("templates") / "student_profile.html"
        html_body = template_path.read_text(encoding="utf-8")
        html_body = (
            html_body.replace("__PRIMARY__", context.settings.brand_primary_color)
            .replace("__SECONDARY__", context.settings.brand_secondary_color)
            .replace("__BOT_NAME__", html.escape(context.settings.bot_name))
        )
        return HTMLResponse(
            html_body,
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": (
                    "default-src 'self'; script-src 'self' https://telegram.org 'unsafe-inline'; "
                    "style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; connect-src 'self'; "
                    "frame-ancestors https://web.telegram.org https://*.telegram.org"
                ),
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
            },
        )

    @app.get("/api/webapp/student/profile")
    async def get_student_profile(request: Request):
        verified = verified_webapp(request)
        async with context.database.session_factory() as session:
            result = await context.services.webapp_profile.read(session, verified)
            await session.commit()
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    @app.put("/api/webapp/student/profile")
    async def put_student_profile(request: Request, payload: StudentProfileUpdate):
        verified = verified_webapp(request)
        try:
            async with context.database.session_factory() as session:
                result = await context.services.webapp_profile.save(
                    session,
                    verified,
                    ProfilePayload(**payload.model_dump()),
                )
                await session.commit()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    @app.get("/ping")
    async def ping():
        """Ultra-light anti-sleep endpoint for Render/UptimeRobot.

        It intentionally performs no database, Redis, Telegram or filesystem I/O.
        """
        return {
            "status": "ok",
            "service": "CampusPass IQ",
            "version": __version__,
            "telegram_bot_api_target": TELEGRAM_BOT_API_TARGET,
            "aiogram_target": AIOGRAM_TARGET,
            "checked_at": datetime.now(UTC).isoformat(),
        }

    @app.head("/ping")
    async def ping_head():
        return Response(status_code=204, headers={"Cache-Control": "no-store"})

    @app.get("/health/live")
    async def health_live():
        # Render deployment probe: process/API is alive. Database and Telegram
        # readiness are intentionally checked by /health/ready instead.
        return {
            "status": "ok",
            "version": __version__,
            "telegram_bot_api_target": TELEGRAM_BOT_API_TARGET,
            "aiogram_target": AIOGRAM_TARGET,
            "checked_at": datetime.now(UTC).isoformat(),
        }

    async def database_health_response():
        try:
            async with context.database.session_factory() as session:
                await session.execute(text("SELECT 1"))
            return JSONResponse({"status": "ok", "version": __version__})
        except Exception:
            logger.exception("database health probe failed")
            return JSONResponse({"status": "error", "version": __version__}, status_code=503)

    async def readiness_response():
        expected_bot = context.settings.runtime_mode in {"combined", "bot"}
        expected_worker = context.settings.runtime_mode in {"combined", "worker"}
        webhook_required = expected_bot and context.settings.telegram_delivery_mode == "webhook"
        try:
            async with context.database.session_factory() as session:
                live_gate = await context.services.deployment_gates.run(
                    session,
                    redis_client=context.redis_client,
                    include_telegram=False,
                    include_webhook=False,
                    include_worker=True,
                    persist=False,
                )
        except Exception as exc:
            live_gate = {"ok": False, "checks": {"gate": {"ok": False, "error": type(exc).__name__}}}
        components = {
            "database": context.database_ready,
            "redis": context.redis_ready if context.settings.require_redis_in_production else "optional",
            "bot": context.bot_ready if expected_bot else "not_required",
            "worker": context.worker_ready if expected_worker else "external",
            "release": context.release_registered,
            "webhook": context.webhook_ready if webhook_required else "not_required",
            "update_processor": context.update_processor_ready if webhook_required else "not_required",
            "update_inflight": context.update_inflight,
            "draining": context.draining,
            "deployment_gate": bool(live_gate.get("ok")),
        }
        components_ready = (
            context.database_ready
            and (not context.settings.require_redis_in_production or context.redis_ready)
            and (not expected_bot or context.bot_ready)
            and (not expected_worker or context.worker_ready)
            and (not webhook_required or (context.webhook_ready and context.update_processor_ready))
            and context.release_registered
            and not context.draining
            and bool(live_gate.get("ok"))
        )
        if not context.ready or not components_ready:
            return JSONResponse(
                {
                    "status": "starting" if not context.startup_error else "error",
                    "version": __version__,
                    "release_id": context.settings.release_id,
                    "runtime_mode": context.settings.runtime_mode,
                    "components": components,
                    "checks": live_gate.get("checks", {}),
                    "startup_error": context.startup_error or None,
                },
                status_code=503,
            )
        if context.settings.pilot_mode and context.settings.pilot_strict_startup:
            async with context.database.session_factory() as session:
                latest_validation = await context.services.pilot.latest(session)
            if not latest_validation or latest_validation.status != "passed":
                return JSONResponse(
                    {
                        "status": "pilot_validation_required",
                        "version": __version__,
                        "release_id": context.settings.release_id,
                        "validation_status": getattr(latest_validation, "status", "not_run"),
                    },
                    status_code=503,
                )
        return JSONResponse(
            {
                "status": "ok",
                "version": __version__,
                "release_id": context.settings.release_id,
                "runtime_mode": context.settings.runtime_mode,
                "components": components,
            },
            headers={"X-CampusPass-Release": context.settings.release_id, "Cache-Control": "no-store"},
        )

    @app.get("/health")
    async def health():
        # Backward-compatible database health endpoint. Render uses /ping and /health/live.
        return await database_health_response()

    @app.get("/health/ready")
    async def health_ready():
        return await readiness_response()

    def _require_operations_token(authorization: str, x_admin_token: str) -> None:
        supplied = x_admin_token.strip()
        if authorization.lower().startswith("bearer "):
            supplied = authorization.split(" ", 1)[1].strip()
        expected = context.settings.api_admin_token
        if not expected or not secrets.compare_digest(supplied, expected):
            raise HTTPException(401, "Unauthorized")

    @app.get("/health/deep")
    async def health_deep(
        authorization: str = Header(default=""),
        x_admin_token: str = Header(default=""),
    ):
        _require_operations_token(authorization, x_admin_token)
        async with context.database.session_factory() as session:
            result = await context.services.deployment_gates.run(
                session,
                redis_client=context.redis_client,
                include_telegram=context.settings.runtime_mode in {"combined", "bot"},
                include_webhook=True,
                include_worker=True,
                persist=True,
            )
            await session.commit()
        return JSONResponse(result, status_code=200 if result.get("ok") else 503)

    @app.get("/admin/deployment/gates/latest")
    async def latest_deployment_gate(
        authorization: str = Header(default=""),
        x_admin_token: str = Header(default=""),
    ):
        _require_operations_token(authorization, x_admin_token)
        async with context.database.session_factory() as session:
            row = await context.services.deployment_gates.latest(session)
        if row is None:
            raise HTTPException(404, "No deployment gate has been recorded")
        return {
            "public_id": row.public_id,
            "release_id": row.release_id,
            "environment": row.environment,
            "runtime_mode": row.runtime_mode,
            "status": row.status,
            "checks": row.checks_json,
            "error": row.error,
            "started_at": row.started_at.isoformat(),
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        }

    @app.get("/admin/update/status")
    async def update_status(
        authorization: str = Header(default=""),
        x_admin_token: str = Header(default=""),
    ):
        _require_operations_token(authorization, x_admin_token)
        async with context.database.session_factory() as session:
            compatibility = await session.scalar(
                select(ReleaseCompatibility).where(
                    ReleaseCompatibility.release_id == context.settings.release_id
                )
            )
            generations = list(
                (
                    await session.scalars(
                        select(RuntimeConfigGeneration).order_by(
                            RuntimeConfigGeneration.namespace
                        )
                    )
                ).all()
            )
        return {
            "version": __version__,
            "release_id": context.settings.release_id,
            "ready": context.ready,
            "draining": context.draining,
            "update_inflight": context.update_inflight,
            "compatibility": None
            if compatibility is None
            else {
                "status": compatibility.status,
                "schema_head": compatibility.schema_head,
                "minimum_release_version": compatibility.minimum_release_version,
                "minimum_schema_head": compatibility.minimum_schema_head,
                "callback_schema_version": compatibility.callback_schema_version,
                "event_schema_version": compatibility.event_schema_version,
                "rollout_percent": compatibility.rollout_percent,
                "checked_at": compatibility.checked_at.isoformat(),
                "last_error": compatibility.last_error,
            },
            "cache_generations": {row.namespace: row.generation for row in generations},
        }

    @app.get("/metrics", response_class=PlainTextResponse)
    async def metrics(
        authorization: str = Header(default=""),
        x_metrics_token: str = Header(default=""),
    ):
        if not context.settings.metrics_enabled:
            raise HTTPException(404)
        expected = context.settings.metrics_token
        if expected:
            supplied = x_metrics_token.strip()
            if authorization.lower().startswith("bearer "):
                supplied = authorization.split(" ", 1)[1].strip()
            if not secrets.compare_digest(supplied, expected):
                raise HTTPException(401, "Unauthorized")
        async with context.database.session_factory() as session:
            snapshot = await context.services.health.snapshot(session)
            await session.commit()
        operations = snapshot.get("operations", {})
        backup = operations.get("backup", {})
        delivery = snapshot.get("delivery_jobs", {})
        notifications = snapshot.get("notifications", {})
        values = {
            "campuspass_ready": 1 if context.ready else 0,
            "campuspass_database_ready": 1 if context.database_ready else 0,
            "campuspass_bot_ready": 1 if context.bot_ready else 0,
            "campuspass_worker_ready": 1 if context.worker_ready else 0,
            "campuspass_draining": 1 if context.draining else 0,
            "campuspass_telegram_update_inflight": int(context.update_inflight),
            "campuspass_delivery_pending": int(delivery.get("pending", 0)),
            "campuspass_delivery_failed": int(delivery.get("failed", 0)),
            "campuspass_notifications_failed": int(notifications.get("failed", 0)),
            "campuspass_open_incidents": int(operations.get("open_incidents", 0)),
            "campuspass_failed_scheduled_runs": int(operations.get("failed_scheduled_runs", 0)),
            "campuspass_backup_stale": 1 if backup.get("stale") else 0,
            "campuspass_payment_reviews": int(snapshot.get("payment_reviews", 0)),
            "campuspass_open_tickets": int(snapshot.get("open_tickets", 0)),
        }
        body = "\n".join(f"{key} {value}" for key, value in values.items()) + "\n"
        return PlainTextResponse(body, headers={"Cache-Control": "no-store"})

    @app.get("/admin/health")
    async def admin_health(
        authorization: str = Header(default=""),
        x_admin_token: str = Header(default=""),
    ):
        supplied = x_admin_token.strip()
        if authorization.lower().startswith("bearer "):
            supplied = authorization.split(" ", 1)[1].strip()
        expected = context.settings.api_admin_token
        if not expected or not secrets.compare_digest(supplied, expected):
            raise HTTPException(401, "Unauthorized")
        async with context.database.session_factory() as session:
            snapshot = await context.services.health.snapshot(session)
            await session.commit()
            return snapshot

    @app.get("/admin/operations")
    async def admin_operations(
        authorization: str = Header(default=""),
        x_admin_token: str = Header(default=""),
    ):
        supplied = x_admin_token.strip()
        if authorization.lower().startswith("bearer "):
            supplied = authorization.split(" ", 1)[1].strip()
        expected = context.settings.api_admin_token
        if not expected or not secrets.compare_digest(supplied, expected):
            raise HTTPException(401, "Unauthorized")
        async with context.database.session_factory() as session:
            return await context.services.operations.status_snapshot(session)

    @app.get("/admin/pilot")
    async def admin_pilot(
        authorization: str = Header(default=""),
        x_admin_token: str = Header(default=""),
    ):
        supplied = x_admin_token.strip()
        if authorization.lower().startswith("bearer "):
            supplied = authorization.split(" ", 1)[1].strip()
        expected = context.settings.api_admin_token
        if not expected or not secrets.compare_digest(supplied, expected):
            raise HTTPException(401, "Unauthorized")
        async with context.database.session_factory() as session:
            latest = await context.services.pilot.latest(session)
            if not latest:
                return {"status": "not_run", "pilot_mode": context.settings.pilot_mode}
            return {
                "status": latest.status,
                "pilot_mode": context.settings.pilot_mode,
                "blocking_failures": latest.blocking_failures,
                "warnings": latest.warnings,
                "checks": latest.checks_json,
                "completed_at": latest.completed_at.isoformat() if latest.completed_at else None,
            }

    @app.post("/admin/reports/{report_id}/revoke")
    async def revoke_report(
        report_id: int,
        authorization: str = Header(default=""),
        x_admin_token: str = Header(default=""),
    ):
        supplied = x_admin_token.strip()
        if authorization.lower().startswith("bearer "):
            supplied = authorization.split(" ", 1)[1].strip()
        expected = context.settings.api_admin_token
        if not expected or not secrets.compare_digest(supplied, expected):
            raise HTTPException(401, "Unauthorized")
        async with context.database.session_factory() as session:
            revoked = await context.services.reports.revoke_report(session, report_id)
            await session.commit()
        if not revoked:
            raise HTTPException(404, "Report access not found or already revoked")
        return {"ok": True, "report_id": report_id, "revoked": True}

    async def _load_report(token: str):
        async with context.database.session_factory() as session:
            row = await context.services.reports.resolve_report(session, token)
            if not row:
                raise HTTPException(
                    404, "Report not found, expired, revoked, or access limit reached"
                )
            verification_url = context.services.reports.report_url(token)
            await session.commit()
            return row, verification_url

    @app.get("/reports/{token}", response_class=HTMLResponse)
    async def report(token: str):
        row, verification_url = await _load_report(token)
        rendered = context.services.reports.render(row, verification_url=verification_url)
        return HTMLResponse(
            rendered,
            headers={
                "Cache-Control": "no-store, private",
                "Pragma": "no-cache",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": (
                    "default-src 'none'; img-src 'self' data: https:; "
                    "style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"
                ),
            },
        )

    @app.get("/reports/{token}/download/html", response_class=HTMLResponse)
    async def report_download_html(token: str):
        row, verification_url = await _load_report(token)
        rendered = context.services.reports.render(row, verification_url=verification_url)
        filename = context.services.reports.filename(row, "html")
        return HTMLResponse(
            rendered,
            headers={
                "Cache-Control": "no-store, private",
                "Pragma": "no-cache",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "no-referrer",
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Security-Policy": (
                    "default-src 'none'; img-src 'self' data: https:; "
                    "style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"
                ),
            },
        )

    @app.get("/reports/{token}/dashboard", response_class=HTMLResponse)
    async def report_dashboard(token: str):
        row, verification_url = await _load_report(token)
        if str(row.plan).lower() != "pro":
            raise HTTPException(403, "Secure dashboard is available for Pro reports only")
        rendered = context.services.reports.render(row, verification_url=verification_url)
        return HTMLResponse(rendered, headers={"Cache-Control": "no-store, private", "X-Frame-Options": "DENY"})

    @app.get("/reports/{token}/download/pdf")
    async def report_download_pdf(token: str):
        row, verification_url = await _load_report(token)
        if str(row.plan).lower() != "pro":
            raise HTTPException(403, "Official PDF is available for Pro reports only")
        artifact = await asyncio.to_thread(
            context.services.reports.render_artifact, row, verification_url=verification_url, format="pdf"
        )
        return Response(artifact.content, media_type=artifact.media_type, headers={
            "Cache-Control": "no-store, private", "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'attachment; filename="{artifact.filename}"',
        })

    @app.get("/reports/{token}/download/csv")
    async def report_download_csv_disabled(token: str):
        await _load_report(token)
        raise HTTPException(410, "CSV export was retired. Plus uses HTML and Pro uses PDF/Web App.")

    @app.get("/payments/return/{order_public_id}", response_class=HTMLResponse)
    async def payment_return(order_public_id: str):
        async with context.database.session_factory() as session:
            order = await context.services.orders.get_by_public_id(session, order_public_id[:40])
        if not order:
            raise HTTPException(404, "Order not found")
        status_label = {
            OrderStatus.PAID.value: "تم استلام الدفع بنجاح ✅",
            OrderStatus.WAITING_FULFILLMENT.value: "تم الدفع وجارٍ تجهيز الطلب ✅",
            OrderStatus.PROCESSING.value: "تم الدفع والطلب قيد التنفيذ ✅",
            OrderStatus.DELIVERED.value: "تم الدفع والتسليم ✅",
            OrderStatus.COMPLETED.value: "الطلب مكتمل ✅",
            OrderStatus.NEEDS_SUPPORT.value: "تم استلام العملية وتحتاج مراجعة الدعم",
        }.get(order.status, "ما زلنا ننتظر التأكيد النهائي من بوابة الدفع")
        body = (
            "<!doctype html><html lang='ar' dir='rtl'><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>حالة الدفع</title>"
            "<body style='font-family:system-ui;max-width:640px;margin:15vh auto;padding:24px;line-height:1.8'>"
            f"<h1>{html.escape(status_label)}</h1>"
            f"<p>رقم الطلب: <strong>{html.escape(order.public_id)}</strong></p>"
            "<p>ارجع إلى البوت لعرض التفاصيل ومتابعة التسليم.</p>"
            "</body></html>"
        )
        return HTMLResponse(body, headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY"})

    async def handle_payment_webhook(request: Request, x_signature: str) -> JSONResponse:
        if not context.settings.mastercard_ready:
            raise HTTPException(503, "Card payment connector is not configured")
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                declared_size = int(content_length)
            except ValueError as exc:
                raise HTTPException(400, "Invalid Content-Length") from exc
            if declared_size > context.settings.payment_webhook_max_body_bytes:
                raise HTTPException(413, "Payload too large")
        raw = await request.body()
        if len(raw) > context.settings.payment_webhook_max_body_bytes:
            raise HTTPException(413, "Payload too large")
        if not context.services.mastercard.verify_webhook(raw, x_signature):
            raise HTTPException(401, "Invalid signature")
        try:
            payload = orjson.loads(raw)
            notification = context.services.mastercard.parse_webhook(payload)
        except (orjson.JSONDecodeError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

        async with context.database.session_factory() as session:
            result = await context.services.payments.process_gateway_notification(
                session, notification
            )
            await session.commit()

        fulfillment = "not_required"
        if result.order and result.event.processing_status == "confirmed":
            # A webhook can be retried after a crash between payment commit and fulfillment.
            # Fulfillment is idempotent, so PAID orders are safe to resume here.
            async with context.database.session_factory() as session:
                order = await context.services.orders.get(session, result.order.id)
                if order and order.status == OrderStatus.PAID.value:
                    try:
                        friend_member = await context.services.friend_packages.member_for_order(
                            session, order.id
                        )
                        if friend_member is None:
                            await context.services.fulfillment.fulfill(session, order)
                            fulfillment = "queued"
                        else:
                            progress = await context.services.friend_packages.progress(
                                session, friend_member.group_id
                            )
                            student = await session.get(User, friend_member.user_id)
                            if student is not None:
                                await context.services.notifications.send_user(
                                    session, student,
                                    "تم تأكيد دفعتك في باقة الأصدقاء ✅",
                                    f"{progress.status_text}\n"
                                    "سيُرسل الحساب تلقائياً للجميع بعد اكتمال العدد.",
                                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                                        InlineKeyboardButton(
                                            text="👥 تحديث حالة الأصدقاء",
                                            callback_data=f"friend:progress:{friend_member.group_id}",
                                            style="primary",
                                        )
                                    ]]),
                                    idempotency_key=f"friend-gateway-payment-confirmed:{friend_member.id}",
                                )
                            fulfillment = "friend_group_waiting"
                        await session.commit()
                    except Exception as exc:
                        await session.rollback()
                        logger.exception("automatic fulfillment failed order=%s", order.id)
                        async with context.database.session_factory() as recovery:
                            recovery_order = await context.services.orders.get(recovery, order.id)
                            if recovery_order and recovery_order.status == OrderStatus.PAID.value:
                                await context.services.orders.change_status(
                                    recovery,
                                    recovery_order,
                                    OrderStatus.NEEDS_SUPPORT.value,
                                    note="فشل التجهيز التلقائي بعد الدفع الإلكتروني",
                                    metadata={"error": str(exc)[:500]},
                                )
                                await recovery.commit()
                        fulfillment = "support_required"

        if result.requires_review:
            message = (
                "⚠️ Webhook دفع يحتاج مراجعة\n"
                f"الطلب: {notification.order_public_id}\n"
                f"المرجع: {notification.reference}\n"
                f"السبب: {result.message}"
            )
            for admin_id in context.settings.admin_ids:
                try:
                    await context.bot.send_message(admin_id, message)
                except Exception:
                    logger.warning("Could not notify admin about payment webhook review")

        return JSONResponse(
            {
                "ok": True,
                "accepted": result.accepted,
                "duplicate": result.duplicate,
                "requires_review": result.requires_review,
                "fulfillment": fulfillment,
            },
            status_code=200 if result.accepted else 202,
        )

    @app.post("/webhooks/payments/mastercard")
    async def mastercard_payment_webhook(
        request: Request,
        x_signature: str = Header(default=""),
    ):
        return await handle_payment_webhook(request, x_signature)

    @app.post("/webhooks/payment")
    async def legacy_payment_webhook(
        request: Request,
        x_signature: str = Header(default=""),
    ):
        return await handle_payment_webhook(request, x_signature)


    def _require_admin_token(authorization: str, x_admin_token: str) -> None:
        supplied = x_admin_token.strip()
        if authorization.lower().startswith("bearer "):
            supplied = authorization.split(" ", 1)[1].strip()
        expected = context.settings.api_admin_token
        if not expected or not secrets.compare_digest(supplied, expected):
            raise HTTPException(401, "Unauthorized")

    @app.get("/admin/enterprise/dashboard")
    async def enterprise_dashboard(authorization: str = Header(default=""), x_admin_token: str = Header(default="")):
        _require_admin_token(authorization, x_admin_token)
        async with context.database.session_factory() as session:
            return await context.services.enterprise.dashboard(session)

    @app.post("/admin/enterprise/providers/{provider_id}/subscribe/{plan_code}")
    async def enterprise_subscribe(provider_id: int, plan_code: str, request: Request,
            authorization: str = Header(default=""), x_admin_token: str = Header(default="")):
        _require_admin_token(authorization, x_admin_token)
        payload = await request.json()
        idem = str(payload.get("idempotency_key", "")).strip()
        if not idem: raise HTTPException(422, "idempotency_key is required")
        async with context.database.session_factory() as session:
            row = await context.services.enterprise.subscribe(session, provider_id=provider_id,
                plan_code=plan_code, idempotency_key=idem)
            await session.commit()
            return {"public_id": row.public_id, "status": row.status, "period_end": row.current_period_end.isoformat()}

    @app.post("/admin/enterprise/invoices/{invoice_id}/paid")
    async def enterprise_mark_invoice_paid(invoice_id: int, request: Request,
            authorization: str = Header(default=""), x_admin_token: str = Header(default="")):
        _require_admin_token(authorization, x_admin_token)
        payload = await request.json(); idem = str(payload.get("idempotency_key", "")).strip()
        if not idem: raise HTTPException(422, "idempotency_key is required")
        async with context.database.session_factory() as session:
            try: row = await context.services.enterprise.mark_invoice_paid(session, invoice_id=invoice_id, payment_idempotency_key=idem)
            except ValueError as exc: raise HTTPException(404, str(exc)) from exc
            await session.commit(); return {"invoice_number": row.invoice_number, "status": row.status, "paid_iqd": row.paid_iqd}

    @app.get("/v1/provider/me")
    async def provider_api_me(x_api_key: str = Header(default="")):
        async with context.database.session_factory() as session:
            key = await context.services.enterprise.authenticate_api_key(session, x_api_key, "provider:read")
            if not key: raise HTTPException(401, "Invalid API key or scope")
            await session.commit()
            return {"provider_id": key.provider_id, "key_name": key.name, "scopes": key.scopes_json}

    @app.get("/admin/enterprise/scale")
    async def enterprise_scale_dashboard(authorization: str = Header(default=""), x_admin_token: str = Header(default="")):
        _require_admin_token(authorization, x_admin_token)
        async with context.database.session_factory() as session:
            return await context.services.enterprise_scale.dashboard(session)

    @app.get("/v1/provider/usage")
    async def provider_api_usage(x_api_key: str = Header(default="")):
        async with context.database.session_factory() as session:
            key = await context.services.enterprise.authenticate_api_key(session, x_api_key, "provider:read")
            if not key:
                raise HTTPException(401, "Invalid API key or scope")
            result = await context.services.enterprise_scale.record_usage(session, provider_id=key.provider_id,
                api_key_id=key.id, route="GET /v1/provider/usage",
                idempotency_key=f"usage-self:{key.id}:{datetime.now(UTC).isoformat()}")
            await session.commit()
            if not result["accepted"]:
                raise HTTPException(429, "Plan API request limit exceeded")
            return result

    return app
