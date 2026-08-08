from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RenderedArtifact:
    format: str
    content: bytes
    media_type: str
    filename: str
    sha256: str


class ReportArtifactRenderer:
    """Pure renderer used by bot, API and workers.

    WeasyPrint is imported lazily so Free/Plus HTML remains available even when
    an operating-system PDF dependency is temporarily unavailable.
    """

    @staticmethod
    def html(content: str, filename: str) -> RenderedArtifact:
        payload = content.encode("utf-8")
        return RenderedArtifact(
            format="html",
            content=payload,
            media_type="text/html; charset=utf-8",
            filename=filename,
            sha256=hashlib.sha256(payload).hexdigest(),
        )

    @staticmethod
    def pdf(content: str, filename: str, *, base_url: str | None = None) -> RenderedArtifact:
        try:
            from weasyprint import HTML
        except ImportError as exc:  # pragma: no cover - production dependency gate
            raise RuntimeError("WeasyPrint is required for Pro PDF reports") from exc
        payload = HTML(string=content, base_url=base_url).write_pdf(
            pdf_variant="pdf/a-3u",
            custom_metadata=True,
        )
        if not payload.startswith(b"%PDF"):
            raise RuntimeError("PDF renderer returned invalid output")
        return RenderedArtifact(
            format="pdf",
            content=payload,
            media_type="application/pdf",
            filename=filename,
            sha256=hashlib.sha256(payload).hexdigest(),
        )

    @staticmethod
    def manifest(artifact: RenderedArtifact) -> dict[str, Any]:
        return {
            "format": artifact.format,
            "filename": artifact.filename,
            "media_type": artifact.media_type,
            "sha256": artifact.sha256,
            "byte_size": len(artifact.content),
        }
