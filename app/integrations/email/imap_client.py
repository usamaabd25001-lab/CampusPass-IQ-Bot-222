from __future__ import annotations

import asyncio
import email
import imaplib
import logging
import re
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from email.header import decode_header
from email.utils import parsedate_to_datetime
from html import unescape

from app.core.utils import extract_code

logger = logging.getLogger(__name__)

DEFAULT_CONNECT_TIMEOUT = 15.0
DEFAULT_OPERATION_TIMEOUT = 25.0


class IMAPClientError(RuntimeError):
    """Safe, user-presentable IMAP failure without credential disclosure."""


class IMAPTimeoutError(IMAPClientError):
    pass


class IMAPAuthenticationError(IMAPClientError):
    pass


@dataclass(slots=True)
class EmailCandidate:
    uid: str
    message_id: str
    sender: str
    subject: str
    received_at: datetime
    code: str


def _decode_header(value: str | None) -> str:
    parts: list[str] = []
    for chunk, encoding in decode_header(value or ""):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(encoding or "utf-8", errors="replace"))
        else:
            parts.append(chunk)
    return "".join(parts)


def _body_text(message: email.message.Message) -> str:
    chunks: list[str] = []
    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            if content_type not in {"text/plain", "text/html"}:
                continue
            if "attachment" in (part.get("Content-Disposition") or "").lower():
                continue
            payload = part.get_payload(decode=True) or b""
            charset = part.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            if content_type == "text/html":
                text = re.sub(r"<[^>]+>", " ", text)
                text = unescape(text)
            chunks.append(text)
    else:
        payload = message.get_payload(decode=True) or b""
        charset = message.get_content_charset() or "utf-8"
        chunks.append(payload.decode(charset, errors="replace"))
    return "\n".join(chunks)


def _safe_received_at(message: email.message.Message) -> datetime:
    try:
        received = parsedate_to_datetime(message.get("Date"))
        if received.tzinfo is None:
            received = received.replace(tzinfo=UTC)
        return received.astimezone(UTC)
    except Exception:
        return datetime.now(UTC)


def _connect(host: str, port: int, timeout: float) -> imaplib.IMAP4_SSL:
    try:
        return imaplib.IMAP4_SSL(host, port, timeout=timeout)
    except (TimeoutError, socket.timeout) as exc:
        raise IMAPTimeoutError("انتهت مهلة الاتصال بخادم البريد") from exc
    except OSError as exc:
        raise IMAPClientError("تعذر الاتصال بخادم البريد") from exc


def fetch_candidates_sync(
    host: str,
    port: int,
    username: str,
    password: str,
    since: datetime,
    sender_filter: str | None,
    subject_regex: str | None,
    code_regex: str,
    max_messages: int = 30,
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
) -> list[EmailCandidate]:
    """Blocking IMAP implementation; call only through ``fetch_candidates``."""
    connection = _connect(host, port, connect_timeout)
    try:
        try:
            connection.login(username, password)
        except imaplib.IMAP4.error as exc:
            raise IMAPAuthenticationError(
                "رفض مزود البريد تسجيل الدخول. تحقق من App Password وإعدادات IMAP."
            ) from exc

        status, _ = connection.select("INBOX", readonly=True)
        if status != "OK":
            raise IMAPClientError("تم تسجيل الدخول لكن تعذر فتح صندوق الوارد")

        since_utc = since.astimezone(UTC) if since.tzinfo else since.replace(tzinfo=UTC)
        since_date = since_utc.strftime("%d-%b-%Y")
        status, data = connection.uid("search", None, f'(SINCE "{since_date}")')
        if status != "OK" or not data:
            return []

        uids = data[0].split()[-max(1, min(max_messages, 100)) :]
        results: list[EmailCandidate] = []
        for raw_uid in reversed(uids):
            uid = raw_uid.decode(errors="replace")
            status, message_data = connection.uid("fetch", raw_uid, "(RFC822)")
            if status != "OK" or not message_data or not isinstance(message_data[0], tuple):
                continue

            msg = email.message_from_bytes(message_data[0][1])
            sender = _decode_header(msg.get("From"))
            subject = _decode_header(msg.get("Subject"))
            if sender_filter and sender_filter.lower() not in sender.lower():
                continue
            try:
                if subject_regex and not re.search(subject_regex, subject, re.IGNORECASE):
                    continue
            except re.error as exc:
                raise IMAPClientError("نمط عنوان رسالة التحقق غير صالح") from exc

            received = _safe_received_at(msg)
            if received < since_utc:
                continue
            try:
                code = extract_code(f"{subject}\n{_body_text(msg)}", code_regex)
            except re.error as exc:
                raise IMAPClientError("نمط استخراج رمز التحقق غير صالح") from exc
            if not code:
                continue
            results.append(
                EmailCandidate(
                    uid=uid,
                    message_id=msg.get("Message-ID", ""),
                    sender=sender,
                    subject=subject,
                    received_at=received,
                    code=code,
                )
            )
        return sorted(results, key=lambda item: item.received_at, reverse=True)
    except (TimeoutError, socket.timeout) as exc:
        raise IMAPTimeoutError("انتهت مهلة قراءة صندوق البريد") from exc
    finally:
        try:
            connection.logout()
        except Exception as exc:
            logger.debug("IMAP logout failed: %s", type(exc).__name__)


