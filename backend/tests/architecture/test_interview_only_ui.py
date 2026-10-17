"""Prevent the removed CV Lab UI/optimization branch from returning."""

from app.shared.paths import PROJECT_ROOT
from app.domains.candidate.services.cv_analyzer import CVAnalyzer

FRONTEND = PROJECT_ROOT / "frontend"


def test_ui_has_no_separate_cv_product():
    assert not (FRONTEND / "src/app/cv-lab/page.tsx").exists()
    assert not (FRONTEND / "src/components/cv/GapAnalysisCard.tsx").exists()
    for path in (FRONTEND / "src").rglob("*.tsx"):
        text = path.read_text(encoding="utf-8")
        assert 'href="/cv-lab"' not in text, path
        assert 'href: "/cv-lab"' not in text, path
        assert "Lab Tối ưu CV" not in text, path
        assert "Phân Hệ 2" not in text, path
    header = (FRONTEND / "src/components/common/Header.tsx").read_text(encoding="utf-8")
    assert '{ href: "/interview", label: "Phòng Phỏng vấn" }' in header
    assert "Trang chủ" not in header
    upload = (FRONTEND / "src/components/cv/CVUploader.tsx").read_text(encoding="utf-8")
    assert "ATS" not in upload


def test_home_and_legacy_bookmarks_go_to_interview():
    home = (FRONTEND / "src/app/page.tsx").read_text(encoding="utf-8")
    config = (FRONTEND / "next.config.ts").read_text(encoding="utf-8")
    assert 'redirect("/interview")' in home
    assert 'source: "/cv-lab", destination: "/interview", permanent: true' in config


def test_candidate_service_no_longer_scores_cv_optimization():
    assert not hasattr(CVAnalyzer, "audit_ats_compliance")
    assert not hasattr(CVAnalyzer, "score_xyz_formula")


def test_framework_is_derived_after_cv_jd_selection_not_a_manual_prerequisite():
    page = (FRONTEND / "src/app/interview/page.tsx").read_text(encoding="utf-8")
    assert "resolveInterviewFramework(catalog, candidate, job, useUploadedCv)" in page
    assert "jobsMatchingCandidate(selectableJobs, candidate)" in page
    assert 'id="job-role-filter"' not in page
    assert 'id="job-level-filter"' not in page
    assert 'id="auto-framework"' in page
    assert 'id="framework-choice"' not in page
    assert "selectedFrameworkId" not in page
    assert "compatibleJobs" not in page  # CV metadata now narrows JD choices explicitly.
