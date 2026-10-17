"""Legacy question-bank adapter: normalized data only, no web discovery.

The app now reads InterviewCatalog directly. Keep these imports for older local
scripts, but do not initialize a crawler, external search client, or Redis bank.
"""

# Manual tool bootstrap: no imports or network runs from the production app.
import sys
from pathlib import Path
_WORKSPACE = next(parent for parent in Path(__file__).resolve().parents if (parent / "backend" / "app" / "main.py").is_file())
sys.path[:0] = [str(_WORKSPACE), str(_WORKSPACE / "backend")]

from typing import Any

from app.domains.interview.catalog import get_interview_catalog

COMPANY_KNOWLEDGE_VAULTS: dict[str, list[dict[str, Any]]] = {}


class ModelOrchestratorService:
    def get_ingested_questions(
        self, company: str, role: str, framework_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return get_interview_catalog().framework_question_bank(framework_id=framework_id, role=role)

    def _get_vault_questions_for_role(
        self, company: str, role: str,
        web_results: list[dict[str, Any]] | None = None,
        framework_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.get_ingested_questions(company, role, framework_id)

    async def execute_discovery_and_ingest(
        self, company: str, role: str, student_id: str | None = None,
    ) -> dict[str, Any]:
        raise RuntimeError("Web discovery/crawl has been removed; use the normalized interview catalog.")


_orchestrator_service: ModelOrchestratorService | None = None


def get_orchestrator_service() -> ModelOrchestratorService:
    global _orchestrator_service
    if _orchestrator_service is None:
        _orchestrator_service = ModelOrchestratorService()
    return _orchestrator_service
