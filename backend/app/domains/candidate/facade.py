"""Public candidate-domain boundary used by interview; no HTTP/router coupling."""

import logging
from pathlib import Path

from app.domains.candidate.catalog import get_candidate_catalog
from app.domains.candidate.context import (
    candidate_context, candidate_preview, candidate_to_profile, job_context, job_preview, profile_context,
)
from app.shared.contracts import CandidateSessionContext
from app.shared.infrastructure.redis import RedisSessionManager

logger = logging.getLogger(__name__)

__all__ = ["CandidateDataNotFound", "load_session_context", "persist_candidate_selection", "sample_pair_metadata"]


class CandidateDataNotFound(ValueError):
    """Missing CV/job reference; the API layer chooses the transport status."""


def load_session_context(student_id: str, candidate_id: str | None = None, job_id: str | None = None) -> CandidateSessionContext:
    catalog = get_candidate_catalog()
    candidate, job = catalog.get_candidate(candidate_id), catalog.get_job(job_id)
    if candidate_id and not candidate:
        raise CandidateDataNotFound("Không tìm thấy CV mẫu trong normalized catalog")
    if job_id and not job:
        raise CandidateDataNotFound("Không tìm thấy JD mẫu trong normalized catalog")
    store = RedisSessionManager()
    memory = {}
    try:
        memory = store.get_cached_candidate_memory(student_id) or {}
    except Exception as exc:
        logger.debug("Could not retrieve candidate memory: %s", exc)
    if candidate:
        profile = candidate_to_profile(candidate)
        memory = {"candidate_name": profile["candidate_name"], "profile": profile,
                  "source": "normalized_interview_catalog", "source_candidate_id": candidate_id}
    else:
        profile = memory.get("profile", {}) if isinstance(memory, dict) else {}
    if not isinstance(memory, dict):
        memory = {}
    if not isinstance(profile, dict):
        profile = {}
    name = (profile.get("candidate_name") or memory.get("candidate_name") or student_id)
    return CandidateSessionContext(
        candidate_name=name, source_candidate_id=candidate_id, source_job_id=job_id,
        candidate_role_id=(candidate or {}).get("canonical_role_id"),
        job_role_id=(job or {}).get("canonical_role_id"),
        candidate_framework_id=(candidate or {}).get("framework_id"),
        job_framework_id=(job or {}).get("framework_id"),
        candidate_context=candidate_context(candidate) if candidate else profile_context(profile),
        job_context=job_context(job),
    )


def persist_candidate_selection(student_id: str, candidate_id: str | None) -> None:
    """Persist only after the interview has validated the selected framework/JD."""
    if not candidate_id:
        return
    record = get_candidate_catalog().get_candidate(candidate_id)
    if not record:
        raise CandidateDataNotFound("Không tìm thấy CV mẫu trong normalized catalog")
    profile = candidate_to_profile(record)
    try:
        RedisSessionManager().cache_candidate_memory(student_id, {
            "candidate_name": profile["candidate_name"], "profile": profile,
            "source": "normalized_interview_catalog", "source_candidate_id": candidate_id,
        })
    except Exception as exc:
        logger.warning("Could not cache selected candidate profile: %s", exc)


def sample_pair_metadata(framework: dict, data_dir: str | Path | None = None) -> dict | None:
    pair = get_candidate_catalog(data_dir).sample_pair_for_framework(framework)
    if not pair:
        return None
    return {"candidate": candidate_preview(pair["candidate"]), "job": job_preview(pair["job"])}
