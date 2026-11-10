"""Offline research data failures; callers must stop rather than remove failing stocks."""

from __future__ import annotations


class DataFormatError(ValueError):
    """T-R58d §2.2/§2.7: an invalid format or splice forbids producing results."""
