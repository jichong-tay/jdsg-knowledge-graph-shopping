"""Shared parser errors for deterministic vendor adapters."""


class UnsupportedEmailError(ValueError):
    """An email is not an unambiguous supported shopping transaction."""
