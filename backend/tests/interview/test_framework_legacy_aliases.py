from app.domains.interview.catalog import InterviewCatalog


def _catalog_with(frameworks, monkeypatch):
    catalog = InterviewCatalog(data_dir=".")
    monkeypatch.setattr(catalog, "frameworks", lambda: frameworks)
    return catalog


def test_fullstack_legacy_ids_resolve_only_to_fullstack_framework(monkeypatch):
    frameworks = [
        {"position_id": "IF_FULLSTACK", "canonical_role_id": "ROLE_SOFTWARE_ENGINEER", "role_title": "FullStack Developer"},
        {"position_id": "IF_FE", "canonical_role_id": "ROLE_FRONTEND", "role_title": "Frontend Developer"},
    ]
    catalog = _catalog_with(frameworks, monkeypatch)

    by_legacy_framework_id = catalog.resolve_selection_framework("IF_FS", "ROLE_FULLSTACK", "FullStack Developer Intern")
    by_canonical_role = catalog.resolve_selection_framework(None, "ROLE_FULLSTACK", "FullStack Developer Intern")

    assert by_legacy_framework_id["position_id"] == "IF_FULLSTACK"
    assert by_canonical_role["position_id"] == "IF_FULLSTACK"
    assert catalog.resolve_selection_framework("IF_FS", "ROLE_FRONTEND", "Frontend Developer") is None


def test_legacy_general_framework_uses_specific_title_and_fails_closed_when_ambiguous(monkeypatch):
    frameworks = [
        {"position_id": "IF_BE_JAVA", "canonical_role_id": "ROLE_BACKEND_JAVA", "role_title": "Backend Java"},
        {"position_id": "IF_BE_PHP", "canonical_role_id": "ROLE_BACKEND_PHP", "role_title": "Backend PHP"},
        {"position_id": "IF_SWD", "canonical_role_id": "ROLE_SOFTWARE_DEVELOPER", "role_title": "Software Developer"},
    ]
    catalog = _catalog_with(frameworks, monkeypatch)

    java_backend = catalog.resolve_selection_framework(
        "IF_DEV_GENERAL", "ROLE_SOFTWARE_DEVELOPER", "Backend Developer (Java / Spring Boot)"
    )
    ambiguous = catalog.resolve_selection_framework(
        "IF_DEV_GENERAL", "ROLE_SOFTWARE_DEVELOPER", "Software Developer Java, .NET and JavaScript"
    )

    assert java_backend["position_id"] == "IF_BE_JAVA"
    assert ambiguous is None
