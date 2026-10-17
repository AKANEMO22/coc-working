"""Compatibility import for the organized interview-domain package."""

# Manual tool bootstrap: no imports or network runs from the production app.
import sys
from pathlib import Path
_WORKSPACE = next(parent for parent in Path(__file__).resolve().parents if (parent / "backend" / "app" / "main.py").is_file())
sys.path[:0] = [str(_WORKSPACE), str(_WORKSPACE / "backend")]

from app.domains.interview.services.questions import QuestionService, get_question_service

__all__ = ["QuestionService", "get_question_service"]
