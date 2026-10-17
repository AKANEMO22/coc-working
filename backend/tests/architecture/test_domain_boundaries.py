"""Architectural contracts for a modular monolith, without provider calls."""

import ast
import json
from pathlib import Path
from types import SimpleNamespace

from app.domains.candidate import facade as candidate_facade
from app.main import create_app
from app.shared.paths import BACKEND_ROOT, PROJECT_ROOT
from app.shared.config import Settings
from app.domains.interview.websocket import router as websocket_router


def imports_in(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            yield node.module
        elif isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)


def test_cross_domain_dependencies_use_public_facades_only():
    errors = []
    public = {
        "candidate": {"CandidateDataNotFound", "load_session_context", "persist_candidate_selection", "sample_pair_metadata"},
        "interview": {"get_interview_catalog", "framework_context", "copies_reference", "framework_guidance"},
    }
    for path in (BACKEND_ROOT / "app" / "domains").rglob("*.py"):
        owner = path.relative_to(BACKEND_ROOT / "app" / "domains").parts[0]
        for module in imports_in(path):
            if module.startswith("app.domains."):
                target = module.split(".")[2]
                if target != owner and module != f"app.domains.{target}.facade":
                    errors.append(f"{path.name}: {owner} imports {module}")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app.domains.") and node.module.endswith(".facade"):
                target = node.module.split(".")[2]
                if target != owner:
                    for name in node.names:
                        if name.name not in public.get(target, set()):
                            errors.append(f"{path.name}: non-public facade member {target}.{name.name}")
    assert not errors, "\n".join(errors)


def test_shared_and_production_code_do_not_depend_on_legacy_tools_or_old_layers():
    forbidden = ("app.services", "app.core", "app.models", "app.api", "app.websocket", "tools")
    errors = []
    for path in (BACKEND_ROOT / "app").rglob("*.py"):
        for module in imports_in(path):
            if any(module == name or module.startswith(name + ".") for name in forbidden):
                errors.append(f"{path.name}: {module}")
            if "shared" in path.relative_to(BACKEND_ROOT / "app").parts and module.startswith("app.domains."):
                errors.append(f"shared depends on a domain: {path.name}: {module}")
    assert not errors, "\n".join(errors)


def test_domains_do_not_create_independent_fastapi_apps():
    for path in (BACKEND_ROOT / "app" / "domains").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id != "FastAPI", f"Independent app created in {path}"


def test_interview_does_not_read_or_write_candidate_cache_directly():
    for path in (BACKEND_ROOT / "app" / "domains" / "interview").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "get_cached_candidate_memory(" not in source, path
        assert "cache_candidate_memory(" not in source, path


def test_candidate_facade_snapshot_excludes_raw_cv_and_contact_fields(monkeypatch):
    candidate = {
        "candidate_id": "LOCAL_CV", "canonical_role_id": "LOCAL_ROLE", "target_role": "Local Engineer",
        "email": "private@example.invalid", "phone": "private-phone", "raw_cv": "private-raw-cv",
        "technical_skills": ["Python"], "projects": [{"name": "Queue", "description": "bounded queue"}],
    }
    catalog = SimpleNamespace(get_candidate=lambda _id: candidate, get_job=lambda _id: None)
    monkeypatch.setattr(candidate_facade, "get_candidate_catalog", lambda: catalog)
    monkeypatch.setattr(candidate_facade.RedisSessionManager, "get_cached_candidate_memory", lambda *_: {})

    def unexpected_write(*_args, **_kwargs):
        raise AssertionError("Context reads must not persist before framework validation")

    monkeypatch.setattr(candidate_facade.RedisSessionManager, "cache_candidate_memory", unexpected_write)
    snapshot = candidate_facade.load_session_context("LOCAL", candidate_id="LOCAL_CV")
    serialized = json.dumps(snapshot.model_dump())
    assert snapshot.source_candidate_id == "LOCAL_CV"
    assert snapshot.candidate_context["projects"][0]["name"] == "Queue"
    assert all(secret not in serialized for secret in ("private@example.invalid", "private-phone", "private-raw-cv"))


def test_runtime_paths_are_source_anchored_and_old_folders_have_no_source():
    assert Settings.model_config["env_file"] == str(BACKEND_ROOT / ".env")
    assert Path(Settings.model_fields["normalized_data_dir"].default) == PROJECT_ROOT / "data" / "normalized"
    for old in ("api", "core", "models", "services", "websocket"):
        assert not list((BACKEND_ROOT / "app" / old).rglob("*.py"))
    assert not list((BACKEND_ROOT / "scratch").rglob("*.py"))


def test_existing_rest_and_websocket_route_addresses_are_preserved():
    app = create_app()
    routes = set(app.openapi()["paths"])
    routes.update(route.path for route in websocket_router.routes if hasattr(route, "path"))
    expected = {
        "/health", "/api/v1/health", "/api/v1/cv/upload", "/api/v1/cv/interview-catalog",
        "/api/v1/cv/interview-catalog/{framework_id}/sample", "/api/v1/cv/interview-seeds",
        "/api/v1/sessions/create", "/api/v1/sessions/initiate", "/api/v1/sessions/live-logs",
        "/api/v1/sessions/{session_id}/state", "/api/v1/sessions/{session_id}/report",
        "/api/v1/questions/bank", "/api/v1/tts/synthesize", "/api/v1/tts/voices",
        "/api/v1/stt/transcribe",
        "/ws/interview/{session_id}",
    }
    assert expected <= routes