def test_connection_sync(
    host: str,
    port: int,
    username: str,
    password: str,
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
) -> tuple[bool, str]:
    """Verify credentials without reading messages."""
    connection: imaplib.IMAP4_SSL | None = None
    try:
        connection = _connect(host, port, connect_timeout)
        connection.login(username, password)
        status, _ = connection.select("INBOX", readonly=True)
        if status != "OK":
            return False, "تم تسجيل الدخول لكن تعذر فتح صندوق الوارد"
        return True, "تم الاتصال بصندوق الوارد بنجاح"
    except IMAPClientError as exc:
        return False, str(exc)
    except imaplib.IMAP4.error:
        return False, "رفض مزود البريد تسجيل الدخول. تحقق من App Password وإعدادات IMAP."
    except (TimeoutError, socket.timeout):
        return False, "انتهت مهلة الاتصال بخادم البريد"
    except OSError:
        return False, "تعذر الاتصال بخادم البريد"
    except Exception as exc:
        logger.exception("Unexpected IMAP connection test failure: %s", type(exc).__name__)
        return False, "حدث خطأ غير متوقع أثناء اختبار البريد"
    finally:
        if connection is not None:
            try:
                connection.logout()
            except Exception:
                pass


async def fetch_candidates(
    host: str,
    port: int,
    username: str,
    password: str,
    since: datetime,
    sender_filter: str | None,
    subject_regex: str | None,
    code_regex: str,
    max_messages: int = 30,
    timeout: float = DEFAULT_OPERATION_TIMEOUT,
) -> list[EmailCandidate]:
    """Fully non-blocking API for the bot event loop."""
    try:
        async with asyncio.timeout(max(5.0, timeout)):
            return await asyncio.to_thread(
                fetch_candidates_sync,
                host,
                port,
                username,
                password,
                since,
                sender_filter,
                subject_regex,
                code_regex,
                max_messages,
                min(DEFAULT_CONNECT_TIMEOUT, max(5.0, timeout)),
            )
    except TimeoutError as exc:
        raise IMAPTimeoutError("انتهت مهلة انتظار رسالة التحقق") from exc


async def test_connection(
    host: str,
    port: int,
    username: str,
    password: str,
    timeout: float = 20.0,
) -> tuple[bool, str]:
    try:
        async with asyncio.timeout(max(5.0, timeout)):
            return await asyncio.to_thread(
                test_connection_sync,
                host,
                port,
                username,
                password,
                min(DEFAULT_CONNECT_TIMEOUT, max(5.0, timeout)),
            )
    except TimeoutError:
        return False, "انتهت مهلة الاتصال بخادم البريد. حاول مرة أخرى لاحقًا."
