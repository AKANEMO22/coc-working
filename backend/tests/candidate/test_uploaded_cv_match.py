"""Uploaded CV role/level metadata limits JD choices without user filters."""

from app.domains.candidate.api import _uploaded_cv_match
from app.domains.interview.catalog import get_interview_catalog


def test_uploaded_cv_match_requires_explicit_supported_role_and_level():
    resolved = _uploaded_cv_match({"target_role": "Java Backend Developer", "current_level": "fresher"})
    assert resolved == {
        "target_role": "Java Backend Developer", "experience_level": "Fresher",
        "resolved_framework_id": "IF_BE_JAVA",
    }
    missing = _uploaded_cv_match({"skills": {"hard_skills": ["Java"]}})
    assert missing == {"target_role": None, "experience_level": None, "resolved_framework_id": None}


def test_broad_uploaded_cv_role_does_not_guess_framework():
    catalog = get_interview_catalog()
    assert catalog.resolve_uploaded_cv_role("Engineer") is None
    assert catalog.resolve_uploaded_cv_role("Frontend Developer")["position_id"] == "IF_FE"
