from __future__ import annotations


class CampusPassError(Exception):
    """Base error for expected business-rule failures."""


class AuthorizationError(CampusPassError):
    """The current actor is authenticated but cannot perform the operation."""


class ResourceNotFoundError(CampusPassError):
    """The requested resource is missing or intentionally hidden by tenant scope."""


class BusinessConflictError(CampusPassError):
    """The requested operation conflicts with the current resource state."""


class FeatureDisabledError(CampusPassError):
    """The feature is deliberately disabled for this deployment or plan."""
