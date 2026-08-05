"""Backward-compatible imports for old tests and third-party helpers.

The production application uses :mod:`app.core.utils`. New code must import from
that module directly. This shim can be removed after all external integrations
have migrated.
"""

from app.core.utils import normalize_phone, safe, validate_full_name

__all__ = ["normalize_phone", "safe", "validate_full_name"]
