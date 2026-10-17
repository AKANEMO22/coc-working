"""Candidate domain owns CV/job records and sample selection from loaded data."""

from functools import lru_cache
from pathlib import Path
from typing import Any

from app.shared.infrastructure.normalized_data import get_normalized_data_store
from app.shared.text import token_similarity as _similarity
from app.domains.candidate.context import _as_strings, candidate_preview, job_preview


class CandidateCatalog:
    def __init__(self, data_dir: str | Path | None = None):
        self.store = get_normalized_data_store(data_dir)
        self.data_dir = self.store.data_dir

    def candidates(self) -> list[dict[str, Any]]:
        return self.store.read_records("candidates")

    def jobs(self) -> list[dict[str, Any]]:
        return self.store.read_records("jobs")

    def selection_options(self) -> dict[str, Any]:
        """Independent, allowlisted CV/JD choices, not one preselected pair."""
        candidates = [
            {**candidate_preview(row), "canonical_role_id": row.get("canonical_role_id"), "framework_id": row.get("framework_id")}
            for row in self.candidates() if row.get("candidate_id")
        ]
        jobs = [
            {**job_preview(row), "canonical_role_id": row.get("canonical_role_id"), "canonical_role_name": row.get("canonical_role_name"), "framework_id": row.get("framework_id")}
            for row in self.jobs() if row.get("job_id")
        ]
        return {"available": bool(candidates and jobs), "candidates": candidates, "jobs": jobs}

    def get_candidate(self, candidate_id: str | None) -> dict[str, Any] | None:
        if not candidate_id:
            return None
        return next((row for row in self.candidates() if row.get("candidate_id") == candidate_id), None)


    def get_job(self, job_id: str | None) -> dict[str, Any] | None:
        if not job_id:
            return None
        return next((row for row in self.jobs() if row.get("job_id") == job_id), None)


    def sample_pair_for_framework(self, framework: dict[str, Any]) -> dict[str, Any] | None:
        framework_id = str(framework.get("position_id", ""))
        canonical_id = framework.get("canonical_role_id")

        candidates = [
            row for row in self.candidates()
            if row.get("framework_id") == framework_id or (canonical_id and row.get("canonical_role_id") == canonical_id)
        ]
        jobs = [
            row for row in self.jobs()
            if row.get("framework_id") == framework_id or (canonical_id and row.get("canonical_role_id") == canonical_id)
        ]
        if not candidates or not jobs:
            return None

        # Prefer an actual CV with project evidence and a JD whose title/level
        # fits the chosen framework; retain stable source order for ties.
        role_title = str(framework.get("role_title", ""))
        candidate = max(candidates, key=lambda row: (
            int(row.get("framework_id") == framework_id),
            _similarity(role_title, str(row.get("target_role", ""))),
            len(row.get("projects") or []),
            len(row.get("work_experience") or []),
            len(_as_strings(row.get("technical_skills"))),
            -self.candidates().index(row),
        ))
        candidate_role = str(candidate.get("target_role", ""))
        job = max(jobs, key=lambda row: (
            int(row.get("framework_id") == framework_id),
            _similarity(role_title, str(row.get("job_title") or row.get("normalized_job_title", "")))
            + _similarity(candidate_role, str(row.get("job_title") or row.get("normalized_job_title", ""))),
            int(str(row.get("required_level", "")).casefold() in {"fresher", "junior", "intern", "entry"}),
            -self.jobs().index(row),
        ))
        return {"framework": framework, "candidate": candidate, "job": job}



@lru_cache(maxsize=8)
def get_candidate_catalog(data_dir: str | Path | None = None) -> CandidateCatalog:
    return CandidateCatalog(data_dir)
