"""Sanitized candidate/CV/JD projections; raw contact and CV text stay in candidate domain."""

from typing import Any
import re

JOB_LEVELS = ("Intern", "Fresher", "Junior", "Mid", "Senior")


def job_levels(job: dict[str, Any]) -> list[str]:
    """Only explicitly supported hiring levels; never infer Intern from 0 years.

    Conflicting declared/normalized levels cannot qualify for a level filter.
    A declared Intern/Fresher with >=2 years required is not entry-level eligible.
    """
    names = {level.casefold(): level for level in JOB_LEVELS}
    raw = job.get("declared_levels")
    parts = raw if isinstance(raw, list) else re.split(r"[,/;|]", str(raw or ""))
    declared = {names[str(part).strip().casefold()] for part in parts if str(part).strip().casefold() in names}
    required = names.get(str(job.get("required_level") or "").strip().casefold())
    if declared and required and required not in declared:
        return []
    levels = declared or ({required} if required else set())
    try:
        if float(job.get("min_years") or 0) >= 2:
            levels -= {"Intern", "Fresher"}
    except (ValueError, TypeError):
        pass
    return [level for level in JOB_LEVELS if level in levels]

def candidate_to_profile(candidate: dict[str, Any]) -> dict[str, Any]:
    """Convert normalized candidate data into the app's CV shape without PII/raw CV."""
    projects = _safe_records(
        candidate.get("projects"),
        ("name", "project_name", "role", "technologies", "description", "results"),
    )
    work = _safe_records(
        candidate.get("work_experience"),
        ("title", "role", "company", "description", "achievements", "start_date", "end_date"),
    )
    education = _safe_records(
        candidate.get("education"),
        ("degree", "university", "major", "gpa", "graduation_year", "start_year", "end_year"),
    )
    return {
        "candidate_name": str(candidate.get("candidate_id") or "Candidate"),
        "education": education,
        "skills": {
            "hard_skills": _as_strings(candidate.get("technical_skills")),
            "soft_skills": _as_strings(candidate.get("soft_skills")),
            "tools": _as_strings(candidate.get("certifications")),
        },
        "projects": projects if isinstance(projects, list) else [],
        "work_experience": work if isinstance(work, list) else [],
        "career_objective": candidate.get("career_objective", ""),
        "source_candidate_id": candidate.get("candidate_id"),
    }


def candidate_context(candidate: dict[str, Any] | None) -> dict[str, Any]:
    if not candidate:
        return {}
    profile = candidate_to_profile(candidate)
    skills = profile.get("skills", {})
    projects = []
    for item in profile.get("projects", [])[:5]:
        if not isinstance(item, dict):
            continue
        projects.append({key: item.get(key) for key in ("name", "role", "technologies", "description", "results") if item.get(key)})
    experience = []
    for item in profile.get("work_experience", [])[:3]:
        if not isinstance(item, dict):
            continue
        experience.append({key: item.get(key) for key in ("title", "role", "company", "description", "achievements") if item.get(key)})
    return {
        "candidate_id": candidate.get("candidate_id"),
        "target_role": candidate.get("target_role"),
        "experience_level": candidate.get("current_level"),
        "years_of_experience": candidate.get("years_of_experience"),
        "skills": skills,
        "projects": projects,
        "experience": experience,
        "career_objective": profile.get("career_objective"),
    }


def profile_context(profile: dict[str, Any] | None) -> dict[str, Any]:
    """Create an interview-only projection from an uploaded CV profile."""
    if not profile:
        return {}
    skills = profile.get("skills") or {}
    projects = []
    for item in profile.get("projects", [])[:5]:
        if not isinstance(item, dict):
            continue
        projects.append({key: item.get(key) for key in ("name", "role", "technologies", "description", "results") if item.get(key)})
    experience = []
    for item in profile.get("work_experience", profile.get("experience", []))[:3]:
        if not isinstance(item, dict):
            continue
        experience.append({key: item.get(key) for key in ("title", "role", "company", "description", "achievements") if item.get(key)})
    return {
        "target_role": profile.get("target_role"),
        "experience_level": profile.get("current_level"),
        "skills": skills if isinstance(skills, dict) else {"hard_skills": _as_strings(skills)},
        "projects": projects,
        "experience": experience,
        "career_objective": profile.get("career_objective", ""),
    }


def job_context(job: dict[str, Any] | None) -> dict[str, Any]:
    if not job:
        return {}
    return {
        "job_id": job.get("job_id"),
        "title": job.get("job_title") or job.get("normalized_job_title"),
        "company": job.get("company_name"),
        "level": job.get("required_level"),
        "levels": job_levels(job),
        "min_years": job.get("min_years"),
        "max_years": job.get("max_years"),
        "required_skills": _as_strings(job.get("skills_required")),
    }


def candidate_preview(candidate: dict[str, Any] | None) -> dict[str, Any] | None:
    if not candidate:
        return None
    return {
        "candidate_id": candidate.get("candidate_id"),
        "target_role": candidate.get("target_role"),
        "experience_level": candidate.get("current_level"),
        "skills": _as_strings(candidate.get("technical_skills"))[:12],
        "project_count": len(candidate.get("projects") or []),
    }


def job_preview(job: dict[str, Any] | None) -> dict[str, Any] | None:
    if not job:
        return None
    return {
        "job_id": job.get("job_id"),
        "title": job.get("job_title") or job.get("normalized_job_title"),
        "company": job.get("company_name"),
        "level": job.get("required_level"),
        "levels": job_levels(job),
        "min_years": job.get("min_years"),
        "required_skills": _as_strings(job.get("skills_required"))[:12],
    }


def _as_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, dict):
        return [str(item) for items in value.values() for item in (items if isinstance(items, list) else [items]) if item]
    return [str(value)]


def _safe_records(value: Any, allowed_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [
        {key: record[key] for key in allowed_fields if key in record and record[key] not in (None, "", [])}
        for record in value
        if isinstance(record, dict)
    ]


