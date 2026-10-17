"""Public framework/guidance boundary for candidate preparation and adapters."""

from app.domains.interview.catalog import get_interview_catalog, framework_context
from app.domains.interview.services.guidance import copies_reference, framework_guidance

__all__ = ["get_interview_catalog", "framework_context", "copies_reference", "framework_guidance"]
