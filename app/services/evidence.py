from __future__ import annotations

import asyncio
import io
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from aiogram import Bot
from aiogram.types import BufferedInputFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import SecretBox
from app.core.utils import public_id
from app.db.models import (
    Dispute,
    EvidenceAccessLog,
    EvidenceAsset,
    EvidenceStatus,
    Order,
    PaymentProof,
    Refund,
    SupportTicket,
    TicketMessage,
    User,
)


class EvidenceService:
    """Encrypted evidence registry with optional S3-compatible archival.

    Telegram file ids are encrypted at rest. When S3/R2/MinIO settings are
    supplied, the original bytes are downloaded, encrypted, hashed and stored
    outside the Telegram-only reference.
    """

    def __init__(self, bot: Bot, settings: Settings, secrets: SecretBox) -> None:
        self.bot = bot
        self.settings = settings
        self.secrets = secrets

    async def register_telegram(
        self,
        session: AsyncSession,
        creator: User,
        file_id: str,
        file_type: str,
        purpose: str,
        *,
        provider_id: int | None = None,
        order_id: int | None = None,
        dispute_id: int | None = None,
        ticket_id: int | None = None,
        original_name: str = "",
        mime_type: str | None = None,
        size_bytes: int | None = None,
    ) -> EvidenceAsset:
        now = datetime.now(UTC)
        asset = EvidenceAsset(
            public_id=public_id("EVD"),
            created_by_user_id=creator.id,
            provider_id=provider_id,
            order_id=order_id,
            dispute_id=dispute_id,
            ticket_id=ticket_id,
            purpose=purpose[:80],
            file_type=file_type[:30],
            original_name=original_name[:255],
            mime_type=mime_type,
            size_bytes=size_bytes,
            encrypted_telegram_file_id=self.secrets.encrypt(file_id),
            storage_backend="telegram",
            status=EvidenceStatus.REGISTERED.value,
            encryption_key_version=1,
            retention_until=now
            + timedelta(days=max(1, self.settings.evidence_retention_days)),
        )
        session.add(asset)
        await session.flush()
        return asset

    async def attach_entity(
        self,
        session: AsyncSession,
        asset: EvidenceAsset,
        *,
        provider_id: int | None = None,
        order_id: int | None = None,
        dispute_id: int | None = None,
        ticket_id: int | None = None,
    ) -> None:
        asset.provider_id = provider_id if provider_id is not None else asset.provider_id
        asset.order_id = order_id if order_id is not None else asset.order_id
        asset.dispute_id = dispute_id if dispute_id is not None else asset.dispute_id
        asset.ticket_id = ticket_id if ticket_id is not None else asset.ticket_id
        await session.flush()

    async def _access(
        self,
        session: AsyncSession,
        asset: EvidenceAsset,
        actor: User | None,
        purpose: str,
        outcome: str = "allowed",
    ) -> None:
        asset.access_count += 1
        asset.last_access_at = datetime.now(UTC)
        session.add(
            EvidenceAccessLog(
                evidence_asset_id=asset.id,
                actor_user_id=actor.id if actor else None,
                purpose=purpose[:160],
                outcome=outcome[:30],
            )
        )
        await session.flush()

    async def telegram_file_id(
        self,
        session: AsyncSession,
        asset: EvidenceAsset,
        actor: User | None,
        purpose: str,
    ) -> str:
        if asset.status == EvidenceStatus.DELETED.value:
            raise ValueError("الدليل حُذف وفق سياسة الاحتفاظ")
        await self._access(session, asset, actor, purpose)
        return self.secrets.decrypt(asset.encrypted_telegram_file_id)

    async def send(
        self,
        session: AsyncSession,
        asset: EvidenceAsset,
        actor: User | None,
        chat_id: int,
        caption: str,
        reply_markup=None,
    ) -> None:
        if asset.storage_backend == "s3" and asset.storage_key:
            payload = await self._download_s3(asset.storage_key)
            await self._access(session, asset, actor, "send_evidence_from_s3")
            file = BufferedInputFile(payload, filename=asset.original_name or f"{asset.public_id}.bin")
            if asset.file_type == "photo":
                await self.bot.send_photo(chat_id, file, caption=caption, reply_markup=reply_markup)
            else:
                await self.bot.send_document(chat_id, file, caption=caption, reply_markup=reply_markup)
            return
        file_id = await self.telegram_file_id(session, asset, actor, "send_evidence_from_telegram")
        if asset.file_type == "photo":
            await self.bot.send_photo(chat_id, file_id, caption=caption, reply_markup=reply_markup)
        else:
            await self.bot.send_document(chat_id, file_id, caption=caption, reply_markup=reply_markup)

    def _s3_client(self):
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - deployment dependency
            raise RuntimeError("boto3 is required for external evidence storage") from exc
        return boto3.client(
            "s3",
            endpoint_url=self.settings.evidence_s3_endpoint or None,
            aws_access_key_id=self.settings.evidence_s3_access_key,
            aws_secret_access_key=self.settings.evidence_s3_secret_key,
            region_name=self.settings.evidence_s3_region,
        )

    async def archive(self, session: AsyncSession, asset: EvidenceAsset) -> bool:
        if asset.status == EvidenceStatus.DELETED.value:
            return False
        if not self.settings.evidence_external_storage_ready:
            return False
        file_id = self.secrets.decrypt(asset.encrypted_telegram_file_id)
        buffer = io.BytesIO()
        await self.bot.download(file_id, destination=buffer)
        raw = buffer.getvalue()
        digest = self.secrets.hash_value(raw)
        encrypted = self.secrets.encrypt_bytes(raw)
        key = f"evidence/{datetime.now(UTC):%Y/%m}/{asset.public_id}-{uuid.uuid4().hex}.bin"
        client = self._s3_client()
        await asyncio.to_thread(
            client.put_object,
            Bucket=self.settings.evidence_s3_bucket,
            Key=key,
            Body=encrypted,
            ContentType="application/octet-stream",
            Metadata={"sha256": digest, "encrypted": "fernet-v1"},
        )
        asset.storage_backend = "s3"
        asset.storage_key = key
        asset.content_sha256 = digest
        asset.size_bytes = len(raw)
        asset.status = EvidenceStatus.ARCHIVED.value
        asset.archived_at = datetime.now(UTC)
        await session.flush()
        return True

    async def _download_s3(self, key: str) -> bytes:
        client = self._s3_client()
        response: dict[str, Any] = await asyncio.to_thread(
            client.get_object, Bucket=self.settings.evidence_s3_bucket, Key=key
        )
        encrypted = await asyncio.to_thread(response["Body"].read)
        return self.secrets.decrypt_bytes(encrypted)

    async def archive_pending(self, session: AsyncSession, limit: int = 10) -> int:
        if not self.settings.evidence_external_storage_ready:
            return 0
        assets = list(
            (
                await session.scalars(
                    select(EvidenceAsset)
                    .where(EvidenceAsset.status == EvidenceStatus.REGISTERED.value)
                    .order_by(EvidenceAsset.id)
                    .limit(max(1, min(limit, 50)))
                )
            ).all()
        )
        done = 0
        for asset in assets:
            try:
                if await self.archive(session, asset):
                    done += 1
            except Exception as exc:
                asset.status = EvidenceStatus.FAILED.value
                asset.last_error = f"{type(exc).__name__}: {exc}"[:1000]
                await session.flush()
        return done

    async def purge_expired(self, session: AsyncSession, limit: int = 50) -> int:
        now = datetime.now(UTC)
        assets = list(
            (
                await session.scalars(
                    select(EvidenceAsset)
                    .where(
                        EvidenceAsset.retention_until <= now,
                        EvidenceAsset.status != EvidenceStatus.DELETED.value,
                    )
                    .order_by(EvidenceAsset.retention_until)
                    .limit(max(1, min(limit, 200)))
                )
            ).all()
        )
        count = 0
        client = self._s3_client() if self.settings.evidence_external_storage_ready else None
        for asset in assets:
            if client and asset.storage_key:
                try:
                    await asyncio.to_thread(
                        client.delete_object,
                        Bucket=self.settings.evidence_s3_bucket,
                        Key=asset.storage_key,
                    )
                except Exception as exc:
                    asset.last_error = f"delete failed: {type(exc).__name__}: {exc}"[:1000]
                    continue
            asset.encrypted_telegram_file_id = ""
            asset.storage_key = ""
            asset.status = EvidenceStatus.DELETED.value
            asset.deleted_at = now
            count += 1
        await session.flush()
        return count

    async def migrate_legacy_references(
        self, session: AsyncSession, limit: int = 200
    ) -> int:
        """Move old plaintext Telegram file ids into the encrypted evidence registry.

        The migration is bounded and idempotent: rows already linked to an
        EvidenceAsset are skipped, and plaintext legacy columns are cleared only
        after the encrypted record has been flushed successfully.
        """
        remaining = max(1, min(int(limit), 500))
        migrated = 0

        proofs = list(
            (
                await session.scalars(
                    select(PaymentProof)
                    .where(
                        PaymentProof.evidence_asset_id.is_(None),
                        (PaymentProof.photo_file_id.is_not(None))
                        | (PaymentProof.document_file_id.is_not(None)),
                    )
                    .order_by(PaymentProof.id)
                    .limit(remaining)
                )
            ).all()
        )
        for proof in proofs:
            order = await session.get(Order, proof.order_id)
            creator = await session.get(User, order.user_id) if order else None
            file_id = proof.photo_file_id or proof.document_file_id
            if not order or not creator or not file_id:
                continue
            asset = await self.register_telegram(
                session,
                creator,
                file_id,
                "photo" if proof.photo_file_id else "document",
                "payment_proof_legacy",
                provider_id=order.provider_id,
                order_id=order.id,
            )
            proof.evidence_asset_id = asset.id
            proof.photo_file_id = None
            proof.document_file_id = None
            migrated += 1
        remaining -= len(proofs)
        if remaining <= 0:
            await session.flush()
            return migrated

        messages = list(
            (
                await session.scalars(
                    select(TicketMessage)
                    .where(
                        TicketMessage.evidence_asset_id.is_(None),
                        TicketMessage.file_id.is_not(None),
                    )
                    .order_by(TicketMessage.id)
                    .limit(remaining)
                )
            ).all()
        )
        for item in messages:
            ticket = await session.get(SupportTicket, item.ticket_id)
            creator_id = item.sender_user_id or (ticket.user_id if ticket else None)
            creator = await session.get(User, creator_id) if creator_id else None
            if not ticket or not creator or not item.file_id:
                continue
            asset = await self.register_telegram(
                session,
                creator,
                item.file_id,
                item.file_type or "document",
                "support_attachment_legacy",
                provider_id=ticket.provider_id,
                order_id=ticket.order_id,
                ticket_id=ticket.id,
            )
            item.evidence_asset_id = asset.id
            item.file_id = None
            migrated += 1
        remaining -= len(messages)
        if remaining <= 0:
            await session.flush()
            return migrated

        disputes = list(
            (
                await session.scalars(
                    select(Dispute)
                    .where(
                        Dispute.evidence_asset_id.is_(None),
                        Dispute.evidence_file_id.is_not(None),
                    )
                    .order_by(Dispute.id)
                    .limit(remaining)
                )
            ).all()
        )
        for dispute in disputes:
            creator = await session.get(User, dispute.user_id)
            if not creator or not dispute.evidence_file_id:
                continue
            asset = await self.register_telegram(
                session,
                creator,
                dispute.evidence_file_id,
                dispute.evidence_file_type or "document",
                "dispute_evidence_legacy",
                provider_id=dispute.provider_id,
                order_id=dispute.order_id,
                dispute_id=dispute.id,
            )
            dispute.evidence_asset_id = asset.id
            dispute.evidence_file_id = None
            migrated += 1
        remaining -= len(disputes)
        if remaining <= 0:
            await session.flush()
            return migrated

        refunds = list(
            (
                await session.scalars(
                    select(Refund)
                    .where(
                        Refund.proof_evidence_asset_id.is_(None),
                        Refund.proof_file_id.is_not(None),
                    )
                    .order_by(Refund.id)
                    .limit(remaining)
                )
            ).all()
        )
        for refund in refunds:
            creator_id = refund.transfer_reported_by_user_id or refund.user_id
            creator = await session.get(User, creator_id)
            if not creator or not refund.proof_file_id:
                continue
            asset = await self.register_telegram(
                session,
                creator,
                refund.proof_file_id,
                "document",
                "refund_transfer_proof_legacy",
                provider_id=refund.provider_id,
                order_id=refund.order_id,
                dispute_id=refund.dispute_id,
            )
            refund.proof_evidence_asset_id = asset.id
            refund.proof_file_id = None
            migrated += 1

        await session.flush()
        return migrated

