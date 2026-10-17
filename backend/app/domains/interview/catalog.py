"""Interview domain owns role frameworks, rubric guidance and reference questions.

Candidate samples are requested through the candidate public facade; this
module does not query candidate/job repositories directly.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any
import re
import unicodedata

from app.shared.infrastructure.normalized_data import get_normalized_data_store
from app.shared.text import token_similarity as _similarity
from app.domains.candidate.facade import sample_pair_metadata


# Explicit ID migrations between the independently normalized job and framework
# files. These aliases are data identity, not fuzzy guesses.
LEGACY_FRAMEWORK_ID_ALIASES = {
    "IF_FS": "IF_FULLSTACK",
}
CANONICAL_ROLE_FRAMEWORK_ALIASES = {
    "ROLE_FULLSTACK": "IF_FULLSTACK",
}


def _legacy_general_framework_id(role: str | None) -> str | None:
    """Resolve only clear specialties from legacy IF_DEV_GENERAL titles.

    Ambiguous/broad titles return None so the caller cannot silently pick an
    unrelated framework. This is a narrow migration for existing normalized IDs.
    """
    if not role:
        return None
    text = unicodedata.normalize("NFKD", role.casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-z0-9+#.]+", " ", text)
    words = set(text.split())

    def has(*terms: str) -> bool:
        return any(term in text for term in terms)

    # Most specific role identities first.
    if has("fullstack", "full stack", "full-stack"):
        return "IF_FULLSTACK"
    if has("unity", "game developer", "game programmer"):
        return "IF_UNITY"
    if has("automation test", "test automation", "automation qa", "sdet"):
        return "IF_AUTO_QA"
    if has("qa", "quality assurance", "test engineer", "software tester", "tester"):
        return "IF_QA_QC"
    if has("embedded", "firmware", "mcu", "rtos", "boot loader"):
        return "IF_EMBEDDED"
    if has("android") or "kotlin" in words:
        return "IF_MOBILE_ANDROID" if not has("ios", "swift", "iphone") else None
    if has("ios", "swift", "iphone"):
        return "IF_MOBILE_IOS"
    if has("data analyst", "business intelligence", "bi analyst"):
        return "IF_DA"
    if has("data engineer", "data platform"):
        return "IF_DE"
    if has("ai software", "ai application engineer"):
        return "IF_AI_SWE"
    if has("data scientist", "machine learning", "deep learning", "ai engineer"):
        return "IF_DS" if has("data scientist") else "IF_AI"
    if has("devops", "site reliability", "sre", "cloud engineer"):
        return "IF_DEVOPS"
    if has("network", "telecom", "networking"):
        return "IF_NETWORK"
    if has("erp", "sap", "d365", "dynamics 365"):
        return "IF_ERP"
    if has("business analyst", "ba analyst"):
        return "IF_BA"
    if has("frontend", "front end", "front-end", "react developer", "vue developer", "angular developer"):
        return "IF_FE"
    if has("backend", "back end", "back-end"):
        stacks = [
            has("java", "spring"),
            has(".net", "asp net", "c#", "dotnet"),
            has("php", "laravel"),
        ]
        if sum(stacks) > 1:
            return None
        if stacks[0]:
            return "IF_BE_JAVA"
        if stacks[1]:
            return "IF_BE_NET"
        if stacks[2]:
            return "IF_BE_PHP"
        return "IF_BE_GEN"
    stack_matches = [
        has("java", "spring"),
        has(".net", "asp net", "c#", "dotnet"),
        has("php", "laravel"),
    ]
    if sum(stack_matches) > 1:
        return None
    if stack_matches[0] and has("developer", "programmer", "lap trinh", "engineer"):
        return "IF_BE_JAVA"
    if stack_matches[1] and has("developer", "programmer", "lap trinh", "engineer"):
        return "IF_BE_NET"
    if stack_matches[2] and has("developer", "programmer", "lap trinh", "engineer"):
        return "IF_BE_PHP"
    if has("software engineer", "software engineering"):
        return "IF_SWE"
    if has("software developer", "software development", "programmer", "lap trinh vien"):
        return "IF_SWD"
    return None


class InterviewCatalog:
    def __init__(self, data_dir: str | Path | None = None):
        self.store = get_normalized_data_store(data_dir)
        self.data_dir = self.store.data_dir

    @property
    def available(self) -> bool:
        return self.store.available

    def frameworks(self) -> list[dict[str, Any]]:
        return self.store.read_records("frameworks")

    def get_framework(self, framework_id: str | None) -> dict[str, Any] | None:
        if not framework_id:
            return None
        return next((row for row in self.frameworks() if row.get("position_id") == framework_id), None)

    def resolve_uploaded_cv_role(self, role: str | None) -> dict[str, Any] | None:
        """Resolve only an explicit, recognizable role in an uploaded CV.

        The general fuzzy resolver is intentionally not used here: a bare
        'engineer' or ambiguous AI title must not silently choose a JD.
        """
        return self.get_framework(_legacy_general_framework_id(role))


    def resolve_framework(
        self,
        framework_id: str | None = None,
        canonical_role_id: str | None = None,
        role: str | None = None,
    ) -> dict[str, Any] | None:
        """Resolve by exact dataset ID first, then role identity and text similarity."""
        rows = self.frameworks()
        if framework_id:
            exact = self.get_framework(framework_id)
            if exact:
                return exact

        if canonical_role_id:
            matches = [row for row in rows if row.get("canonical_role_id") == canonical_role_id]
            if matches:
                if role:
                    return max(matches, key=lambda row: _similarity(role, row.get("role_title", "")))
                return matches[0]

        if role:
            ranked = sorted(rows, key=lambda row: _similarity(role, " ".join((
                str(row.get("role_title", "")),
                str(row.get("canonical_role_name", "")),
                str(row.get("role_family", "")),
            ))), reverse=True)
            if ranked and _similarity(role, " ".join((ranked[0].get("role_title", ""), ranked[0].get("canonical_role_name", "")))) >= 0.16:
                return ranked[0]
        return None


    def resolve_selection_framework(
        self, framework_id: str | None = None, canonical_role_id: str | None = None, role: str | None = None,
    ) -> dict[str, Any] | None:
        """Resolve a CV/JD's metadata, without inventing an unrelated default.

        Legacy IDs can differ between normalized files; canonical identity is
        the fallback. A known but unsupported role must not match on 'Engineer'.
        """
        exact = self.get_framework(framework_id)
        role_alias_id = CANONICAL_ROLE_FRAMEWORK_ALIASES.get(canonical_role_id or "")
        if exact and (
            not canonical_role_id
            or exact.get("canonical_role_id") == canonical_role_id
            or role_alias_id == exact.get("position_id")
        ):
            return exact

        legacy_framework_id = LEGACY_FRAMEWORK_ID_ALIASES.get(framework_id or "")
        if legacy_framework_id:
            if canonical_role_id not in {None, "ROLE_FULLSTACK"}:
                return None
            legacy = self.get_framework(legacy_framework_id)
            if legacy:
                return legacy

        if role_alias_id:
            aliased = self.get_framework(role_alias_id)
            if aliased:
                return aliased

        # This legacy pair is too broad to resolve by ID alone. Use a specific
        # title rule before the generic canonical role's framework.
        if framework_id == "IF_DEV_GENERAL" or canonical_role_id == "ROLE_SOFTWARE_DEVELOPER":
            inferred_id = _legacy_general_framework_id(role)
            inferred = self.get_framework(inferred_id)
            return inferred

        if canonical_role_id:
            matches = [row for row in self.frameworks() if row.get("canonical_role_id") == canonical_role_id]
            if matches:
                return max(matches, key=lambda row: _similarity(role or "", row.get("role_title", "")))

        if exact:
            # Do not fall back from a conflicting but known ID unless canonical
            # identity resolved to an explicit framework above.
            return None

        # Use role-text fallback only when normalized data supplied no canonical
        # identity at all; an explicit but unsupported role ID must fail closed.
        return self.resolve_framework(role=role) if not canonical_role_id else None

    def sample_pair(self, framework_id: str | None = None) -> dict[str, Any] | None:
        framework = self.get_framework(framework_id)
        if not framework:
            return None
        metadata = sample_pair_metadata(framework, data_dir=self.data_dir)
        return {"framework": framework, **metadata} if metadata else None

    def public_catalog(self) -> dict[str, Any]:
        entries: list[dict[str, Any]] = []
        for framework in self.frameworks():
            pair = self.sample_pair(str(framework.get("position_id", "")))
            candidate = pair["candidate"] if pair else None
            job = pair["job"] if pair else None
            entries.append({
                "framework_id": framework.get("position_id"),
                "role_title": framework.get("role_title"),
                "canonical_role_id": framework.get("canonical_role_id"),
                "canonical_role_name": framework.get("canonical_role_name"),
                "role_family": framework.get("role_family"),
                "major_category": framework.get("major_category"),
                "target_levels": framework.get("target_levels", []),
                "target_competencies": framework.get("target_competencies", []),
                "sample_candidate": candidate,
                "sample_job": job,
            })
        return {"available": self.available, "frameworks": entries}


    def framework_question_bank(self, framework_id: str | None = None, role: str | None = None) -> list[dict[str, Any]]:
        framework = self.resolve_framework(framework_id=framework_id, role=role)
        if not framework:
            return []
        result: list[dict[str, Any]] = []
        for item in framework.get("behavioral_questions", []) or []:
            if not isinstance(item, dict) or not item.get("question"):
                continue
            result.append(_normalize_question(item, framework, behavioral=True))
        for item in framework.get("technical_questions", []) or []:
            if not isinstance(item, dict) or not item.get("question"):
                continue
            result.append(_normalize_question(item, framework, behavioral=False))
        return result


def framework_context(framework: dict[str, Any] | None) -> dict[str, Any]:
    if not framework:
        return {}
    return {
        "framework_id": framework.get("position_id"),
        "role_title": framework.get("role_title"),
        "role_family": framework.get("role_family"),
        "target_levels": framework.get("target_levels", []),
        "competencies": framework.get("target_competencies", []),
        "interview_stages": framework.get("interview_stages", []),
        "evaluation_matrix": framework.get("evaluation_matrix", []),
        "scoring_anchors": framework.get("scoring_anchors", {}),
        "passing_thresholds": framework.get("passing_thresholds", {}),
        "evaluation_rubric": framework.get("evaluation_rubric", {}),
    }


def _normalize_question(item: dict[str, Any], framework: dict[str, Any], behavioral: bool) -> dict[str, Any]:
    text = str(item.get("question", "")).strip()
    lower = text.casefold()
    if behavioral:
        stage = "cv_project_defense" if any(token in lower for token in ("dự án", "bug", "sự cố", "bất đồng", "nhóm")) else "hr_motivation"
        rubric = "star_framework" if stage == "cv_project_defense" else "hr_motivation"
    else:
        scenario = any(token in lower for token in ("giả sử", "nếu ", "tình huống", "thiết kế hệ thống", "production"))
        stage = "applied_scenario" if scenario else "technical_core"
        rubric = "case_study" if scenario else "technical_correctness"
    return {
        "id": item.get("id") or f"{framework.get('position_id')}_{len(text)}",
        "question": text,
        "stage": stage,
        "rubric_type": rubric,
        "difficulty": _level_difficulty(item.get("level")),
        "expected_concepts": [framework.get("canonical_role_name") or framework.get("role_title")],
        "expected_answer": item.get("expected_answer"),
        "evaluation_focus": item.get("evaluation_focus"),
        "source": f"Normalized framework {framework.get('position_id')}",
        "url": "",
    }


def _level_difficulty(level: Any) -> int:
    value = str(level or "").casefold()
    if any(token in value for token in ("senior", "lead", "expert")):
        return 4
    if any(token in value for token in ("junior", "middle", "mid")):
        return 3
    return 2


@lru_cache(maxsize=1)
def get_interview_catalog() -> InterviewCatalog:
    return InterviewCatalog()
